"""Property routes."""

from flask import Blueprint, request

import db
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from routes.helpers import lookup, paginate
from services import domain
import validation as V

bp = Blueprint("properties", __name__)


@bp.post("/properties")
def create_property():
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    body = V.get_body()
    landlord_id = V.require_str(body, "landlord_id")
    address = V.require_str(body, "address")
    list_price_cents = V.require_int(body, "list_price_cents", gt=0)

    # Existence (priority 3): the named landlord must exist.
    lookup(db.landlords, landlord_id)
    # Ownership (priority 2 ladder, resolved after existence): the acting
    # landlord must own the property via landlord_id == X-User-ID.
    if landlord_id != user_id:
        raise err("ERR_FORBIDDEN", "Landlord may only list properties they own")

    rec = {
        "id": db.new_id(),
        "landlord_id": landlord_id,
        "address": address,
        "list_price_cents": list_price_cents,
        "status": "AVAILABLE",
    }
    domain._stamp_new(rec)
    db.properties[rec["id"]] = rec
    return object_response(domain.serialize_property(rec), 201)


@bp.get("/properties/<rid>")
def get_property(rid):
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    rec = lookup(db.properties, rid)
    return object_response(domain.serialize_property(rec), 200)


@bp.get("/properties")
def list_properties():
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    items = list(db.properties.values())
    landlord_id = request.args.get("landlord_id")
    status = request.args.get("status")
    if landlord_id is not None:
        items = [p for p in items if p["landlord_id"] == landlord_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([domain.serialize_property(p) for p in page],
                          limit, offset, total)
