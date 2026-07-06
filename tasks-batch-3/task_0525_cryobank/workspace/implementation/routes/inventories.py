from flask import Blueprint, request

from db import db
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import paginate
from routes.common import get_inventory

bp = Blueprint("inventories", __name__)

READ_ROLES = {"CatalogManager", "LabTech", "ComplianceOfficer", "Recipient"}


@bp.get("/donor-inventories/<i>")
def get_one(i):
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    return ok_object(get_inventory(i))


@bp.get("/donor-inventories")
def list_inv():
    _uid, role = get_auth()
    require_role(role, READ_ROLES)
    items = list(db.donor_inventories.values())
    specimen_f = request.args.get("specimen_id")
    donor_f = request.args.get("donor_id")
    listed_f = request.args.get("is_listed")
    if specimen_f is not None:
        items = [x for x in items if x["specimen_id"] == specimen_f]
    if donor_f is not None:
        items = [x for x in items if x["donor_id"] == donor_f]
    if listed_f is not None:
        want = listed_f.lower() in ("true", "1")
        items = [x for x in items if x["is_listed"] == want]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)
