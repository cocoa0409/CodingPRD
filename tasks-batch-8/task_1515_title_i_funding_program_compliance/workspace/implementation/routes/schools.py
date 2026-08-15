"""School and PrivateSchool endpoints."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from services import serializers

bp = Blueprint("schools", __name__)

CA = {"ComplianceAnalyst"}
ALL_ROLES = middleware.ROLES


@bp.post("/schools")
def create_school():
    _uid, role = middleware.current_user()
    middleware.require_role(role, CA)
    data = V.json_body()
    V.check_unknown(data, {"name", "nces_id", "grade_span_low", "grade_span_high", "is_active"})
    name = V.req_str(data, "name")
    nces_id = V.req_str(data, "nces_id")
    low = V.req_int(data, "grade_span_low")
    high = V.req_int(data, "grade_span_high")
    is_active = V.opt_bool(data, "is_active", True)
    if low < 0 or low > 12 or high < 0 or high > 12:
        errors.fail(errors.ERR_INVALID_REQUEST, "Grade spans must be within 0..12.")
    if low > high:
        errors.fail(
            errors.ERR_INVALID_DATE_RANGE,
            "grade_span_low must not exceed grade_span_high.",
        )
    # Tier 4.5: duplicate nces_id surfaces as ERR_INVALID_REQUEST.
    for s in db.schools.values():
        if s["nces_id"] == nces_id:
            errors.fail(errors.ERR_INVALID_REQUEST, "nces_id %s is already registered." % nces_id)
    school = db.init_common({
        "name": name,
        "nces_id": nces_id,
        "grade_span_low": low,
        "grade_span_high": high,
        "is_active": is_active,
    })
    db.schools[school["id"]] = school
    return response.success_object(serializers.school_view(school), 201)


@bp.get("/schools")
def list_schools():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    is_active = V.query_bool("is_active")
    page, limit, offset, total = V.sorted_page(
        list(db.schools.values()), [("is_active", is_active)]
    )
    return response.success_list(
        [serializers.school_view(s) for s in page], limit, offset, total
    )


@bp.patch("/schools/<school_id>")
def update_school(school_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, CA)
    school = db.schools.get(school_id)
    if school is None:
        errors.fail(errors.ERR_NOT_FOUND, "School %s does not exist." % school_id)
    data = V.json_body()
    V.check_unknown(data, {"is_active"})
    is_active = V.opt_bool(data, "is_active", None)
    if is_active is None:
        return response.success_object(serializers.school_view(school))
    if school["is_active"] and not is_active:
        # Tier 9: a school present in any CERTIFIED snapshot cannot be deactivated.
        for snap in db.snapshots.values():
            if snap["status"] != "CERTIFIED":
                continue
            if any(e["school_id"] == school_id for e in snap["entries"]):
                errors.fail(
                    errors.ERR_SCHOOL_LOCKED_BY_SNAPSHOT,
                    "Cannot deactivate a school present in a CERTIFIED snapshot.",
                )
    if school["is_active"] != is_active:
        school["is_active"] = is_active
        db.touch(school)
    return response.success_object(serializers.school_view(school))


@bp.post("/private-schools")
def create_private_school():
    _uid, role = middleware.current_user()
    middleware.require_role(role, CA)
    data = V.json_body()
    V.check_unknown(data, {"name", "low_income_resident_count", "contact_email", "nonprofit_verified"})
    name = V.req_str(data, "name")
    count = V.req_int(data, "low_income_resident_count")
    email = V.req_str(data, "contact_email")
    verified = V.opt_bool(data, "nonprofit_verified", False)
    if count < 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "low_income_resident_count must be >= 0.")
    ps = db.init_common({
        "name": name,
        "nonprofit_verified": verified,
        "low_income_resident_count": count,
        "contact_email": email,
    })
    db.private_schools[ps["id"]] = ps
    return response.success_object(serializers.private_school_view(ps), 201)


@bp.get("/private-schools")
def list_private_schools():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    verified = V.query_bool("nonprofit_verified")
    page, limit, offset, total = V.sorted_page(
        list(db.private_schools.values()), [("nonprofit_verified", verified)]
    )
    return response.success_list(
        [serializers.private_school_view(p) for p in page], limit, offset, total
    )
