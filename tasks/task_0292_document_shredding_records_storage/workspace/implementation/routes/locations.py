"""ServiceLocation endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db, stamp_create
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    body, serialize, paginate, sort_by_created,
    require_present, as_str, get_account_or_404, get_location_or_404,
)

bp = Blueprint("locations", __name__)

_ROLES = {"AccountManager", "ComplianceOfficer"}


@bp.post("/locations")
def create_location():
    _, role = get_auth()
    require_role(role, _ROLES)
    data = body()
    require_present(data, "account_id", "label", "address")
    account_id = as_str(data["account_id"], "account_id")
    # Existence: account_id must resolve.
    get_account_or_404(account_id)
    label = as_str(data["label"], "label")
    address = as_str(data["address"], "address")
    secure_area = data.get("secure_area", False)
    if not isinstance(secure_area, bool):
        raise err("ERR_INVALID_FIELD_VALUE", "secure_area must be boolean")

    loc = {
        "account_id": account_id,
        "label": label,
        "address": address,
        "secure_area": secure_area,
    }
    stamp_create(loc)
    db.locations[loc["id"]] = loc
    return object_response(serialize(loc), 201)


@bp.get("/locations/<location_id>")
def get_location(location_id):
    _, role = get_auth()
    require_role(role, _ROLES)
    loc = get_location_or_404(location_id)
    return object_response(serialize(loc), 200)


@bp.get("/locations")
def list_locations():
    _, role = get_auth()
    require_role(role, _ROLES)
    items = list(db.locations.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        items = [l for l in items if l["account_id"] == account_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(l) for l in page], limit, offset, total, 200)
