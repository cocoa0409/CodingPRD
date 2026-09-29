"""Professional-gear declarations and their verification (PRD §3.6)."""

from flask import Blueprint

from db import base_record, by_seq, db, mark_fresh, touch
from errors import ApiError
from middleware import (
    ROLE_MOVE_COUNSELOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SERVICE_MEMBER,
    ROLE_TSP_COORDINATOR,
    acting_user_id,
    endpoint,
    require_ownership,
)
from paging import list_response
from response import created, ok
from serializers import serialize
from services import calculations as calc
from services import ledger
from validation import bad, get_body, req_enum, req_int, req_str

bp = Blueprint("progear", __name__)


def _owner_cap(shipment, owner):
    entitlement = db.entitlements.get(shipment["entitlement_id"])
    if owner == "MEMBER":
        if entitlement is not None:
            return entitlement["pro_gear_member_allowance_lbs"]
        return calc.PRO_GEAR_MEMBER_CAP_LBS
    if entitlement is not None:
        return entitlement["pro_gear_spouse_allowance_lbs"]
    return 0


def _verified_total(shipment_id, owner, exclude_id):
    total = 0
    for declaration in db.pro_gear_declarations.values():
        if declaration["shipment_id"] != shipment_id or declaration["owner"] != owner:
            continue
        if declaration["id"] == exclude_id:
            continue
        if declaration["status"] not in ("VERIFIED", "PARTIALLY_VERIFIED"):
            continue
        total += declaration["verified_weight_lbs"]
    return total


def _recompute_chain(declaration):
    shipment = db.shipments.get(declaration["shipment_id"])
    if shipment is None:
        return
    ledger.recompute_shipment_weight(shipment)
    entitlement = db.entitlements.get(shipment["entitlement_id"])
    if entitlement is not None:
        ledger.recompute_entitlement_ledger(entitlement, cascade=True)


@bp.post("/shipments/<shipment_id>/pro-gear-declarations")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR])
def declare_pro_gear(shipment_id):
    body = get_body()
    owner = req_enum(body, "owner", calc.PRO_GEAR_OWNERS)
    item_description = req_str(body, "item_description")
    claimed_weight = req_int(body, "claimed_weight_lbs", minimum=1, maximum=2500)
    documentation_type = req_enum(body, "documentation_type", calc.DOCUMENTATION_TYPES)

    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))

    record = base_record()
    record.update(
        {
            "shipment_id": shipment["id"],
            "owner": owner,
            "item_description": item_description,
            "claimed_weight_lbs": claimed_weight,
            "documentation_type": documentation_type,
            "verified_weight_lbs": 0,
            "verified_by_user_id": None,
            "rejection_reason": None,
            "resubmission_count": 0,
            "status": "SUBMITTED",
        }
    )
    mark_fresh(record)
    db.pro_gear_declarations[record["id"]] = record
    return created(serialize(record))


@bp.get("/shipments/<shipment_id>/pro-gear-declarations")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def list_shipment_pro_gear(shipment_id):
    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))
    records = by_seq(
        [d for d in db.pro_gear_declarations.values() if d["shipment_id"] == shipment["id"]]
    )
    return list_response(records)


@bp.get("/pro-gear-declarations/<declaration_id>")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def read_pro_gear(declaration_id):
    declaration = ledger.get_declaration(declaration_id)
    shipment = db.shipments[declaration["shipment_id"]]
    require_ownership(ledger.member_of_shipment(shipment))
    return ok(serialize(declaration))


@bp.post("/pro-gear-declarations/<declaration_id>/verify")
@endpoint([ROLE_MOVE_COUNSELOR])
def verify_pro_gear(declaration_id):
    body = get_body()
    verified_weight = req_int(body, "verified_weight_lbs", minimum=0)

    declaration = ledger.get_declaration(declaration_id)

    if declaration["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_PRO_GEAR_STATE", "Only a submitted declaration may be verified."
        )
    if declaration["documentation_type"] == "NONE":
        raise ApiError(
            "ERR_PRO_GEAR_DOCUMENTATION_REQUIRED",
            "Supporting documentation is required before verification.",
        )
    if verified_weight > declaration["claimed_weight_lbs"]:
        raise ApiError(
            "ERR_PRO_GEAR_CAP_EXCEEDED", "The verified weight exceeds the claimed weight."
        )

    shipment = db.shipments[declaration["shipment_id"]]
    cap = _owner_cap(shipment, declaration["owner"])
    running = _verified_total(shipment["id"], declaration["owner"], declaration["id"])
    if running + verified_weight > cap:
        raise ApiError(
            "ERR_PRO_GEAR_CAP_EXCEEDED", "The verified weight exceeds the owner's allowance."
        )
    if verified_weight <= 0:
        raise bad("Field 'verified_weight_lbs' must be greater than zero.")

    declaration["verified_weight_lbs"] = verified_weight
    declaration["verified_by_user_id"] = acting_user_id()
    declaration["status"] = (
        "VERIFIED" if verified_weight == declaration["claimed_weight_lbs"] else "PARTIALLY_VERIFIED"
    )
    touch(declaration)
    _recompute_chain(declaration)
    return ok(serialize(declaration))


@bp.post("/pro-gear-declarations/<declaration_id>/reject")
@endpoint([ROLE_MOVE_COUNSELOR])
def reject_pro_gear(declaration_id):
    body = get_body()
    rejection_reason = req_str(body, "rejection_reason")

    declaration = ledger.get_declaration(declaration_id)

    if declaration["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_PRO_GEAR_STATE", "Only a submitted declaration may be rejected."
        )

    declaration["verified_weight_lbs"] = 0
    declaration["verified_by_user_id"] = acting_user_id()
    declaration["rejection_reason"] = rejection_reason
    declaration["status"] = "REJECTED"
    touch(declaration)
    _recompute_chain(declaration)
    return ok(serialize(declaration))


@bp.post("/pro-gear-declarations/<declaration_id>/resubmit")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR])
def resubmit_pro_gear(declaration_id):
    body = get_body()
    claimed_weight = req_int(body, "claimed_weight_lbs", minimum=1, maximum=2500)
    documentation_type = req_enum(body, "documentation_type", calc.DOCUMENTATION_TYPES)

    declaration = ledger.get_declaration(declaration_id)
    shipment = db.shipments[declaration["shipment_id"]]
    require_ownership(ledger.member_of_shipment(shipment))

    if declaration["status"] != "REJECTED":
        raise ApiError(
            "ERR_INVALID_PRO_GEAR_STATE", "Only a rejected declaration may be resubmitted."
        )
    if declaration["resubmission_count"] >= calc.PRO_GEAR_RESUBMISSION_LIMIT:
        raise ApiError(
            "ERR_PRO_GEAR_RESUBMISSION_LIMIT", "This declaration has already been resubmitted twice."
        )

    declaration["claimed_weight_lbs"] = claimed_weight
    declaration["documentation_type"] = documentation_type
    declaration["resubmission_count"] += 1
    declaration["rejection_reason"] = None
    declaration["status"] = "SUBMITTED"
    touch(declaration)
    return ok(serialize(declaration))
