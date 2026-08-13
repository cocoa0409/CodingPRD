"""StaffMember endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES
from response import ok, ok_list
from services import stamp_new, public
from util import body, required, as_str, as_bool, pagination_args

bp = Blueprint("staff", __name__)


def _get_staff_or_404(staff_id):
    staff = DB["staff_members"].get(staff_id)
    if staff is None:
        raise ApiError("ERR_STAFF_MEMBER_NOT_FOUND", 404, "Staff member not found")
    return staff


@bp.post("/vault-cash/staff-members")
def create_staff():
    auth(["CashOperationsAdmin"])
    data = body()
    full_name = as_str(required(data, "full_name"), "full_name")
    home_site_id = as_str(required(data, "home_site_id"), "home_site_id")
    if home_site_id not in DB["vault_sites"]:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    active = data.get("active", True)
    if active is not None:
        active = as_bool(active, "active")
    else:
        active = True

    staff = stamp_new({
        "id": new_id(),
        "full_name": full_name,
        "home_site_id": home_site_id,
        "active": active,
    })
    DB["staff_members"][staff["id"]] = staff
    return ok(public(staff), status=201)


@bp.get("/vault-cash/staff-members")
def list_staff():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    home_site_id = request.args.get("home_site_id")
    rows = list(DB["staff_members"].values())
    if home_site_id is not None:
        rows = [s for s in rows if s["home_site_id"] == home_site_id]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        rows = [s for s in rows if s["home_site_id"] == principal.home_site_id]
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(rows)
    return ok_list([public(s) for s in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/staff-members/<staffId>")
def get_staff(staffId):
    principal = auth(ALL_ROLES)
    staff = _get_staff_or_404(staffId)
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        if staff["home_site_id"] != principal.home_site_id:
            raise ApiError(
                "ERR_SITE_SCOPE_VIOLATION", 403, "Staff member is at another site"
            )
    return ok(public(staff))
