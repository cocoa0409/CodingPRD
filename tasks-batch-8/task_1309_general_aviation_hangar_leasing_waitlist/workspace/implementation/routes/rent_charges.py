"""RentCharge read endpoints."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_roles
from envelope import success_list, success_obj
from errors import ApiError, ERR_NOT_FOUND
from routes.leases import get_lease_or_404
from validators import paginate, pagination

bp = Blueprint("rent_charges", __name__)


@bp.get("/leases/<lid>/rent-charges")
def list_lease_rent_charges(lid):
    require_roles(*ALL_ROLES)
    lease = get_lease_or_404(lid)
    items = [c for c in db.rent_charges.values() if c["lease_id"] == lease["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total)


@bp.get("/rent-charges/<cid>")
def get_rent_charge(cid):
    require_roles(*ALL_ROLES)
    charge = db.rent_charges.get(cid)
    if charge is None:
        raise ApiError(ERR_NOT_FOUND, "Rent charge not found", 404)
    return success_obj(db.public(charge), 200)
