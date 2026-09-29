"""End-of-contract removal, sanitization and settlement (PRD 3.9)."""
from flask import Blueprint

import calc
import cascade
import derive
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from errors import fail
from resolve import get_contract, get_removal
from store import db, new_row, touch

bp = Blueprint("removals", __name__)

SANITIZATION_METHODS = ("NONE", "CRYPTO_ERASE", "OVERWRITE_3PASS", "PHYSICAL_DESTRUCTION")
IN_FLIGHT_REMOVAL_STATES = ("REQUESTED", "SCHEDULED", "COLLECTED", "SANITIZED")
READ_ROLES = ("AccountManager", "BillingAnalyst", "FieldTechnician")


@bp.post("/removal-orders")
def create_removal():
    require("AccountManager")
    body = v.body()
    contract_id = v.id_field(body, "contract_id")
    scheduled_for = v.dt_field(body, "scheduled_for")
    contract = get_contract(contract_id)

    if contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_INVALID_STATE",
             "A contract in %s cannot start a wind-down." % contract["status"])
    for row in db.removals.values():
        if row["contract_id"] == contract["id"] and row["status"] in IN_FLIGHT_REMOVAL_STATES:
            fail("ERR_CONTRACT_INVALID_STATE",
                 "The contract already has a removal order in flight.")
    if scheduled_for < db.clock:
        fail("ERR_SCHEDULE_IN_PAST", "Field 'scheduled_for' must not be before the logical clock.")

    row = new_row()
    row.update({
        "contract_id": contract["id"],
        "status": "REQUESTED",
        "scheduled_for": scheduled_for,
        "sanitization_method": "NONE",
        "sanitization_certificate_ref": None,
        "unbilled_pages_charge_cents": 0,
        "early_termination_fee_applied_cents": 0,
        "device_residual_credit_cents": 0,
        "gross_settlement_cents": 0,
        "sanitization_fee_cents": 0,
        "net_settlement_cents": 0,
        "settled_at": None,
    })
    db.removals[row["id"]] = row
    contract["status"] = "TERMINATING"
    touch(contract)
    for device in derive.contract_devices(contract["id"]):
        if device["lifecycle_state"] in derive.FLEET_STATES:
            device["removal_order_id"] = row["id"]
    return created(serialize.removal(row))


@bp.get("/removal-orders/<removal_id>")
def read_removal(removal_id):
    require(*READ_ROLES)
    removal = get_removal(removal_id)
    return ok(serialize.removal(removal))


@bp.get("/removal-orders")
def list_removals():
    require(*READ_ROLES)
    rows = db.sorted_rows("removals")
    for field in ("contract_id", "status"):
        value = v.query_filter(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    data, meta = v.paginate(rows, serialize.removal)
    return ok_list(data, meta)


@bp.post("/removal-orders/<removal_id>/schedule")
def schedule_removal(removal_id):
    require("AccountManager")
    removal = get_removal(removal_id)
    body = v.body()
    scheduled_for = v.dt_field(body, "scheduled_for")
    if removal["status"] != "REQUESTED":
        fail("ERR_REMOVAL_INVALID_STATE",
             "A removal order in %s cannot be scheduled." % removal["status"])
    if scheduled_for < db.clock:
        fail("ERR_SCHEDULE_IN_PAST", "Field 'scheduled_for' must not be before the logical clock.")
    removal["status"] = "SCHEDULED"
    removal["scheduled_for"] = scheduled_for
    touch(removal)
    return ok(serialize.removal(removal))


@bp.post("/removal-orders/<removal_id>/collect")
def collect_removal(removal_id):
    require("FieldTechnician")
    removal = get_removal(removal_id)
    v.body()
    if removal["status"] != "SCHEDULED":
        fail("ERR_REMOVAL_INVALID_STATE",
             "A removal order in %s cannot be collected." % removal["status"])
    covered = derive.covered_devices(removal["id"])
    for device in covered:
        if derive.device_in_flight_tickets(device["id"]):
            fail("ERR_REMOVAL_INVALID_STATE",
                 "A covered device still has a service ticket in progress.")
    if db.clock < removal["scheduled_for"]:
        fail("ERR_COLLECTION_NOT_DUE",
             "Collection is not due until the scheduled instant.")

    for device in covered:
        if device["lifecycle_state"] in derive.FLEET_STATES:
            device["lifecycle_state"] = "RETRIEVED"
            touch(device)
    removal["status"] = "COLLECTED"
    touch(removal)
    return ok(serialize.removal(removal))


@bp.post("/removal-orders/<removal_id>/sanitize")
def sanitize_removal(removal_id):
    require("FieldTechnician")
    removal = get_removal(removal_id)
    body = v.body()
    method = v.enum_field(body, "sanitization_method", SANITIZATION_METHODS,
                          required=False, default=None)
    certificate = v.string_field(body, "sanitization_certificate_ref",
                                 required=False, non_empty=False, max_len=120, default=None)
    if removal["status"] != "COLLECTED":
        fail("ERR_REMOVAL_INVALID_STATE",
             "A removal order in %s cannot be sanitized." % removal["status"])
    if method is None or method == "NONE" or certificate is None or not certificate.strip():
        fail("ERR_SANITIZATION_EVIDENCE_MISSING",
             "A real sanitization method and a non-empty certificate reference are required.")

    removal["sanitization_method"] = method
    removal["sanitization_certificate_ref"] = certificate
    removal["status"] = "SANITIZED"
    touch(removal)
    cascade.sanitize_devices(removal)
    return ok(serialize.removal(removal))


@bp.post("/removal-orders/<removal_id>/settle")
def settle_removal(removal_id):
    require("BillingAnalyst")
    removal = get_removal(removal_id)
    v.body()
    if removal["status"] != "SANITIZED":
        fail("ERR_REMOVAL_INVALID_STATE",
             "A removal order in %s cannot be settled." % removal["status"])
    contract = db.contracts.get(removal["contract_id"])
    if contract is None or contract["status"] != "TERMINATING":
        fail("ERR_CONTRACT_INVALID_STATE",
             "Settlement requires the contract to be TERMINATING.")
    for period in derive.contract_periods(contract["id"]):
        if period["period_end"] <= db.clock and period["status"] != "CLOSED":
            fail("ERR_SETTLEMENT_PERIOD_OPEN",
                 "A billing period that has already ended is not CLOSED yet.")

    figures = calc.settlement_amount(removal, contract, db.clock)
    removal.update(figures)
    removal["status"] = "SETTLED"
    removal["settled_at"] = db.clock
    touch(removal)
    contract["status"] = "CLOSED"
    touch(contract)
    return ok(serialize.removal(removal))
