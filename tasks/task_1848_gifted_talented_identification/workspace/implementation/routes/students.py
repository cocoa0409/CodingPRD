"""Student + SpedPlan endpoints."""

from flask import Blueprint

import db
from errors import ApiError, ERR_DUPLICATE_SPED_PLAN, ERR_INVALID_REQUEST
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_int,
    require_enum,
    require_bool,
    optional_string,
    get_or_404,
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_created,
    parse_date,
    serialize_student,
    serialize_sped_plan,
)

bp = Blueprint("students", __name__)

DEMOGRAPHIC_GROUPS = {
    "AMERICAN_INDIAN",
    "ASIAN",
    "BLACK",
    "HISPANIC",
    "WHITE",
    "MULTIRACIAL",
    "PACIFIC_ISLANDER",
}


def _make_student(student_number, legal_name, grade_level, school_site_id,
                  demographic_group, guardian_id, is_ell):
    ts = now_iso()
    student = {
        "id": new_id(),
        "student_number": student_number,
        "legal_name": legal_name,
        "grade_level": grade_level,
        "school_site_id": school_site_id,
        "demographic_group": demographic_group,
        "is_ell": is_ell,
        "primary_guardian_user_id": guardian_id,
        "gifted_status": "NOT_IDENTIFIED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.students[student["id"]] = student
    return student


@bp.route("/gifted/students", methods=["POST"])
def create_student():
    require_roles("GiftedCoordinator")
    body = get_json_body()
    require_fields(
        body,
        ["student_number", "legal_name", "grade_level", "school_site_id",
         "demographic_group", "primary_guardian_user_id"],
    )
    student_number = require_string(body, "student_number")
    legal_name = require_string(body, "legal_name")
    grade_level = require_int(body, "grade_level", lo=0, hi=12)
    school_site_id = require_string(body, "school_site_id")
    demographic_group = require_enum(body, "demographic_group", DEMOGRAPHIC_GROUPS)
    guardian_id = require_string(body, "primary_guardian_user_id")
    is_ell = require_bool(body, "is_ell", default=False)

    # school_site_id FK: existence is priority 4 (path ids) — for body FK the
    # PRD lists site-on-placement as ERR_NOT_FOUND priority 4; treat the body
    # FK the same way (not-found beats nothing else here but shape).
    get_or_404(db.school_sites, school_site_id, "school site")

    student = _make_student(
        student_number, legal_name, grade_level, school_site_id,
        demographic_group, guardian_id, is_ell,
    )
    return success_object(serialize_student(student), 201)


@bp.route("/gifted/students/bulk-enroll", methods=["POST"])
def bulk_enroll():
    require_roles("GiftedCoordinator")
    body = get_json_body()
    require_fields(body, ["school_site_id", "grade_level", "demographic_group", "count"])
    school_site_id = require_string(body, "school_site_id")
    grade_level = require_int(body, "grade_level", lo=0, hi=12)
    demographic_group = require_enum(body, "demographic_group", DEMOGRAPHIC_GROUPS)
    count = require_int(body, "count", lo=1)

    get_or_404(db.school_sites, school_site_id, "school site")

    ids = []
    for _ in range(count):
        student = _make_student(
            student_number="BULK-" + new_id(),
            legal_name="Bulk Enrolled Student",
            grade_level=grade_level,
            school_site_id=school_site_id,
            demographic_group=demographic_group,
            guardian_id=None,
            is_ell=False,
        )
        ids.append(student["id"])
    return success_object({"created_count": len(ids), "student_ids": ids}, 201)


@bp.route("/gifted/students/<sid>", methods=["GET"])
def get_student(sid):
    require_roles(*ALL_ROLES)
    student = get_or_404(db.students, sid, "student")
    return success_object(serialize_student(student), 200)


@bp.route("/gifted/students/<sid>/sped-plans", methods=["POST"])
def create_sped_plan(sid):
    require_roles("SpecialEdCoordinator")
    student = get_or_404(db.students, sid, "student")
    body = get_json_body()
    require_fields(body, ["plan_type", "started_on"])
    plan_type = require_enum(body, "plan_type", {"IEP", "PLAN_504"})
    started_raw = body["started_on"]
    parse_date(started_raw, "started_on")

    # uniqueness: at most one SpedPlan per student
    for sp in db.sped_plans.values():
        if sp["student_id"] == sid:
            raise ApiError(
                ERR_DUPLICATE_SPED_PLAN,
                "student already has a SpedPlan",
                409,
            )

    ts = now_iso()
    plan = {
        "id": new_id(),
        "student_id": sid,
        "plan_type": plan_type,
        "started_on": started_raw,
        "created_at": ts,
    }
    db.sped_plans[plan["id"]] = plan
    # has_active_sped_plan is derived at read time from SpedPlan existence.
    return success_object(serialize_sped_plan(plan), 201)


@bp.route("/gifted/students/<sid>/sped-plans", methods=["GET"])
def list_sped_plans(sid):
    require_roles(*ALL_ROLES)
    get_or_404(db.students, sid, "student")
    items = [sp for sp in db.sped_plans.values() if sp["student_id"] == sid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_sped_plan(sp) for sp in page], total, limit, offset)
