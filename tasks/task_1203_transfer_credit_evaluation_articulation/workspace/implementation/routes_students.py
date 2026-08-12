"""Student routes: registration, profile patch (OCC), degree progress."""
from flask import Blueprint, request

import db
from db import touch
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_NOT_RESOURCE_OWNER, ERR_STALE_VERSION)
from middleware import ANY, current_user, require_roles
from response import get_body, success_object
from services import compute_degree_progress, ser_student
from util import opt_str, req_int, req_str

bp = Blueprint("students", __name__)


def _get_student(sid):
    rec = db.students.get(sid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"TransferStudent not found: {sid}")
    return rec


def _check_student_read_ownership(student):
    uid, role = current_user()
    if role == "Student" and student["id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Students may only access their own records")


@bp.route("/api/students", methods=["POST"])
@require_roles("RegistrarAdmin")
def create_student():
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    declared_major = req_str(body, "declared_major")
    catalog_year = req_int(body, "catalog_year")
    for s in db.students.values():
        if s["email"] == email:
            raise ApiError(ERR_INVALID_REQUEST, 400, "email must be unique")
    from decimal import Decimal
    rec = db.create_rec(db.students, {
        "full_name": full_name, "email": email,
        "declared_major": declared_major, "catalog_year": catalog_year,
        "total_posted_transfer_credits": Decimal("0"),
        "total_posted_pla_credits": Decimal("0"),
    })
    return success_object(ser_student(rec), 201)


@bp.route("/api/students/<sid>", methods=["GET"])
@require_roles(*ANY)
def get_student(sid):
    rec = _get_student(sid)
    _check_student_read_ownership(rec)
    return success_object(ser_student(rec))


@bp.route("/api/students/<sid>", methods=["PATCH"])
@require_roles("RegistrarAdmin")
def patch_student(sid):
    body = get_body()
    expected = req_int(body, "expected_student_version")
    full_name = body.get("full_name")
    declared_major = body.get("declared_major")
    catalog_year = body.get("catalog_year")
    if full_name is not None and (not isinstance(full_name, str) or full_name.strip() == ""):
        raise ApiError(ERR_INVALID_REQUEST, 400, "full_name must be a non-empty string")
    if declared_major is not None and (not isinstance(declared_major, str) or declared_major.strip() == ""):
        raise ApiError(ERR_INVALID_REQUEST, 400, "declared_major must be a non-empty string")
    if catalog_year is not None:
        if isinstance(catalog_year, bool) or not isinstance(catalog_year, int):
            if isinstance(catalog_year, float) and catalog_year.is_integer():
                catalog_year = int(catalog_year)
            else:
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "catalog_year must be an integer")
    rec = _get_student(sid)
    # OCC (priority 5)
    if expected != rec["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_student_version does not match the student version")
    if full_name is not None:
        rec["full_name"] = full_name
    if declared_major is not None:
        rec["declared_major"] = declared_major
    if catalog_year is not None:
        rec["catalog_year"] = catalog_year
    touch(rec)
    return success_object(ser_student(rec))


@bp.route("/api/students/<sid>/degree-progress", methods=["GET"])
@require_roles(*ANY)
def degree_progress(sid):
    rec = _get_student(sid)
    _check_student_read_ownership(rec)
    variant = request.args.get("variant")
    if variant is None:
        variant = "CERTIFIED"
    if variant not in ("CERTIFIED", "PROVISIONAL"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "variant must be CERTIFIED or PROVISIONAL")
    return success_object(compute_degree_progress(rec, variant))
