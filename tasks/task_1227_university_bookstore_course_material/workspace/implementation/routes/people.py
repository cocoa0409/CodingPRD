"""Faculty and Student records (PRD §3.3), plus FinanceAdmin aid adjustments."""

from flask import Blueprint

from db import store, new_entity, touch, pub
from errors import ApiError, ERR_VALIDATION
from middleware import require_roles, body, get_str, get_int, get_or_404
from response import success

bp = Blueprint("people", __name__)


@bp.post("/bookstore/faculty")
def create_faculty():
    require_roles("PlatformAdmin")
    data = body()
    full_name = get_str(data, "full_name")
    email = get_str(data, "email")
    if any(f["email"] == email for f in store.faculty.values()):
        raise ApiError(ERR_VALIDATION, 400, "email must be unique")
    fac = new_entity()
    fac.update({"full_name": full_name, "email": email})
    store.faculty[fac["id"]] = fac
    return success(pub(fac), status=201)


@bp.get("/bookstore/faculty/<fid>")
def get_faculty(fid):
    require_roles("PlatformAdmin", "BookstoreManager", "Faculty")
    return success(pub(get_or_404(store.faculty, fid, "faculty")))


@bp.post("/bookstore/students")
def create_student():
    require_roles("PlatformAdmin")
    data = body()
    full_name = get_str(data, "full_name")
    email = get_str(data, "email")
    awarded = get_int(data, "awarded_aid_cents", required=False, default=0,
                      min_val=0)
    if any(s["email"] == email for s in store.students.values()):
        raise ApiError(ERR_VALIDATION, 400, "email must be unique")
    stu = new_entity()
    stu.update({
        "full_name": full_name,
        "email": email,
        "awarded_aid_cents": awarded,
        "aid_balance_cents": awarded,
    })
    store.students[stu["id"]] = stu
    return success(pub(stu), status=201)


@bp.get("/bookstore/students/<sid>")
def get_student(sid):
    require_roles("PlatformAdmin", "BookstoreManager", "FinanceAdmin", "Student")
    return success(pub(get_or_404(store.students, sid, "student")))


@bp.post("/bookstore/students/<sid>/aid-adjustments")
def adjust_aid(sid):
    require_roles("FinanceAdmin")
    stu = get_or_404(store.students, sid, "student")
    data = body()
    delta = get_int(data, "delta_cents")  # signed; no min
    get_str(data, "reason")
    stu["awarded_aid_cents"] += delta
    stu["aid_balance_cents"] += delta
    touch(stu)
    return success(pub(stu), status=201)
