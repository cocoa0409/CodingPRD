"""Role-requirement matrix endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from serializers import role_requirement_view
from services import refresh_employee_derived
from util import as_bool, as_str, body, pagination_args, required

bp = Blueprint("role_requirements", __name__, url_prefix="/licensing/role-requirements")


def _recompute_role(role_code):
    """Requirement maintenance immediately re-derives every matching employee."""
    for emp in DB["employees"].values():
        if emp["role_code"] == role_code:
            refresh_employee_derived(emp, bump=True)


@bp.post("")
def create_role_requirement():
    auth(["ComplianceAdmin"])
    data = body()
    role_code = as_str(required(data, "role_code"), "role_code")
    license_type_id = as_str(required(data, "license_type_id"), "license_type_id")
    state_code = as_str(required(data, "state_code"), "state_code")
    is_required = as_bool(required(data, "is_required"), "is_required")

    # Body-FK existence before further domain/uniqueness checks (PRD 2.6/2.8).
    if license_type_id not in DB["license_types"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced license type does not exist")

    for rr in DB["role_requirements"].values():
        if (
            rr["role_code"] == role_code
            and rr["license_type_id"] == license_type_id
            and rr["state_code"] == state_code
        ):
            raise ApiError(
                "ERR_DUPLICATE_ROLE_REQUIREMENT", 409,
                "A role requirement already exists for this (role_code, license_type_id, state_code)",
            )

    ts = now_iso()
    rr = {
        "id": new_id(),
        "role_code": role_code,
        "license_type_id": license_type_id,
        "state_code": state_code,
        "is_required": is_required,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["role_requirements"][rr["id"]] = rr
    _recompute_role(role_code)
    return ok(role_requirement_view(rr), status=201)


@bp.get("")
def list_role_requirements():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    role_code = request.args.get("role_code")
    state_code = request.args.get("state_code")
    license_type_id = request.args.get("license_type_id")
    items = sorted(DB["role_requirements"].values(), key=lambda x: x["created_at"])
    if role_code is not None:
        items = [x for x in items if x["role_code"] == role_code]
    if state_code is not None:
        items = [x for x in items if x["state_code"] == state_code]
    if license_type_id is not None:
        items = [x for x in items if x["license_type_id"] == license_type_id]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([role_requirement_view(x) for x in page], total, limit, offset)


@bp.get("/<rid>")
def get_role_requirement(rid):
    auth(ALL_ROLES)
    rr = DB["role_requirements"].get(rid)
    if rr is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Role requirement not found")
    return ok(role_requirement_view(rr))


@bp.delete("/<rid>")
def delete_role_requirement(rid):
    auth(["ComplianceAdmin"])
    rr = DB["role_requirements"].get(rid)
    if rr is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Role requirement not found")
    role_code = rr["role_code"]
    del DB["role_requirements"][rid]
    _recompute_role(role_code)
    return "", 204
