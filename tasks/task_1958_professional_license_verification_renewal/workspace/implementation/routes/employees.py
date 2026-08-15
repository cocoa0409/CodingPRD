"""Employee roster endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from serializers import employee_view, license_view
from services import refresh_employee_derived
from util import as_str, body, pagination_args, required

bp = Blueprint("employees", __name__, url_prefix="/licensing/employees")


@bp.post("")
def create_employee():
    auth(["HRPartner"])
    data = body()
    full_name = as_str(required(data, "full_name"), "full_name")
    work_email = as_str(required(data, "work_email"), "work_email")
    role_code = as_str(required(data, "role_code"), "role_code")

    lowered = work_email.lower()
    for emp in DB["employees"].values():
        if emp["work_email"].lower() == lowered:
            raise ApiError(
                "ERR_DUPLICATE_EMAIL", 409,
                "An employee with this work email already exists",
            )

    ts = now_iso()
    emp = {
        "id": new_id(),
        "full_name": full_name,
        "work_email": work_email,
        "role_code": role_code,
        "work_authorization": "AUTHORIZED",
        "restriction_reason": None,
        "screening_posture": "CLEAR",
        "reimbursement_committed_cents": 0,
        "reimbursement_paid_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["employees"][emp["id"]] = emp
    # Onboarding computes compliance posture immediately (MISSING_LICENSE may
    # engage against mandatory matrix rows for the role).
    refresh_employee_derived(emp)
    return ok(employee_view(emp), status=201)


@bp.get("")
def list_employees():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    role_code = request.args.get("role_code")
    work_authorization = request.args.get("work_authorization")
    screening_posture = request.args.get("screening_posture")
    items = sorted(DB["employees"].values(), key=lambda x: x["created_at"])
    views = [employee_view(x) for x in items]  # refreshes derived filters
    if role_code is not None:
        views = [v for v in views if v["role_code"] == role_code]
    if work_authorization is not None:
        views = [v for v in views if v["work_authorization"] == work_authorization]
    if screening_posture is not None:
        views = [v for v in views if v["screening_posture"] == screening_posture]
    total = len(views)
    page = views[offset:offset + limit]
    return ok_list(page, total, limit, offset)


@bp.get("/<eid>")
def get_employee(eid):
    auth(ALL_ROLES)
    emp = DB["employees"].get(eid)
    if emp is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Employee not found")
    return ok(employee_view(emp))


@bp.patch("/<eid>")
def update_employee(eid):
    auth(["HRPartner"])
    emp = DB["employees"].get(eid)
    if emp is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Employee not found")
    data = body()
    role_changed = False
    if "full_name" in data and data["full_name"] is not None:
        emp["full_name"] = as_str(data["full_name"], "full_name")
    if "work_email" in data and data["work_email"] is not None:
        new_email = as_str(data["work_email"], "work_email")
        lowered = new_email.lower()
        for other in DB["employees"].values():
            if other["id"] != eid and other["work_email"].lower() == lowered:
                raise ApiError(
                    "ERR_DUPLICATE_EMAIL", 409,
                    "An employee with this work email already exists",
                )
        emp["work_email"] = new_email
    if "role_code" in data and data["role_code"] is not None:
        new_role = as_str(data["role_code"], "role_code")
        if new_role != emp["role_code"]:
            emp["role_code"] = new_role
            role_changed = True
    refresh_employee_derived(emp)
    # The PATCH itself is a profile mutation; the version advances once.
    emp["updated_at"] = now_iso()
    emp["version"] += 1
    _ = role_changed  # role_code change already re-derived authorization above
    return ok(employee_view(emp))


@bp.get("/<eid>/licenses")
def list_employee_licenses(eid):
    auth(ALL_ROLES)
    if eid not in DB["employees"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Employee not found")
    limit, offset = pagination_args()
    items = sorted(
        (l for l in DB["licenses"].values() if l["employee_id"] == eid),
        key=lambda x: x["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([license_view(x) for x in page], total, limit, offset)
