"""Coupon CRUD + disable transition (PRD §3.5)."""
from flask import Blueprint, request

import response
from db import db, new_id
from errors import err
from middleware import authenticate, require_roles
from services.common import (stamp_create, touch, require_field, as_str,
                             as_int, paginate, parse_dt)
from services.serialize import view, view_list

bp = Blueprint("coupons", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _overlaps(a_from, a_until, b_from, b_until):
    """Half-open overlap: (a_from < b_until) and (b_from < a_until)."""
    return a_from < b_until and b_from < a_until


@bp.route("/coupons", methods=["POST"])
def create_coupon():
    principal = authenticate()
    require_roles(principal, "Instructor")
    body = _body()

    instructor_id = as_str(require_field(body, "instructor_id"), "instructor_id")
    course_id = as_str(require_field(body, "course_id"), "course_id")
    code = as_str(require_field(body, "code"), "code")
    discount_type = as_str(require_field(body, "discount_type"), "discount_type")
    discount_value = as_int(require_field(body, "discount_value"), "discount_value")
    max_redemptions = as_int(require_field(body, "max_redemptions"), "max_redemptions")
    valid_from_raw = require_field(body, "valid_from")
    valid_until_raw = require_field(body, "valid_until")

    if discount_type not in ("PERCENT", "FLAT"):
        raise err("ERR_INVALID_REQUEST", "discount_type must be PERCENT or FLAT.")
    if discount_type == "PERCENT":
        if not (1 <= discount_value <= 100):
            raise err("ERR_INVALID_REQUEST", "PERCENT discount_value must be 1-100.")
    else:  # FLAT
        if discount_value < 1:
            raise err("ERR_INVALID_REQUEST", "FLAT discount_value must be >= 1 cent.")
    if max_redemptions < 1:
        raise err("ERR_INVALID_REQUEST", "max_redemptions must be >= 1.")

    valid_from = parse_dt(valid_from_raw)
    valid_until = parse_dt(valid_until_raw)

    # ownership + existence: issuing instructor must own the coupon's course
    if principal.user_id != instructor_id:
        raise err("ERR_FORBIDDEN")
    if instructor_id not in db.instructors:
        raise err("ERR_NOT_FOUND")
    course = db.courses.get(course_id)
    if course is None:
        raise err("ERR_NOT_FOUND")
    if course["instructor_id"] != instructor_id:
        raise err("ERR_FORBIDDEN")

    # code unique per instructor (case-insensitive)
    for c in db.coupons.values():
        if c["instructor_id"] == instructor_id and c["code"].lower() == code.lower():
            raise err("ERR_INVALID_REQUEST", "Coupon code must be unique per instructor.")

    # window must not overlap any existing non-DISABLED coupon for same
    # (instructor, course); half-open semantics, touching allowed.
    for c in db.coupons.values():
        if (c["instructor_id"] == instructor_id and c["course_id"] == course_id
                and c["status"] != "DISABLED"):
            ef = parse_dt(c["valid_from"])
            eu = parse_dt(c["valid_until"])
            if _overlaps(valid_from, valid_until, ef, eu):
                raise err("ERR_COUPON_WINDOW_OVERLAP")

    rec = {
        "id": new_id(),
        "instructor_id": instructor_id,
        "course_id": course_id,
        "code": code,
        "discount_type": discount_type,
        "discount_value": discount_value,
        "max_redemptions": max_redemptions,
        "redeemed_count": 0,
        "valid_from": valid_from_raw,
        "valid_until": valid_until_raw,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.coupons[rec["id"]] = rec
    return response.success(view(rec), status=201)


@bp.route("/coupons/<coupon_id>", methods=["GET"])
def get_coupon(coupon_id):
    principal = authenticate()
    require_roles(principal, "Instructor", "PlatformAdmin")
    coupon = db.coupons.get(coupon_id)
    if coupon is None:
        raise err("ERR_NOT_FOUND")
    if principal.role == "Instructor" and principal.user_id != coupon["instructor_id"]:
        raise err("ERR_FORBIDDEN")
    return response.success(view(coupon), status=200)


@bp.route("/coupons", methods=["GET"])
def list_coupons():
    principal = authenticate()
    require_roles(principal, "Instructor", "PlatformAdmin")
    args = request.args
    items = list(db.coupons.values())
    instructor_id = args.get("instructor_id")
    course_id = args.get("course_id")
    status = args.get("status")
    if instructor_id is not None:
        items = [c for c in items if c["instructor_id"] == instructor_id]
    if course_id is not None:
        items = [c for c in items if c["course_id"] == course_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    # An instructor listing coupons sees only its own.
    if principal.role == "Instructor":
        items = [c for c in items if c["instructor_id"] == principal.user_id]
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)


@bp.route("/coupons/<coupon_id>/disable", methods=["POST"])
def disable_coupon(coupon_id):
    principal = authenticate()
    require_roles(principal, "Instructor")
    coupon = db.coupons.get(coupon_id)
    if coupon is None:
        raise err("ERR_NOT_FOUND")
    if principal.user_id != coupon["instructor_id"]:
        raise err("ERR_FORBIDDEN")
    if coupon["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE")
    coupon["status"] = "DISABLED"
    touch(coupon)
    return response.success(view(coupon), status=200)
