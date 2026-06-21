"""Owner endpoints (PRD §3.2)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_roles
from services import serialize
from services.common import stamp_create, get_body, require_fields
from services.query import paginate_params, sort_by_created, apply_page, owner_guard
from routes.facilities import get_facility_or_404

bp = Blueprint("owners", __name__)

OWNER_STATUSES = {"ACTIVE", "ARCHIVED"}


def get_owner_or_404(oid):
    o = db.owners.get(oid)
    if o is None:
        raise errors.err_not_found()
    return o


@bp.route("/facilities/<fid>/owners", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff")
def create_owner(fid):
    facility = get_facility_or_404(fid)
    body = get_body()
    require_fields(body, ["full_name", "email", "phone"])
    full_name = body["full_name"]
    email = body["email"]
    phone = body["phone"]
    for val, name in ((full_name, "full_name"), (email, "email"), (phone, "phone")):
        if not isinstance(val, str) or val == "":
            raise errors.err_invalid_request(f"{name} must be a non-empty string.")

    owner = {
        "facility_id": fid,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "status": "ACTIVE",
        "wallet_credit_cents": 0,
    }
    stamp_create(owner)
    db.owners[owner["id"]] = owner
    return response.success(serialize.owner(owner), status=201)


@bp.route("/owners/<oid>", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def get_owner(oid):
    o = get_owner_or_404(oid)
    owner_guard(oid)
    return response.success(serialize.owner(o), status=200)


@bp.route("/facilities/<fid>/owners", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff")
def list_owners(fid):
    get_facility_or_404(fid)
    limit, offset = paginate_params()
    email_filter = request.args.get("email")
    status_filter = request.args.get("status")

    items = [o for o in db.owners.values() if o["facility_id"] == fid]
    if email_filter is not None:
        items = [o for o in items if o["email"] == email_filter]
    if status_filter is not None:
        items = [o for o in items if o["status"] == status_filter]
    items = sort_by_created(items)
    page, total = apply_page(items, limit, offset)
    return response.list_success([serialize.owner(o) for o in page], limit, offset, total)
