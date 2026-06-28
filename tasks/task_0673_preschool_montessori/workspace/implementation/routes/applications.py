"""Application lifecycle endpoints (PRD §3.2-§3.4, SCAFFOLD §1.2 Application)."""
from flask import Blueprint

import errors
from db import db, new_common_fields, touch
from middleware import get_auth, require_role
from response import object_response, array_response
from services import calc, compliance
from services.common import (
    get_json_body, require_fields, require_number, parse_pagination,
    sort_created_asc, paginate, serialize, serialize_list, str_arg, optional_enum,
)

bp = Blueprint("applications", __name__)

READ_ROLES = {"Registrar", "ComplianceOfficer", "Parent"}
APP_STATUSES = {
    "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "WAITLISTED",
    "OFFERED", "ENROLLED", "WITHDRAWN", "DECLINED",
}


# ---------------------------------------------------------------------------
# Shared admissibility checks (PRD §3.3/§3.4): tier/level + age band.
# Order per §2.10: tier mismatch before age out of range.
# ---------------------------------------------------------------------------
def _check_tier_level(application):
    classroom = db.classrooms[application["classroom_id"]]
    tier = db.tiers[application["tier_id"]]
    if classroom["level"] != tier["level"] or not tier["active"]:
        raise errors.tier_level_mismatch()


def _check_age(application):
    classroom = db.classrooms[application["classroom_id"]]
    student = db.students[application["student_id"]]
    age = calc.months_between_for_age(student["date_of_birth"], db.clock_now())
    if age < classroom["min_age_months"] or age > classroom["max_age_months"]:
        raise errors.age_out_of_range()


def _get_app_or_404(application_id):
    app = db.applications.get(application_id)
    if app is None:
        raise errors.not_found("Application not found.")
    return app


@bp.route("/applications", methods=["POST"])
def create_application():
    _, role = get_auth()
    require_role(role, {"Parent", "Registrar"})
    body = get_json_body()
    require_fields(body, ["student_id", "classroom_id", "tier_id"])

    student_id = body["student_id"]
    classroom_id = body["classroom_id"]
    tier_id = body["tier_id"]
    for val, label in ((student_id, "student_id"), (classroom_id, "classroom_id"), (tier_id, "tier_id")):
        if not isinstance(val, str):
            raise errors.invalid_request(f"{label} must be a string.")

    ext_day = False
    if "extended_day_opt_in" in body and body["extended_day_opt_in"] is not None:
        if not isinstance(body["extended_day_opt_in"], bool):
            raise errors.invalid_request("extended_day_opt_in must be a boolean.")
        ext_day = body["extended_day_opt_in"]
    aid = 0
    if "financial_aid_pct" in body and body["financial_aid_pct"] is not None:
        aid = require_number(body, "financial_aid_pct", minimum=0, max_exclusive=1)

    # Body FK existence (PRD §2.9): student, classroom, tier.
    if student_id not in db.students:
        raise errors.not_found("student_id does not exist.")
    if classroom_id not in db.classrooms:
        raise errors.not_found("classroom_id does not exist.")
    if tier_id not in db.tiers:
        raise errors.not_found("tier_id does not exist.")

    app = new_common_fields()
    app.update({
        "student_id": student_id,
        "classroom_id": classroom_id,
        "tier_id": tier_id,
        "status": "SUBMITTED",
        "priority_score": 0,
        "waitlisted_at": None,
        "enrollment_id": None,
        "extended_day_opt_in": ext_day,
        "financial_aid_pct": aid,
    })
    db.applications[app["id"]] = app
    return object_response(serialize(app), 201)


@bp.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    return object_response(serialize(_get_app_or_404(application_id)), 200)


@bp.route("/applications", methods=["GET"])
def list_applications():
    _, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    student_id = str_arg("student_id")
    status = optional_enum(str_arg("status"), APP_STATUSES, "status")
    classroom_id = str_arg("classroom_id")
    tier_id = str_arg("tier_id")
    enrollment_id = str_arg("enrollment_id")

    records = list(db.applications.values())
    if student_id is not None:
        records = [a for a in records if a["student_id"] == student_id]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    if classroom_id is not None:
        records = [a for a in records if a["classroom_id"] == classroom_id]
    if tier_id is not None:
        records = [a for a in records if a["tier_id"] == tier_id]
    if enrollment_id is not None:
        records = [a for a in records if a.get("enrollment_id") == enrollment_id]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Registrar transitions
# ---------------------------------------------------------------------------
@bp.route("/applications/<application_id>/start-review", methods=["POST"])
def start_review(application_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    app = _get_app_or_404(application_id)
    if app["status"] != "SUBMITTED":
        raise errors.invalid_state()
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return object_response(serialize(app), 200)


@bp.route("/applications/<application_id>/request-changes", methods=["POST"])
def request_changes(application_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    app = _get_app_or_404(application_id)
    if app["status"] != "UNDER_REVIEW":
        raise errors.invalid_state()
    app["status"] = "CHANGES_REQUESTED"
    touch(app)
    return object_response(serialize(app), 200)


@bp.route("/applications/<application_id>/resubmit", methods=["POST"])
def resubmit(application_id):
    user_id, role = get_auth()
    require_role(role, {"Parent"})
    app = _get_app_or_404(application_id)
    # Ownership (priority 3, before existence-of-others/state per §2.10 ordering:
    # owner check precedes state check).
    _require_owner(user_id, app)
    if app["status"] != "CHANGES_REQUESTED":
        raise errors.invalid_state()
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return object_response(serialize(app), 200)


@bp.route("/applications/<application_id>/waitlist", methods=["POST"])
def waitlist(application_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    app = _get_app_or_404(application_id)
    if app["status"] != "UNDER_REVIEW":
        raise errors.invalid_state()
    _check_tier_level(app)
    _check_age(app)
    app["status"] = "WAITLISTED"
    app["waitlisted_at"] = db.clock.now_iso()
    student = db.students[app["student_id"]]
    app["priority_score"] = calc.compute_priority_score(app, student)
    touch(app)
    return object_response(serialize(app), 200)


@bp.route("/applications/<application_id>/offer", methods=["POST"])
def offer(application_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    app = _get_app_or_404(application_id)
    if app["status"] != "UNDER_REVIEW":
        raise errors.invalid_state()
    _check_tier_level(app)
    _check_age(app)
    classroom = db.classrooms[app["classroom_id"]]
    # Order per §2.10: not-compliant (9) before classroom-full (13).
    if classroom["compliance_status"] != "COMPLIANT":
        raise errors.classroom_not_compliant()
    if classroom["placed_count"] >= classroom["capacity"]:
        raise errors.classroom_full()
    app["status"] = "OFFERED"
    touch(app)
    return object_response(serialize(app), 200)


@bp.route("/applications/<application_id>/decline", methods=["POST"])
def decline(application_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    app = _get_app_or_404(application_id)
    if app["status"] != "UNDER_REVIEW":
        raise errors.invalid_state()
    app["status"] = "DECLINED"
    touch(app)
    return object_response(serialize(app), 200)


# ---------------------------------------------------------------------------
# Parent transitions
# ---------------------------------------------------------------------------
@bp.route("/applications/<application_id>/accept-offer", methods=["POST"])
def accept_offer(application_id):
    user_id, role = get_auth()
    require_role(role, {"Parent"})
    app = _get_app_or_404(application_id)
    _require_owner(user_id, app)
    body = get_json_body()
    require_fields(body, ["program_start_date"])
    program_start = body["program_start_date"]
    if not isinstance(program_start, str):
        raise errors.invalid_request("program_start_date must be an ISO 8601 string.")
    from db import parse_iso
    try:
        parse_iso(program_start)
    except (ValueError, TypeError):
        raise errors.invalid_request("program_start_date must be a valid ISO 8601 instant.")

    if app["status"] != "OFFERED":
        raise errors.invalid_state()
    _check_tier_level(app)
    classroom = db.classrooms[app["classroom_id"]]
    # §2.10 order: not-compliant (9) before classroom-full (13).
    if classroom["compliance_status"] != "COMPLIANT":
        raise errors.classroom_not_compliant()
    if classroom["placed_count"] >= classroom["capacity"]:
        raise errors.classroom_full()

    tier = db.tiers[app["tier_id"]]
    student = db.students[app["student_id"]]

    enrollment = new_common_fields()
    net_annual, monthly = calc.compute_tuition_net(
        tier, student, app["extended_day_opt_in"], app["financial_aid_pct"]
    )
    deposit = calc.compute_deposit(tier)
    enrollment.update({
        "application_id": app["id"],
        "student_id": app["student_id"],
        "classroom_id": app["classroom_id"],
        "tier_id": app["tier_id"],
        "placement_status": "PLACED",
        "billing_status": "DEPOSIT_DUE",
        "extended_day_opt_in": app["extended_day_opt_in"],
        "program_start_date": program_start,
        "net_annual_cents": net_annual,
        "monthly_installment_cents": monthly,
        "deposit_cents": deposit,
        "paid_to_date_cents": 0,
    })
    db.enrollments[enrollment["id"]] = enrollment

    app["enrollment_id"] = enrollment["id"]
    app["status"] = "ENROLLED"
    touch(app)

    # Place the child: bump placed_count + recompute compliance (mutation on classroom).
    compliance.recompute_and_touch(classroom)

    # accept-offer returns the created Enrollment (SCAFFOLD output: Enrollment).
    return object_response(serialize(enrollment), 200)


@bp.route("/applications/<application_id>/decline-offer", methods=["POST"])
def decline_offer(application_id):
    user_id, role = get_auth()
    require_role(role, {"Parent"})
    app = _get_app_or_404(application_id)
    _require_owner(user_id, app)
    if app["status"] != "OFFERED":
        raise errors.invalid_state()
    app["status"] = "DECLINED"
    touch(app)
    return object_response(serialize(app), 200)


def _require_owner(user_id, app):
    """Parent ownership: acting X-User-ID == owning Student.parent_user_id."""
    student = db.students.get(app["student_id"])
    if student is None or student["parent_user_id"] != user_id:
        raise errors.not_resource_owner()
