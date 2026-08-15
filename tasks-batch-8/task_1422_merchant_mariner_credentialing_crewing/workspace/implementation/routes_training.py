"""Training courses, enrollments, budgets, reimbursement (PRD 3.9)."""

from flask import Blueprint, g, request

from db import store
from errors import err
from helpers import (
    get_body,
    opt_int,
    opt_str,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_str,
    require_roles,
    scope_mariner_id,
    scope_mariner_resource,
    sorted_items,
)
from response import success
from serialize import (
    ser_training_budget,
    ser_training_course,
    ser_training_enrollment,
)
from services import (
    budget_for,
    compute_provisional_amount,
)

bp = Blueprint("training", __name__)

ALL_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
)
STAFF_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
)

OPEN_ENROLLMENT_STATES = ("REQUESTED", "APPROVED", "ENROLLED", "COMPLETED")


def _get_course(course_id):
    c = store.training_courses.get(course_id)
    if c is None:
        raise err(
            "ERR_TRAINING_COURSE_NOT_FOUND",
            "Training course %s not found" % course_id,
        )
    return c


def _get_enrollment(enrollment_id):
    e = store.training_enrollments.get(enrollment_id)
    if e is None:
        raise err(
            "ERR_TRAINING_ENROLLMENT_NOT_FOUND",
            "Training enrollment %s not found" % enrollment_id,
        )
    return e


def _get_mariner(mariner_id):
    m = store.mariners.get(mariner_id)
    if m is None:
        raise err("ERR_MARINER_NOT_FOUND", "Mariner %s not found" % mariner_id)
    return m


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------


@bp.route("/training-courses", methods=["POST"])
@require_roles("FleetAdmin")
def create_course():
    body = get_body()
    code = req_str(body, "course_code")
    title = req_str(body, "title")
    provider = req_str(body, "provider")
    grants = opt_str(body, "grants_endorsement_code")
    start = req_dt(body, "start_date")
    end = req_dt(body, "end_date")
    capacity = req_int(body, "seat_capacity")
    cost = req_int(body, "cost_cents")
    if end < start:
        raise err("ERR_INVALID_REQUEST", "end_date must be on or after start_date")
    if any(c["course_code"] == code for c in store.training_courses.values()):
        raise err("ERR_INVALID_REQUEST", "course_code %s already exists" % code)
    c = {
        "course_code": code,
        "title": title,
        "provider": provider,
        "grants_endorsement_code": grants,
        "start_date": start,
        "end_date": end,
        "seat_capacity": capacity,
        "seats_reserved": 0,
        "cost_cents": cost,
        "status": "SCHEDULED",
    }
    store.stamp(c)
    store.training_courses[c["id"]] = c
    return success(ser_training_course(c), code=201)


@bp.route("/training-courses", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_courses():
    items = list(store.training_courses.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_training_course(c) for c in page], response_type="array", pagination=meta
    )


@bp.route("/training-courses/<course_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_course(course_id):
    return success(ser_training_course(_get_course(course_id)))


@bp.route("/training-courses/<course_id>/cancel", methods=["POST"])
@require_roles("FleetAdmin")
def cancel_course(course_id):
    c = _get_course(course_id)
    if c["status"] != "SCHEDULED":
        raise err(
            "ERR_COURSE_NOT_SCHEDULED", "Only a SCHEDULED course can be cancelled"
        )
    c["status"] = "CANCELLED"
    store.bump(c)
    # Enrollment cascade (PRD 3.9).
    for e in store.training_enrollments.values():
        if e["course_id"] != c["id"]:
            continue
        if e["status"] == "REQUESTED":
            e["status"] = "REJECTED"
            store.bump(e)
        elif e["status"] == "APPROVED":
            e["status"] = "CANCELLED"
            store.bump(e)
        elif e["status"] == "ENROLLED":
            e["status"] = "CANCELLED"
            store.bump(e)
            b = budget_for(e["mariner_id"], c["start_date"].year)
            if b is not None and e["provisional_amount_cents"] is not None:
                b["reserved_cents"] -= e["provisional_amount_cents"]
                store.bump(b)
            c["seats_reserved"] -= 1
    return success(ser_training_course(c))


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------


@bp.route("/training-courses/<course_id>/enrollments", methods=["POST"])
@require_roles("Mariner")
def request_enrollment(course_id):
    course = _get_course(course_id)
    get_body()
    m = store.mariners.get(g.user_id)
    if m is None:
        raise err("ERR_MARINER_NOT_FOUND", "Mariner %s not found" % g.user_id)
    if course["status"] != "SCHEDULED":
        raise err(
            "ERR_COURSE_NOT_SCHEDULED",
            "Enrollment requires a SCHEDULED course",
        )
    if m["status"] != "ACTIVE":
        raise err("ERR_MARINER_NOT_ACTIVE", "Mariner must be ACTIVE to enroll")
    if m["training_privileges"] != "ENABLED":
        raise err(
            "ERR_TRAINING_PRIVILEGES_SUSPENDED",
            "Training privileges are suspended",
        )
    if any(
        e["mariner_id"] == m["id"]
        and e["course_id"] == course["id"]
        and e["status"] in OPEN_ENROLLMENT_STATES
        for e in store.training_enrollments.values()
    ):
        raise err(
            "ERR_DUPLICATE_ENROLLMENT",
            "An open enrollment already exists for this mariner and course",
        )
    e = {
        "course_id": course["id"],
        "mariner_id": m["id"],
        "status": "REQUESTED",
        "channel_snapshot": None,
        "provisional_amount_cents": None,
        "receipt_amount_cents": None,
        "reimbursed_amount_cents": None,
        "requested_by_user_id": g.user_id,
        "approved_by_user_id": None,
        "reimbursed_by_user_id": None,
    }
    store.stamp(e)
    store.training_enrollments[e["id"]] = e
    return success(ser_training_enrollment(e), code=201)


@bp.route("/training-courses/<course_id>/enrollments", methods=["GET"])
@require_roles(*STAFF_ROLES)
def list_course_enrollments(course_id):
    course = _get_course(course_id)
    items = [
        e for e in store.training_enrollments.values() if e["course_id"] == course["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_training_enrollment(e) for e in page],
        response_type="array",
        pagination=meta,
    )


@bp.route("/mariners/<mariner_id>/enrollments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_mariner_enrollments(mariner_id):
    scope_mariner_id(mariner_id)
    m = _get_mariner(mariner_id)
    items = [
        e for e in store.training_enrollments.values() if e["mariner_id"] == m["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_training_enrollment(e) for e in page],
        response_type="array",
        pagination=meta,
    )


@bp.route("/training-enrollments/<enrollment_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_enrollment(enrollment_id):
    e = _get_enrollment(enrollment_id)
    scope_mariner_resource(e["mariner_id"])
    return success(ser_training_enrollment(e))


@bp.route("/training-enrollments/<enrollment_id>/approve", methods=["POST"])
@require_roles("CrewingManager")
def approve_enrollment(enrollment_id):
    e = _get_enrollment(enrollment_id)
    if e["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Only REQUESTED enrollments can be approved")
    m = _get_mariner(e["mariner_id"])
    if m["readiness_posture"] == "BLOCKED":
        raise err("ERR_MARINER_NOT_CLEAR", "Mariner readiness posture is BLOCKED")
    e["status"] = "APPROVED"
    e["channel_snapshot"] = m["hire_channel"]
    e["approved_by_user_id"] = g.user_id
    store.bump(e)
    return success(ser_training_enrollment(e))


@bp.route("/training-enrollments/<enrollment_id>/reject", methods=["POST"])
@require_roles("CrewingManager")
def reject_enrollment(enrollment_id):
    e = _get_enrollment(enrollment_id)
    get_body()  # optional reason
    if e["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Only REQUESTED enrollments can be rejected")
    e["status"] = "REJECTED"
    store.bump(e)
    return success(ser_training_enrollment(e))


@bp.route("/training-enrollments/<enrollment_id>/enroll", methods=["POST"])
@require_roles("FleetAdmin")
def enroll(enrollment_id):
    e = _get_enrollment(enrollment_id)
    if e["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only APPROVED enrollments can enroll")
    course = _get_course(e["course_id"])
    if course["status"] != "SCHEDULED":
        raise err("ERR_COURSE_NOT_SCHEDULED", "Course is no longer SCHEDULED")
    m = _get_mariner(e["mariner_id"])
    # Readiness gate (pipeline step 10).
    if m["readiness_posture"] == "BLOCKED":
        raise err("ERR_MARINER_NOT_CLEAR", "Mariner readiness posture is BLOCKED")
    # Aggregate (pipeline step 14): open seat.
    if course["seat_capacity"] - course["seats_reserved"] < 1:
        raise err("ERR_COURSE_FULL", "Course has no open seats")
    provisional = compute_provisional_amount(
        course["cost_cents"], e["channel_snapshot"]
    )
    # Fiscal gate (pipeline step 15): budget availability. The budget row is
    # persisted only on a successful enroll.
    fiscal_year = course["start_date"].year
    budget = budget_for(m["id"], fiscal_year)
    available = (
        budget["annual_cap_cents"] - budget["reserved_cents"] - budget["used_cents"]
        if budget is not None
        else m["annual_training_cap_cents"]
    )
    if available < provisional:
        raise err(
            "ERR_TRAINING_BUDGET_EXCEEDED",
            "Training budget availability %s is below the provisional %s"
            % (available, provisional),
        )
    if budget is None:
        budget = {
            "mariner_id": m["id"],
            "fiscal_year": fiscal_year,
            "annual_cap_cents": m["annual_training_cap_cents"],
            "reserved_cents": 0,
            "used_cents": 0,
        }
        store.stamp(budget)
        store.training_budgets[budget["id"]] = budget
    budget["reserved_cents"] += provisional
    store.bump(budget)
    course["seats_reserved"] += 1
    store.bump(course)
    e["status"] = "ENROLLED"
    e["provisional_amount_cents"] = provisional
    store.bump(e)
    return success(ser_training_enrollment(e))


@bp.route("/training-enrollments/<enrollment_id>/record-completion", methods=["POST"])
@require_roles("FleetAdmin")
def record_completion(enrollment_id):
    e = _get_enrollment(enrollment_id)
    body = get_body()
    outcome = req_enum(body, "outcome", ("COMPLETED", "NO_SHOW"))
    if e["status"] != "ENROLLED":
        raise err(
            "ERR_INVALID_STATE",
            "Only ENROLLED enrollments can record completion",
        )
    m = _get_mariner(e["mariner_id"])
    course = _get_course(e["course_id"])
    if outcome == "COMPLETED":
        # Seat and budget reservation are retained until reimbursement.
        e["status"] = "COMPLETED"
        store.bump(e)
        return success(ser_training_enrollment(e))
    # NO_SHOW: budget reservation released, seat deliberately retained, strike.
    e["status"] = "NO_SHOW"
    store.bump(e)
    budget = budget_for(m["id"], course["start_date"].year)
    if budget is not None and e["provisional_amount_cents"] is not None:
        budget["reserved_cents"] -= e["provisional_amount_cents"]
        store.bump(budget)
    m["no_show_strike_count"] += 1
    if m["no_show_strike_count"] >= 2 and m["training_privileges"] != "SUSPENDED":
        m["training_privileges"] = "SUSPENDED"
        store.bump(m)
        # Cascade: REQUESTED -> REJECTED, APPROVED -> CANCELLED.
        for other in store.training_enrollments.values():
            if other["mariner_id"] != m["id"]:
                continue
            if other["status"] == "REQUESTED":
                other["status"] = "REJECTED"
                store.bump(other)
            elif other["status"] == "APPROVED":
                other["status"] = "CANCELLED"
                store.bump(other)
    else:
        store.bump(m)
    return success(ser_training_enrollment(e))


@bp.route("/training-enrollments/<enrollment_id>/reimburse", methods=["POST"])
@require_roles("FleetAdmin")
def reimburse(enrollment_id):
    e = _get_enrollment(enrollment_id)
    body = get_body()
    receipt = req_int(body, "receipt_amount_cents", min_v=0)
    # Segregation of duties (pipeline step 8) precedes the state check (step 9).
    if e["approved_by_user_id"] is not None and g.user_id == e["approved_by_user_id"]:
        raise err(
            "ERR_SOD_REIMBURSE_SAME_APPROVER",
            "The reimburser must differ from the approver",
        )
    if e["status"] != "COMPLETED":
        raise err(
            "ERR_INVALID_STATE", "Only COMPLETED enrollments can be reimbursed"
        )
    reimbursed = min(receipt, e["provisional_amount_cents"])
    e["receipt_amount_cents"] = receipt
    e["reimbursed_amount_cents"] = reimbursed
    e["reimbursed_by_user_id"] = g.user_id
    e["status"] = "REIMBURSED"
    store.bump(e)
    course = _get_course(e["course_id"])
    budget = budget_for(e["mariner_id"], course["start_date"].year)
    if budget is not None:
        budget["used_cents"] += reimbursed
        budget["reserved_cents"] -= e["provisional_amount_cents"]
        store.bump(budget)
    return success(ser_training_enrollment(e))


@bp.route("/training-enrollments/<enrollment_id>/cancel", methods=["POST"])
@require_roles("Mariner", "CrewingManager", "FleetAdmin")
def cancel_enrollment(enrollment_id):
    e = _get_enrollment(enrollment_id)
    scope_mariner_resource(e["mariner_id"])
    if e["status"] not in ("APPROVED", "ENROLLED"):
        raise err(
            "ERR_INVALID_STATE",
            "Only APPROVED or ENROLLED enrollments can be cancelled",
        )
    was_enrolled = e["status"] == "ENROLLED"
    e["status"] = "CANCELLED"
    store.bump(e)
    if was_enrolled:
        course = _get_course(e["course_id"])
        course["seats_reserved"] -= 1
        store.bump(course)
        budget = budget_for(e["mariner_id"], course["start_date"].year)
        if budget is not None and e["provisional_amount_cents"] is not None:
            budget["reserved_cents"] -= e["provisional_amount_cents"]
            store.bump(budget)
    return success(ser_training_enrollment(e))


# ---------------------------------------------------------------------------
# Training budgets
# ---------------------------------------------------------------------------


@bp.route("/mariners/<mariner_id>/training-budgets", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_training_budgets(mariner_id):
    scope_mariner_id(mariner_id)
    m = _get_mariner(mariner_id)
    items = [
        b for b in store.training_budgets.values() if b["mariner_id"] == m["id"]
    ]
    fy = request.args.get("fiscal_year")
    if fy is not None:
        try:
            fy_int = int(fy)
        except (TypeError, ValueError):
            raise err(
                "ERR_INVALID_REQUEST", "Query parameter 'fiscal_year' must be an integer"
            )
        items = [b for b in items if b["fiscal_year"] == fy_int]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_training_budget(b) for b in page], response_type="array", pagination=meta
    )
