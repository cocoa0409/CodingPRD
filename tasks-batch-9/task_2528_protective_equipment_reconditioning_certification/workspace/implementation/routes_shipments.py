"""IntakeShipment endpoints (PRD 3.3, 3.9)."""
from flask import Blueprint

import calc
import cascades
import db
import helpers
import serialize
import validate
from auth import ALL_ROLES, authorize, check_account_scope
from db import touch
from errors import ApiError

bp = Blueprint("shipments", __name__)

READ_ROLES = ALL_ROLES
LIST_ROLES = ("PlantManager", "IntakeClerk", "ComplianceOfficer", "CustomerContact")


@bp.post("/intake-shipments")
def create_shipment():
    authorize(("IntakeClerk",))
    data = validate.body()
    customer_account_id = validate.req_id(data, "customer_account_id")
    sport = validate.req_enum(data, "sport", calc.SPORTS)
    service_tier = validate.req_enum(data, "service_tier", calc.SERVICE_TIERS)
    declared_unit_count = validate.req_int(data, "declared_unit_count", 1)
    (start, start_raw), (end, end_raw) = validate.req_window(
        data, "season_start_date", "season_end_date")
    helpers.account(customer_account_id)

    record = db.base_record()
    record.update({
        "customer_account_id": customer_account_id,
        "sport": sport,
        "service_tier": service_tier,
        "declared_unit_count": declared_unit_count,
        "season_start_date": start,
        "season_end_date": end,
        "counted_unit_count": None,
        "discrepancy_count": None,
        "discrepancy_resolution": None,
        "units_registered": 0,
        "units_in_process": 0,
        "units_certified": 0,
        "units_condemned": 0,
        "units_released": 0,
        "accepted_at": None,
        "raw_due_at": None,
        "committed_due_at": None,
        "loaner_required": False,
        "provisional_total_cents": None,
        "final_total_cents": None,
        "settlement_locked": False,
        "status": "DRAFT",
    })
    db.raw_set(record, "season_start_date", start_raw)
    db.raw_set(record, "season_end_date", end_raw)
    db.db.intake_shipments[record["id"]] = record
    return helpers.single(record, serialize.intake_shipment, 201)


@bp.get("/intake-shipments/<row_id>")
def get_shipment(row_id):
    caller = authorize(READ_ROLES)
    record = helpers.shipment(row_id)
    check_account_scope(caller, record["customer_account_id"])
    return helpers.single(record, serialize.intake_shipment)


@bp.get("/intake-shipments")
def list_shipments():
    caller = authorize(LIST_ROLES)
    account_id = validate.query_str("customer_account_id")
    status = validate.query_enum("status", calc.SHIPMENT_STATUSES)
    if caller.is_customer:
        # A program contact may only ever see its own shipments.
        if account_id is not None:
            check_account_scope(caller, account_id)
        account_id = caller.user_id
    filters = {"customer_account_id": account_id, "status": status}
    return helpers.listing("intake_shipments", serialize.intake_shipment, filters)


@bp.post("/intake-shipments/<row_id>/count")
def count_shipment(row_id):
    authorize(("IntakeClerk",))
    data = validate.body()
    counted = validate.req_int(data, "counted_unit_count", 1)
    record = helpers.shipment(row_id)
    if record["status"] != "DRAFT":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID",
                       "Counting is only defined for a DRAFT shipment.")

    record["counted_unit_count"] = counted
    record["discrepancy_count"] = counted - record["declared_unit_count"]
    record["status"] = "COUNTED" if record["discrepancy_count"] == 0 else "QUARANTINED"
    touch(record)
    return helpers.single(record, serialize.intake_shipment)


ACCEPT_RESOLUTIONS = {
    "COUNTED": ("MATCHED",),
    "QUARANTINED": ("CUSTOMER_CONFIRMED", "WRITTEN_OFF"),
}


@bp.post("/intake-shipments/<row_id>/accept")
def accept_shipment(row_id):
    authorize(("IntakeClerk",))
    data = validate.body()
    resolution = validate.req_enum(data, "discrepancy_resolution",
                                   calc.DISCREPANCY_RESOLUTIONS)
    record = helpers.shipment(row_id)
    allowed = ACCEPT_RESOLUTIONS.get(record["status"])
    if allowed is None or resolution not in allowed:
        raise ApiError(
            "ERR_SHIPMENT_STATE_INVALID",
            "No accept transition is defined for status %s with resolution %s."
            % (record["status"], resolution))
    if record["units_registered"] != record["counted_unit_count"]:
        raise ApiError("ERR_UNIT_REGISTRATION_INCOMPLETE",
                       "Every counted unit must be registered before acceptance.")
    account = helpers.account(record["customer_account_id"])
    if account["liability_waiver_status"] != "ON_FILE":
        raise ApiError("ERR_LIABILITY_WAIVER_MISSING",
                       "The program has no current liability waiver on file.")

    accepted_at = db.now()
    record["discrepancy_resolution"] = resolution
    record["status"] = "ACCEPTED"
    record["accepted_at"] = accepted_at
    record["units_in_process"] = record["counted_unit_count"]
    record["units_certified"] = 0
    record["units_condemned"] = 0
    record["units_released"] = 0
    raw_due_at, committed_due_at, loaner_required = calc.turnaround_commitment(
        record["service_tier"], record["counted_unit_count"],
        record["season_start_date"], accepted_at)
    record["raw_due_at"] = raw_due_at
    record["committed_due_at"] = committed_due_at
    record["loaner_required"] = loaner_required
    record["provisional_total_cents"] = calc.shipment_settlement_total(
        record, "PROVISIONAL")
    touch(record)
    cascades.bump_open_shipments(account, 1)
    return helpers.single(record, serialize.intake_shipment)


@bp.post("/intake-shipments/<row_id>/settle")
def settle_shipment(row_id):
    authorize(("PlantManager",))
    record = helpers.shipment(row_id)
    # Rung 6 sits ahead of the generic state rung on purpose (PRD 2.7).
    if record["units_in_process"] != 0:
        raise ApiError("ERR_SHIPMENT_NOT_READY",
                       "Units are still in process on this shipment.")
    if record["status"] != "READY_FOR_RETURN":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID",
                       "Settlement is only defined from READY_FOR_RETURN.")
    account = helpers.account(record["customer_account_id"])
    if account["status"] == "BILLING_HOLD":
        raise ApiError("ERR_ACCOUNT_ON_HOLD",
                       "The program's account is on a billing hold.")
    if record["settlement_locked"]:
        raise ApiError("ERR_SETTLEMENT_LOCKED",
                       "This shipment has already been settled.")

    record["final_total_cents"] = calc.shipment_settlement_total(record, "FINAL")
    record["settlement_locked"] = True
    record["status"] = "CLOSED"
    touch(record)
    return helpers.single(record, serialize.intake_shipment)
