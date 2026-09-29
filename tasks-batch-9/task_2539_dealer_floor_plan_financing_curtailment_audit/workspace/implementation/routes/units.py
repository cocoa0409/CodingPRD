"""Inventory units, the title-custody dimension, collateral write-downs and the
two computed reads hanging off a unit."""

from flask import Blueprint

import db
import lookup
import middleware
import response
import validate
from errors import ApiError
from services import ledger, serial, spec

bp = Blueprint("units", __name__)

ALL_READ_ROLES = middleware.ALL_ROLES

LEGAL_CUSTODY_MOVES = {
    "NOT_RECEIVED": ("LENDER_HELD", "LOST"),
    "LENDER_HELD": ("LOST", "RELEASED_FOR_SALE"),
    "LOST": ("LENDER_HELD",),
    "RELEASED_FOR_SALE": (),
}


@bp.route("/floorplan/units", methods=["POST"])
def register_unit():
    middleware.require(middleware.DEALER_PRINCIPAL)
    data = validate.body()
    dealer_id = validate.req_ref(data, "dealer_id")
    middleware.guard_dealer_id(dealer_id)
    dealer = lookup.dealer(dealer_id)
    line = lookup.credit_line(validate.req_ref(data, "credit_line_id"))
    if line["dealer_id"] != dealer["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION", "The credit line belongs to another dealership."
        )
    vin = validate.req_str(data, "vin", min_len=17, max_len=17)
    if not validate.upper_alnum(vin):
        validate.bad("vin must be exactly 17 uppercase alphanumeric characters.")
    inventory_class = validate.req_enum(data, "inventory_class", spec.INVENTORY_CLASSES)
    invoice_amount = validate.req_int(data, "invoice_amount_cents", minimum=1)
    invoice_date = validate.req_instant(data, "invoice_date")
    odometer = validate.opt_int(data, "odometer_miles", minimum=0, default=0)
    document_type = validate.req_enum(data, "title_document_type", spec.TITLE_DOCUMENT_TYPES)

    if line["status"] != "ACTIVE":
        raise ApiError("ERR_CREDIT_LINE_NOT_ACTIVE")
    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_NOT_ACTIVE")

    if inventory_class == "NEW" and document_type != "MSO":
        raise ApiError("ERR_MSO_REQUIRED_FOR_NEW_UNIT")
    if inventory_class == "USED" and document_type != "TITLE":
        raise ApiError("ERR_MSO_REQUIRED_FOR_NEW_UNIT")

    for other in ledger.dealer_units(dealer["id"]):
        if other["vin"] == vin and other["funding_status"] != "REPOSSESSED":
            raise ApiError("ERR_DUPLICATE_VIN")

    record = db.insert(
        "inventory_units",
        {
            "dealer_id": dealer["id"],
            "credit_line_id": line["id"],
            "vin": vin,
            "inventory_class": inventory_class,
            "invoice_amount_cents": invoice_amount,
            "invoice_date": db.fmt_instant(invoice_date),
            "odometer_miles": odometer,
            "title_document_type": document_type,
            "funding_status": "REGISTERED",
            "title_custody_status": "NOT_RECEIVED",
            "eligibility_status": "ELIGIBLE",
            "ineligibility_reason_code": None,
            "advance_amount_cents": 0,
            "outstanding_principal_cents": 0,
            "principal_paid_cents": 0,
            "floored_at": None,
            "funded_by_user_id": None,
            "aging_exception_count": 0,
            "curtailment_extension_days_total": 0,
        },
    )
    return response.created(serial.unit(record))


@bp.route("/floorplan/units/<unit_id>", methods=["GET"])
def read_unit(unit_id):
    middleware.require(*ALL_READ_ROLES)
    unit = lookup.unit(unit_id)
    middleware.guard_owned(unit)
    return response.ok(serial.unit(unit))


@bp.route("/floorplan/units", methods=["GET"])
def list_units():
    middleware.require(*ALL_READ_ROLES)
    dealer_id = response.filter_value("dealer_id")
    if dealer_id is not None:
        middleware.guard_dealer_id(dealer_id)
    credit_line_id = response.filter_value("credit_line_id")
    funding_status = response.filter_value("funding_status", spec.FUNDING_STATUSES)
    title_custody_status = response.filter_value(
        "title_custody_status", spec.TITLE_CUSTODY_STATUSES
    )
    eligibility_status = response.filter_value("eligibility_status", spec.ELIGIBILITY_STATUSES)
    inventory_class = response.filter_value("inventory_class", spec.INVENTORY_CLASSES)
    vin = response.filter_value("vin")
    records = response.apply_filters(
        db.rows("inventory_units"),
        [
            ("dealer_id", dealer_id),
            ("credit_line_id", credit_line_id),
            ("funding_status", funding_status),
            ("title_custody_status", title_custody_status),
            ("eligibility_status", eligibility_status),
            ("inventory_class", inventory_class),
            ("vin", vin),
        ],
    )
    scope = middleware.scope_dealer_id()
    if scope is not None:
        records = [r for r in records if r["dealer_id"] == scope]
    return response.paginate(records, serial.unit)


@bp.route("/floorplan/units/<unit_id>/title-custody", methods=["POST"])
def move_title_custody(unit_id):
    middleware.require(middleware.CREDIT_OFFICER)
    unit = lookup.unit(unit_id)
    data = validate.body()
    new_status = validate.req_enum(data, "new_custody_status", spec.TITLE_CUSTODY_STATUSES)
    document_reference = validate.opt_str(data, "document_reference")

    current = unit["title_custody_status"]
    if new_status not in LEGAL_CUSTODY_MOVES[current]:
        raise ApiError("ERR_INVALID_TITLE_TRANSITION")
    if current == "LOST" and new_status == "LENDER_HELD" and not document_reference:
        validate.bad("document_reference is required to recover a lost document.")

    if new_status == "RELEASED_FOR_SALE":
        blocked = int(unit["outstanding_principal_cents"]) != 0
        blocked = blocked or unit["funding_status"] not in ("REGISTERED", "PAID_OFF")
        blocked = blocked or bool(ledger.unit_obligations(unit["id"], ("DUE", "DELINQUENT")))
        blocked = blocked or bool(ledger.unit_incidents(unit["id"], ("OPEN",)))
        if blocked:
            raise ApiError("ERR_TITLE_RELEASE_BLOCKED")

    unit["title_custody_status"] = new_status
    if new_status == "LOST":
        unit["eligibility_status"] = "INELIGIBLE_TITLE_DEFECT"
        unit["ineligibility_reason_code"] = "TITLE_DEFECT"
    elif current == "LOST" and new_status == "LENDER_HELD":
        if unit["ineligibility_reason_code"] == "TITLE_DEFECT":
            unit["eligibility_status"] = "ELIGIBLE"
            unit["ineligibility_reason_code"] = None
    db.touch(unit)
    ledger.recompute_availability(ledger.unit_line(unit))
    return response.ok(serial.unit(unit))


@bp.route("/floorplan/units/<unit_id>/ineligibility", methods=["POST"])
def classify_ineligible(unit_id):
    middleware.require(middleware.CREDIT_OFFICER, middleware.AUDIT_MANAGER)
    unit = lookup.unit(unit_id)
    data = validate.body()
    reason = validate.req_enum(data, "ineligibility_reason_code", spec.INELIGIBILITY_REASONS)
    validate.opt_str(data, "notes", min_len=0)
    if unit["funding_status"] not in spec.COLLATERAL_FUNDING_STATUSES:
        raise ApiError("ERR_UNIT_NOT_FLOORED")
    unit["eligibility_status"] = spec.INELIGIBILITY_MAP[reason]
    unit["ineligibility_reason_code"] = reason
    db.touch(unit)
    line = ledger.unit_line(unit)
    ledger.recompute_availability(line)
    db.touch(line)
    return response.ok(serial.unit(unit))


@bp.route("/floorplan/units/<unit_id>/curtailment-schedule", methods=["GET"])
def read_curtailment_schedule(unit_id):
    middleware.require(
        middleware.CREDIT_OFFICER,
        middleware.CREDIT_RISK_MANAGER,
        middleware.DEALER_PRINCIPAL,
        middleware.SYSTEM_OPERATOR,
    )
    unit = lookup.unit(unit_id)
    middleware.guard_owned(unit)
    obligations = ledger.unit_obligations(unit["id"])
    projected = []
    total = 0
    for obligation in obligations:
        projected.append(
            {
                "obligation_id": obligation["id"],
                "tier_age_days_from": obligation["tier_age_days_from"],
                "tier_cumulative_paydown_bps": obligation["tier_cumulative_paydown_bps"],
                "due_date": obligation["due_date"],
                "projected_principal_cents": obligation["projected_principal_cents"],
                "status": obligation["status"],
            }
        )
        if obligation["status"] not in ("CANCELLED", "SUPERSEDED"):
            total += int(obligation["projected_principal_cents"])
    return response.ok(
        {
            "unit_id": unit["id"],
            "advance_amount_cents": unit["advance_amount_cents"],
            "inventory_class": unit["inventory_class"],
            "basis": "FORWARD_PROJECTED",
            "projected_obligations": projected,
            "projected_total_required_cents": total,
        }
    )


@bp.route("/floorplan/units/<unit_id>/audit-observations", methods=["GET"])
def list_unit_observations(unit_id):
    middleware.require(*ALL_READ_ROLES)
    unit = lookup.unit(unit_id)
    middleware.guard_owned(unit)
    classification = response.filter_value("classification", spec.CLASSIFICATIONS)
    is_out_of_trust = response.filter_bool("is_out_of_trust")
    audit_id = response.filter_value("audit_id")
    records = response.apply_filters(
        [o for o in db.rows("observations") if o["unit_id"] == unit["id"]],
        [
            ("classification", classification),
            ("is_out_of_trust", is_out_of_trust),
            ("audit_id", audit_id),
        ],
    )
    return response.paginate(records, serial.observation)
