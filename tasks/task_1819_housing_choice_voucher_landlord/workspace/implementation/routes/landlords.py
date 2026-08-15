"""Landlord endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import parse_pagination, get_or_404, sorted_page

bp = Blueprint("landlords", __name__)


def _serialize(l):
    return {
        "id": l["id"],
        "legal_name": l["legal_name"],
        "tax_id": l["tax_id"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


@bp.route("/hcv/landlords", methods=["POST"])
def create_landlord():
    require_roles("HousingAuthorityAdmin")
    body = request.get_json(force=True, silent=True) or {}
    legal_name = body.get("legal_name")
    tax_id = body.get("tax_id")
    # tax_id unique across Landlord
    for l in db.landlords.values():
        if l["tax_id"] == tax_id:
            # No dedicated error id for duplicate tax_id; closest generic is invalid state/amount.
            # PRD §3.1 says "duplicate tax ID is rejected at create time" — no explicit error id,
            # use ERR_INVALID_AMOUNT? Better: it's a business conflict. Use 409 ERR_INVALID_STATE is wrong.
            # Scaffold has no ERR_DUPLICATE; treat as validation failure with 422 ERR_INVALID_AMOUNT is wrong too.
            # Best fit from the catalog: none. We'll return 409 ERR_INVALID_STATE as conflict proxy.
            raise errors.APIError(errors.ERR_INVALID_STATE, "tax_id already registered", 409)
    rec = db.make_record({
        "legal_name": legal_name,
        "tax_id": tax_id,
        "status": "ACTIVE",
    })
    db.landlords[rec["id"]] = rec
    return success_object(_serialize(rec), 201)


@bp.route("/hcv/landlords", methods=["GET"])
def list_landlords():
    require_roles("HousingAuthorityAdmin")
    limit, offset = parse_pagination()
    page, total = sorted_page(list(db.landlords.values()), limit, offset)
    return success_list([_serialize(l) for l in page], total, limit, offset)


@bp.route("/hcv/landlords/<lid>", methods=["GET"])
def get_landlord(lid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    l = get_or_404(db.landlords, lid, "Landlord")
    return success_object(_serialize(l))


@bp.route("/hcv/landlords/<lid>/suspend", methods=["POST"])
def suspend_landlord(lid):
    require_roles("HousingAuthorityAdmin")
    l = get_or_404(db.landlords, lid, "Landlord")
    if l["status"] != "ACTIVE":
        raise errors.invalid_state("Landlord must be ACTIVE to suspend")
    l["status"] = "SUSPENDED"
    db.touch(l)
    return success_object(_serialize(l))


@bp.route("/hcv/landlords/<lid>/reinstate", methods=["POST"])
def reinstate_landlord(lid):
    require_roles("HousingAuthorityAdmin")
    l = get_or_404(db.landlords, lid, "Landlord")
    if l["status"] != "SUSPENDED":
        raise errors.invalid_state("Landlord must be SUSPENDED to reinstate")
    l["status"] = "ACTIVE"
    db.touch(l)
    return success_object(_serialize(l))


@bp.route("/hcv/landlords/<lid>/terminate", methods=["POST"])
def terminate_landlord(lid):
    require_roles("HousingAuthorityAdmin")
    l = get_or_404(db.landlords, lid, "Landlord")
    if l["status"] != "ACTIVE":
        raise errors.invalid_state("Landlord must be ACTIVE to terminate")
    # No HAPContract for any of landlord's units in ACTIVE or ABATED
    owned_property_ids = {p["id"] for p in db.properties.values() if p["landlord_id"] == lid}
    owned_unit_ids = {u["id"] for u in db.units.values() if u["property_id"] in owned_property_ids}
    for c in db.hap_contracts.values():
        if c["unit_id"] in owned_unit_ids and c["status"] in ("ACTIVE", "ABATED"):
            raise errors.invalid_state("Landlord has contracts in ACTIVE or ABATED status")
    l["status"] = "TERMINATED"
    db.touch(l)
    return success_object(_serialize(l))


@bp.route("/hcv/landlords/<lid>/properties", methods=["GET"])
def list_landlord_properties(lid):
    require_roles("HousingAuthorityAdmin", "Landlord")
    get_or_404(db.landlords, lid, "Landlord")
    limit, offset = parse_pagination()
    rows = [p for p in db.properties.values() if p["landlord_id"] == lid]
    page, total = sorted_page(rows, limit, offset)
    from routes.properties import serialize_property
    return success_list([serialize_property(p) for p in page], total, limit, offset)
