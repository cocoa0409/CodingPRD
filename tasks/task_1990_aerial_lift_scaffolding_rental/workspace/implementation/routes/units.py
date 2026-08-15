"""Equipment units: register, list, read, recover."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import ok, created, paginate
from services import calc, domain
from validation import validate_body

bp = Blueprint("units", __name__)


@bp.post("/equipment-units")
def create_unit():
    uid, role = get_context()
    require_roles(["BranchManager"])
    body = validate_body({
        "class_id": ("string", True),
        "serial_number": ("string", True),
        "ansi_standard_ref": ("string", True),
    })
    if body["class_id"] not in store.classes:
        raise ApiError("ERR_NOT_FOUND", 404, "Equipment class not found")
    for existing in store.units.values():
        if existing["serial_number"] == body["serial_number"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "serial_number must be unique across the fleet")
    unit = db.new_common({
        "id": db.new_id(),
        "class_id": body["class_id"],
        "serial_number": body["serial_number"],
        "ansi_standard_ref": body["ansi_standard_ref"],
        "status": "AVAILABLE",
        # Factory pre-delivery inspection: stamped from the logical clock date.
        "last_annual_inspection_date": db.logical_date().isoformat(),
    })
    store.units[unit["id"]] = unit
    return created(domain.view_unit(unit))


@bp.get("/equipment-units")
def list_units():
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "YardTechnician"])
    rows = [domain.view_unit(u) for u in store.units.values()]
    rows = paginate.filter(rows, "class_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/equipment-units/<uid_>")
def get_unit(uid_):
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "YardTechnician"])
    unit = store.units.get(uid_)
    if unit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Equipment unit not found")
    return ok(domain.view_unit(unit))


@bp.post("/equipment-units/<uid_>/recover")
def recover_unit(uid_):
    uid, role = get_context()
    require_roles(["BranchManager"])
    unit = store.units.get(uid_)
    if unit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Equipment unit not found")
    if unit["status"] != "LOST":
        raise ApiError("ERR_INVALID_STATE", 409, "Unit is not LOST")
    # Recovery credit: every CHARGED LOST/STOLEN claim on this unit that has not
    # yet received a credit gets 80% of its chargeback, rounded half-up per claim.
    for claim in store.claims.values():
        if claim["unit_id"] != unit["id"]:
            continue
        if claim["claim_type"] not in ("LOST", "STOLEN"):
            continue
        if claim["status"] != "CHARGED" or claim["recovery_credit_cents"] is not None:
            continue
        claim["recovery_credit_cents"] = calc.recovery_credit_cents(claim["chargeback_cents"])
        db.touch(claim)
        contract = store.contracts.get(claim["contract_id"])
        if contract is not None:
            db.touch(contract)  # damage_subtotal_cents recomputed (derived view)
            customer = store.customers.get(contract["customer_id"])
            if customer is not None:
                calc.maybe_suspend(customer)
    due = db.parse_date(domain.next_inspection_due(unit["last_annual_inspection_date"]))
    unit["status"] = "AVAILABLE" if db.logical_date() <= due else "QUARANTINED"
    db.touch(unit)
    return ok(domain.view_unit(unit))
