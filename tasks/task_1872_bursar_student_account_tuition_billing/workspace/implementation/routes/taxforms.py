from flask import Blueprint, request

from db import store, base_fields, touch
from errors import (err, ERR_STUDENT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
                    ERR_DUPLICATE_TAX_FORM, ERR_TAX_FORM_STATE_INVALID)
from middleware import auth_context, require_roles, forbid
from response import success, json_body, req_str, req_int, list_response
from serialize import ser_tax_form
from services.domain import compute_tax_boxes

bp = Blueprint("taxforms", __name__)


def _load_form(fid, uid, role):
    f = store.tax_forms.get(fid)
    if f is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Tax form not found")
    if role == "Student" and f["student_id"] != uid:
        forbid()
    return f


@bp.post("/bursar/tax-forms")
def create_tax_form():
    _, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    body = json_body()
    student_id = req_str(body, "student_id")
    tax_year = req_int(body, "tax_year")
    if student_id not in store.students:
        raise err(ERR_STUDENT_NOT_FOUND, "Student not found")
    # One live form per student per year.
    for f in store.tax_forms.values():
        if (f["student_id"] == student_id and f["tax_year"] == tax_year
                and f["status"] in ("DRAFT", "FINALIZED")):
            raise err(ERR_DUPLICATE_TAX_FORM,
                      "A DRAFT or FINALIZED form already exists for this student and year")
    box1, box4, box5 = compute_tax_boxes(student_id, tax_year)
    f = base_fields()
    f.update({
        "student_id": student_id, "tax_year": tax_year,
        "box1_cents": box1, "box4_cents": box4, "box5_cents": box5,
        "status": "DRAFT", "corrected_from_id": None,
    })
    store.tax_forms[f["id"]] = f
    return success(ser_tax_form(f), status=201)


@bp.get("/bursar/tax-forms/<fid>")
def get_tax_form(fid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    f = _load_form(fid, uid, role)
    return success(ser_tax_form(f))


@bp.get("/bursar/tax-forms")
def list_tax_forms():
    _, role = auth_context()
    require_roles(role, "RegistrarStaff", "BursarStaff", "BursarManager")
    rows = list(store.tax_forms.values())
    for key in ("student_id", "corrected_from_id", "status"):
        v = request.args.get(key)
        if v is not None:
            rows = [f for f in rows if f[key] == v]
    tax_year = request.args.get("tax_year")
    if tax_year is not None:
        try:
            ty = int(tax_year)
            rows = [f for f in rows if f["tax_year"] == ty]
        except ValueError:
            rows = []
    rows.sort(key=lambda f: f["_seq"])
    return list_response(rows, ser_tax_form)


@bp.post("/bursar/tax-forms/<fid>/finalize")
def finalize_tax_form(fid):
    _, role = auth_context()
    require_roles(role, "BursarManager")
    f = store.tax_forms.get(fid)
    if f is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Tax form not found")
    if f["status"] != "DRAFT":
        raise err(ERR_TAX_FORM_STATE_INVALID, "Finalize requires a DRAFT form")
    f["status"] = "FINALIZED"
    touch(f)
    return success(ser_tax_form(f))


@bp.post("/bursar/tax-forms/<fid>/correct")
def correct_tax_form(fid):
    _, role = auth_context()
    require_roles(role, "BursarManager")
    f = store.tax_forms.get(fid)
    if f is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Tax form not found")
    if f["status"] != "FINALIZED":
        raise err(ERR_TAX_FORM_STATE_INVALID, "Correction requires a FINALIZED form")
    f["status"] = "SUPERSEDED"
    touch(f)
    box1, box4, box5 = compute_tax_boxes(f["student_id"], f["tax_year"])
    new = base_fields()
    new.update({
        "student_id": f["student_id"], "tax_year": f["tax_year"],
        "box1_cents": box1, "box4_cents": box4, "box5_cents": box5,
        "status": "DRAFT", "corrected_from_id": f["id"],
    })
    store.tax_forms[new["id"]] = new
    return success(ser_tax_form(new))
