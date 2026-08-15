from flask import Blueprint, request

from db import store, base_fields
from errors import err, ERR_STUDENT_NOT_FOUND, ERR_DUPLICATE_EXTERNAL_REF
from middleware import auth_context, require_roles, forbid
from response import success, json_body, req_str, req_enum, list_response
from serialize import ser_student, ser_account, ser_tax_form
from routes.rates import RESIDENCIES, LEVELS

bp = Blueprint("students", __name__)


@bp.post("/bursar/students")
def create_student():
    _, role = auth_context()
    require_roles(role, "RegistrarStaff")
    body = json_body()
    full_name = req_str(body, "full_name")
    external_ref = req_str(body, "external_ref")
    residency = req_enum(body, "residency_status", RESIDENCIES)
    level = req_enum(body, "level", LEVELS)
    for s in store.students.values():
        if s["external_ref"] == external_ref:
            raise err(ERR_DUPLICATE_EXTERNAL_REF, "external_ref already exists")
    s = base_fields()
    s.update({
        "full_name": full_name, "external_ref": external_ref,
        "residency_status": residency, "level": level,
    })
    store.students[s["id"]] = s
    return success(ser_student(s), status=201)


@bp.get("/bursar/students/<sid>")
def get_student(sid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    # Student role restricted to own record.
    if role == "Student" and sid != uid:
        forbid()
    s = store.students.get(sid)
    if s is None:
        raise err(ERR_STUDENT_NOT_FOUND, "Student not found")
    return success(ser_student(s))


@bp.get("/bursar/students")
def list_students():
    _, role = auth_context()
    require_roles(role, "RegistrarStaff", "BursarStaff", "BursarManager")
    rows = list(store.students.values())
    residency = request.args.get("residency_status")
    if residency is not None:
        rows = [s for s in rows if s["residency_status"] == residency]
    rows.sort(key=lambda s: s["_seq"])
    return list_response(rows, ser_student)


@bp.get("/bursar/students/<sid>/accounts")
def student_accounts(sid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    if role == "Student" and sid != uid:
        forbid()
    if sid not in store.students:
        raise err(ERR_STUDENT_NOT_FOUND, "Student not found")
    rows = [a for a in store.accounts.values() if a["student_id"] == sid]
    rows.sort(key=lambda a: a["_seq"])
    return list_response(rows, ser_account)


@bp.get("/bursar/students/<sid>/tax-forms")
def student_tax_forms(sid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    if role == "Student" and sid != uid:
        forbid()
    if sid not in store.students:
        raise err(ERR_STUDENT_NOT_FOUND, "Student not found")
    rows = [f for f in store.tax_forms.values() if f["student_id"] == sid]
    rows.sort(key=lambda f: f["_seq"])
    return list_response(rows, ser_tax_form)
