"""MealPlanEnrollment and PlanChangeRequest endpoints (PRD 3.4)."""

from flask import Blueprint, g, request

from db import store
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE_TRANSITION, ERR_STALE_VERSION, ERR_HOLDER_NOT_ACTIVE,
    ERR_TERM_NOT_OPEN, ERR_PLAN_NOT_PUBLISHED, ERR_ENROLLMENT_NOT_ACTIVE,
    ERR_PLAN_CHANGE_WINDOW_CLOSED, ERR_PLAN_CHANGE_EFFECTIVE_WEEK_INVALID,
    ERR_HOUSING_INELIGIBLE_FOR_PLAN, ERR_HOLDER_TYPE_INELIGIBLE_FOR_PLAN,
    ERR_ENROLLMENT_OVERLAP, ERR_PENDING_CHANGE_EXISTS, ERR_FRAUD_HOLD,
)
from middleware import (
    authenticate, require_roles, get_body, v_str, v_int, find_or_404, pub,
    paginate,
)
from response import success
from services.core import new_row, touch, clock, dt_of
from services.cascades import activate_enrollment, cancel_enrollment
from services.pricing import plan_change_proration

bp = Blueprint("enrollments", __name__)


def _check_plan_eligibility(holder, plan):
    if plan["requires_on_campus_housing"] and holder["housing_status"] != "ON_CAMPUS":
        err(ERR_HOUSING_INELIGIBLE_FOR_PLAN,
            "Plan requires ON_CAMPUS housing")
    if holder["holder_type"] not in plan["eligible_holder_types"]:
        err(ERR_HOLDER_TYPE_INELIGIBLE_FOR_PLAN,
            "Holder type is not eligible for this plan")


# -------------------------------------------------------------- enrollments
@bp.route("/api/card-holders/<hid>/enrollments", methods=["POST"])
def create_enrollment(hid):
    authenticate()
    require_roles("DiningServicesManager")
    body = get_body()
    plan_id = v_str(body, "plan_id")
    term_id = v_str(body, "term_id")
    holder = find_or_404(store.holders, hid)
    plan = find_or_404(store.plans, plan_id)
    term = find_or_404(store.terms, term_id)
    if holder["status"] != "ACTIVE":
        err(ERR_HOLDER_NOT_ACTIVE, "Holder is not ACTIVE")
    if plan["status"] != "PUBLISHED":
        err(ERR_PLAN_NOT_PUBLISHED, "Plan is not PUBLISHED")
    if term["status"] not in ("SCHEDULED", "OPEN"):
        err(ERR_TERM_NOT_OPEN, "Term is not open for enrollment")
    _check_plan_eligibility(holder, plan)
    for enr in store.enrollments.values():
        if (enr["holder_id"] == holder["id"] and enr["term_id"] == term["id"]
                and enr["status"] in ("ASSIGNED", "ACTIVE")):
            err(ERR_ENROLLMENT_OVERLAP,
                "Holder already has a live enrollment in this term")
    enr = new_row()
    enr.update({
        "holder_id": holder["id"],
        "plan_id": plan["id"],
        "term_id": term["id"],
        "supersedes_enrollment_id": None,
        "status": "ASSIGNED",
        "charge_cents": None,
        "credit_cents": 0,
        "weekly_swipe_allowance": None,
        "is_unlimited_swipes": None,
        "swipes_used_this_week": 0,
        "enrolled_week_index": None,
        "activated_at": None,
    })
    store.enrollments[enr["id"]] = enr
    if term["status"] == "OPEN":
        activate_enrollment(enr, plan, term)
    return success(pub(enr), 201)


def _enrollment_visible(enr):
    """CardHolder callers see only their own enrollments."""
    return g.role != "CardHolder" or enr["holder_id"] == g.user_id


@bp.route("/api/enrollments", methods=["GET"])
def list_enrollments():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "CardHolder")
    rows = list(store.enrollments.values())
    if g.role == "CardHolder":
        rows = [e for e in rows if e["holder_id"] == g.user_id]
    holder_id = request.args.get("holder_id")
    plan_id = request.args.get("plan_id")
    term_id = request.args.get("term_id")
    supersedes = request.args.get("supersedes_enrollment_id")
    status = request.args.get("status")
    if holder_id is not None:
        if g.role == "CardHolder" and holder_id != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER, "Cannot filter by another holder")
        rows = [e for e in rows if e["holder_id"] == holder_id]
    if plan_id is not None:
        rows = [e for e in rows if e["plan_id"] == plan_id]
    if term_id is not None:
        rows = [e for e in rows if e["term_id"] == term_id]
    if supersedes is not None:
        rows = [e for e in rows if e.get("supersedes_enrollment_id") == supersedes]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "CardHolder")
    enr = store.enrollments.get(eid)
    if enr is not None and not _enrollment_visible(enr):
        err(ERR_NOT_RESOURCE_OWNER, "CardHolder may read only its own enrollments")
    if enr is None:
        err(ERR_NOT_FOUND, "Enrollment not found")
    return success(pub(enr), 200)


@bp.route("/api/enrollments/<eid>/cancel", methods=["POST"])
def cancel_enrollment_endpoint(eid):
    authenticate()
    require_roles("DiningServicesManager")
    enr = find_or_404(store.enrollments, eid)
    if enr["status"] not in ("ASSIGNED", "ACTIVE"):
        err(ERR_INVALID_STATE_TRANSITION,
            "Only an ASSIGNED or ACTIVE enrollment can be cancelled")
    cancel_enrollment(enr)
    return success(pub(enr), 200)


@bp.route("/api/enrollments/<eid>/change-requests", methods=["GET"])
def list_enrollment_change_requests(eid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "CardHolder")
    enr = store.enrollments.get(eid)
    if enr is not None and not _enrollment_visible(enr):
        err(ERR_NOT_RESOURCE_OWNER, "CardHolder may read only its own enrollments")
    if enr is None:
        err(ERR_NOT_FOUND, "Enrollment not found")
    rows = [c for c in store.change_requests.values()
            if c["enrollment_id"] == enr["id"]]
    data, page = paginate(rows)
    return success(data, 200, page)


# ----------------------------------------------------------- change requests
@bp.route("/api/enrollments/<eid>/change-requests", methods=["POST"])
def create_change_request(eid):
    authenticate()
    require_roles("CardHolder")
    enr = store.enrollments.get(eid)
    if enr is not None and enr["holder_id"] != g.user_id:
        err(ERR_NOT_RESOURCE_OWNER,
            "CardHolder may request changes only on its own enrollment")
    body = get_body()
    new_plan_id = v_str(body, "new_plan_id")
    expected_version = v_int(body, "expected_enrollment_version")
    if enr is None:
        err(ERR_NOT_FOUND, "Enrollment not found")
    new_plan = find_or_404(store.plans, new_plan_id)
    if expected_version != enr["version"]:
        err(ERR_STALE_VERSION,
            "expected_enrollment_version does not match the enrollment version")
    term = store.terms[enr["term_id"]]
    if term["status"] != "OPEN":
        err(ERR_TERM_NOT_OPEN, "Term is not OPEN")
    if enr["status"] != "ACTIVE":
        err(ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment is not ACTIVE")
    if new_plan["status"] != "PUBLISHED":
        err(ERR_PLAN_NOT_PUBLISHED, "New plan is not PUBLISHED")
    # Priority 11 (PRD 2.10): suspended or fraud-flagged holders are blocked
    # from value-extending actions; this precedes the temporal window checks.
    holder = store.holders[enr["holder_id"]]
    if holder["status"] == "SUSPENDED" or holder["fraud_flag"]:
        err(ERR_FRAUD_HOLD, "Holder is under a fraud hold")
    if clock() > dt_of(term, "add_drop_deadline"):
        err(ERR_PLAN_CHANGE_WINDOW_CLOSED,
            "The plan change window has closed")
    if new_plan["id"] == enr["plan_id"]:
        err(ERR_VALIDATION, "new_plan_id must differ from the current plan")
    _check_plan_eligibility(holder, new_plan)
    for cr in store.change_requests.values():
        if (cr["enrollment_id"] == enr["id"]
                and cr["status"] in ("SUBMITTED", "APPROVED")):
            err(ERR_PENDING_CHANGE_EXISTS,
                "A pending change request already exists on the enrollment")
    cr = new_row()
    cr.update({
        "enrollment_id": enr["id"],
        "new_plan_id": new_plan["id"],
        "requested_by": g.user_id,
        "status": "SUBMITTED",
        "effective_week_index": None,
        "charge_delta_cents": None,
        "funding_delta_cents": None,
        "void_reason": None,
        "decided_by": None,
        "denial_reason": None,
    })
    store.change_requests[cr["id"]] = cr
    touch(enr)  # submitting a change request mutates the enrollment
    return success(pub(cr), 201)


@bp.route("/api/change-requests", methods=["GET"])
def list_change_requests():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "CardHolder")
    rows = list(store.change_requests.values())
    if g.role == "CardHolder":
        own_enrollments = {e["id"] for e in store.enrollments.values()
                           if e["holder_id"] == g.user_id}
        rows = [c for c in rows if c["enrollment_id"] in own_enrollments]
    enrollment_id = request.args.get("enrollment_id")
    new_plan_id = request.args.get("new_plan_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        if g.role == "CardHolder":
            target = store.enrollments.get(enrollment_id)
            if target is not None and target["holder_id"] != g.user_id:
                err(ERR_NOT_RESOURCE_OWNER,
                    "Cannot filter by another holder's enrollment")
        rows = [c for c in rows if c["enrollment_id"] == enrollment_id]
    if new_plan_id is not None:
        rows = [c for c in rows if c["new_plan_id"] == new_plan_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/change-requests/<cid>", methods=["GET"])
def get_change_request(cid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "CardHolder")
    cr = store.change_requests.get(cid)
    if cr is not None and g.role == "CardHolder":
        enr = store.enrollments.get(cr["enrollment_id"])
        if enr is None or enr["holder_id"] != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER,
                "CardHolder may read only its own change requests")
    if cr is None:
        err(ERR_NOT_FOUND, "Change request not found")
    return success(pub(cr), 200)


@bp.route("/api/change-requests/<cid>/approve", methods=["POST"])
def approve_change_request(cid):
    authenticate()
    require_roles("DiningServicesManager")
    cr = find_or_404(store.change_requests, cid)
    if cr["status"] != "SUBMITTED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a SUBMITTED change request can be approved")
    enr = store.enrollments[cr["enrollment_id"]]
    term = store.terms[enr["term_id"]]
    if term["status"] != "OPEN":
        err(ERR_TERM_NOT_OPEN, "Term is not OPEN")
    if clock() > dt_of(term, "add_drop_deadline"):
        err(ERR_PLAN_CHANGE_WINDOW_CLOSED, "The plan change window has closed")
    if term["current_week_index"] + 1 > term["total_weeks"]:
        err(ERR_PLAN_CHANGE_EFFECTIVE_WEEK_INVALID,
            "The effective week would fall beyond the term")
    effective_week = term["current_week_index"] + 1
    old_plan = store.plans[enr["plan_id"]]
    new_plan = store.plans[cr["new_plan_id"]]
    charge_delta, funding_delta, new_due, credit_from_old = plan_change_proration(
        enr, old_plan, new_plan, term, effective_week)
    cr["status"] = "APPROVED"
    cr["effective_week_index"] = effective_week
    cr["charge_delta_cents"] = charge_delta
    cr["funding_delta_cents"] = funding_delta
    cr["decided_by"] = g.user_id
    cr["_new_due"] = new_due
    cr["_credit_from_old"] = credit_from_old
    touch(cr)
    return success(pub(cr), 200)


@bp.route("/api/change-requests/<cid>/deny", methods=["POST"])
def deny_change_request(cid):
    authenticate()
    require_roles("DiningServicesManager")
    body = get_body()
    denial_reason = v_str(body, "denial_reason")
    cr = find_or_404(store.change_requests, cid)
    if cr["status"] != "SUBMITTED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a SUBMITTED change request can be denied")
    cr["status"] = "DENIED"
    cr["denial_reason"] = denial_reason
    cr["decided_by"] = g.user_id
    touch(cr)
    return success(pub(cr), 200)


@bp.route("/api/change-requests/<cid>/withdraw", methods=["POST"])
def withdraw_change_request(cid):
    authenticate()
    require_roles("CardHolder")
    cr = store.change_requests.get(cid)
    if cr is not None:
        enr = store.enrollments.get(cr["enrollment_id"])
        if enr is None or enr["holder_id"] != g.user_id:
            err(ERR_NOT_RESOURCE_OWNER,
                "CardHolder may withdraw only its own change requests")
    if cr is None:
        err(ERR_NOT_FOUND, "Change request not found")
    if cr["status"] != "SUBMITTED":
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a SUBMITTED change request can be withdrawn")
    cr["status"] = "WITHDRAWN"
    touch(cr)
    return success(pub(cr), 200)
