"""Resident CRUD + move-in/move-out state machine."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OWNER_DELINQUENT,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success
from services.common import bump, stamp_create
from services.property_occupancy import recompute_for_property
from services.voting_status import recompute_for_owner
from utils import get_body, iso_format, parse_iso, require_field

bp = Blueprint("residents", __name__)


def _owner_is_delinquent(owner_id: str) -> bool:
    """Owner has at least one FeeBill in OVERDUE on any of their properties."""
    property_ids = {p["id"] for p in db.properties.values() if p.get("owner_id") == owner_id}
    return any(
        b.get("status") == "OVERDUE" and b.get("property_id") in property_ids
        for b in db.fee_bills.values()
    )


@bp.post("/residents")
@require_roles("PropertyManager")
def create_resident():
    body = get_body()
    property_id = require_field(body, "property_id")
    full_name = require_field(body, "full_name")
    id_card_no = require_field(body, "id_card_no")
    relation_kind = require_field(body, "relation_kind")
    phone = require_field(body, "phone")

    if relation_kind not in ("FAMILY", "TENANT"):
        raise APIError(ERR_VALIDATION, "relation_kind must be FAMILY or TENANT.", 422)

    prop = db.properties.get(property_id)
    if prop is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"Property {property_id} not found.", 404)

    lease_end_at = body.get("lease_end_at")
    if relation_kind == "TENANT":
        if not lease_end_at:
            raise APIError(ERR_VALIDATION, "lease_end_at is required for TENANT.", 422)

    # Uniqueness: (id_card_no, property_id, relation_kind)
    for r in db.residents.values():
        if (r.get("id_card_no") == id_card_no
                and r.get("property_id") == property_id
                and r.get("relation_kind") == relation_kind):
            raise APIError(ERR_VALIDATION, "Resident already registered for this property/kind.", 422)

    resident = {
        "property_id": property_id,
        "full_name": full_name,
        "id_card_no": id_card_no,
        "relation_kind": relation_kind,
        "phone": phone,
        "lifecycle_status": "PENDING_MOVE_IN",
        "move_in_at": None,
        "move_out_at": None,
        "lease_end_at": iso_format(parse_iso(lease_end_at, field="lease_end_at"))
            if lease_end_at else None,
    }
    stamp_create(resident)
    db.residents[resident["id"]] = resident
    return success(resident, status=201)


@bp.post("/residents/<rid>/move-in")
@require_roles("PropertyManager")
def move_in(rid):
    resident = db.residents.get(rid)
    if resident is None:
        raise APIError(ERR_NOT_FOUND, f"Resident {rid} not found.", 404)
    if resident.get("lifecycle_status") != "PENDING_MOVE_IN":
        raise APIError(ERR_INVALID_STATE, "Resident is not PENDING_MOVE_IN.", 409)

    if resident.get("relation_kind") == "TENANT":
        # Owner of the property must not be delinquent
        prop = db.properties.get(resident["property_id"])
        if prop is not None:
            owner_id = prop.get("owner_id")
            if owner_id and _owner_is_delinquent(owner_id):
                raise APIError(
                    ERR_OWNER_DELINQUENT,
                    "Owner has overdue bills; tenant move-in blocked.",
                    403,
                )
        # lease_end_at must be in the future
        lease_end_str = resident.get("lease_end_at")
        if not lease_end_str:
            raise APIError(ERR_VALIDATION, "lease_end_at missing for tenant.", 422)
        if parse_iso(lease_end_str, field="lease_end_at") <= db.now():
            raise APIError(ERR_VALIDATION, "lease_end_at must be in the future.", 422)

    resident["lifecycle_status"] = "RESIDING"
    resident["move_in_at"] = iso_format(db.now())
    bump(resident)
    recompute_for_property(resident["property_id"])
    return success(resident)


@bp.post("/residents/<rid>/move-out")
@require_roles("PropertyManager")
def move_out(rid):
    resident = db.residents.get(rid)
    if resident is None:
        raise APIError(ERR_NOT_FOUND, f"Resident {rid} not found.", 404)
    if resident.get("lifecycle_status") != "RESIDING":
        raise APIError(ERR_INVALID_STATE, "Resident is not RESIDING.", 409)

    resident["lifecycle_status"] = "MOVED_OUT"
    resident["move_out_at"] = iso_format(db.now())
    bump(resident)
    recompute_for_property(resident["property_id"])

    # Re-evaluate voting status for the owner of this property (e.g. flipping
    # back from INELIGIBLE_NO_PROPERTY).
    prop = db.properties.get(resident["property_id"])
    if prop is not None:
        recompute_for_owner(prop.get("owner_id"))
    return success(resident)
