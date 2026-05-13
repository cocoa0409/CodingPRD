"""TravelApplication endpoints."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, request

from db import STORE
from errors import (
    APIError, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_NOT_CURRENT_APPROVER, ERR_NOT_FOUND,
    ERR_REFERENCE_INVALID, ERR_VALIDATION, ERR_VERSION_CONFLICT,
    ERR_OPTION_NOT_ELIGIBLE, ERR_SEGMENT_OUTSIDE_TRIP, ERR_SEGMENT_TIME_OVERLAP,
    ERR_HOTEL_NIGHT_OVERLAP, ERR_BUDGET_OVERRUN,
)
from middleware import require_auth
from response import success, parse_pagination, paginate
from serializers import (
    travel_application as ser_app,
    itinerary_segment as ser_seg,
)
from services.audit import emit_external_sync
from services.travel_application import (
    compute_required_chain, pin_standard_version, recompute_total_booked_cost,
    has_active_segments, assert_current_approver, next_chain_step, bump,
    ROLE_TO_CHAIN_STEP, BUDGET_OVERRUN_FACTOR,
)
from services.validate import (
    require_body, get_str, get_enum, get_bool, get_money, get_datetime, get_int,
)
from utils import CLOCK, new_uuid, parse_ts, format_ts


bp = Blueprint("travel_applications", __name__)


TIERS = {"TIER_1", "TIER_2", "TIER_3", "OVERSEAS"}
SCOPES = {"DOMESTIC", "OVERSEAS"}
SEGMENT_TYPES = {"FLIGHT", "TRAIN", "HOTEL", "CAR"}


# ===================== Helpers =====================
def _load_app_or_404(app_id):
    row = STORE.travel_applications.get(app_id)
    if not row:
        raise APIError(ERR_NOT_FOUND, f"TravelApplication {app_id} not found", 404)
    return row


def _ownership_or_forbid(app: dict):
    """Applicant ownership: caller's X-User-ID must equal app.applicant_id."""
    if g.role == "Applicant" and app["applicant_id"] != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Applicant is not the owner", 403)


# ===================== CRUD =====================
@bp.route("/travel-applications", methods=["POST"])
@require_auth(["Applicant"])
def create_application():
    body = require_body(request.get_json(silent=True))
    destination_city = get_str(body, "destination_city")
    destination_tier = get_enum(body, "destination_tier", TIERS)
    travel_scope = get_enum(body, "travel_scope", SCOPES)
    purpose = get_str(body, "purpose")
    planned_start = get_datetime(body, "planned_start")
    planned_end = get_datetime(body, "planned_end")
    if planned_end <= planned_start:
        raise APIError(ERR_VALIDATION, "planned_end must be > planned_start", 422)
    estimated_budget = get_money(body, "estimated_budget")
    urgent = get_bool(body, "urgent", required=False, default=False)

    # Applicant owns their own row; applicant_id == X-User-ID
    applicant_id = g.user_id
    # Applicant must exist
    if applicant_id not in STORE.employees:
        raise APIError(ERR_REFERENCE_INVALID, "Applicant employee not found", 422)

    now = CLOCK.now_iso()
    aid = new_uuid()
    row = {
        "id": aid,
        "applicant_id": applicant_id,
        "destination_city": destination_city,
        "destination_tier": destination_tier,
        "travel_scope": travel_scope,
        "purpose": purpose,
        "planned_start": format_ts(planned_start),
        "planned_end": format_ts(planned_end),
        "estimated_budget": estimated_budget,
        "urgent": urgent,
        "status": "DRAFT",
        "required_chain": None,
        "standard_version_pinned": None,
        "total_booked_cost": Decimal("0.00"),
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.travel_applications[aid] = row
    return success(ser_app(row), status=201)


@bp.route("/travel-applications/<aid>", methods=["GET"])
@require_auth(["Applicant", "Supervisor", "DeptHead", "Finance", "GeneralManager", "Admin"])
def get_application(aid):
    row = _load_app_or_404(aid)
    return success(ser_app(row))


@bp.route("/travel-applications/<aid>", methods=["PATCH"])
@require_auth(["Applicant"])
def patch_application(aid):
    app = _load_app_or_404(aid)
    _ownership_or_forbid(app)
    if app["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "TravelApplication is not in DRAFT", 409)
    body = require_body(request.get_json(silent=True))

    # Pre-validate the schema of each provided field (priority 18) BEFORE OCC (priority 19).
    proposed = {}
    if "destination_city" in body and body["destination_city"] is not None:
        proposed["destination_city"] = get_str(body, "destination_city")
    if "destination_tier" in body and body["destination_tier"] is not None:
        proposed["destination_tier"] = get_enum(body, "destination_tier", TIERS)
    if "travel_scope" in body and body["travel_scope"] is not None:
        proposed["travel_scope"] = get_enum(body, "travel_scope", SCOPES)
    if "purpose" in body and body["purpose"] is not None:
        proposed["purpose"] = get_str(body, "purpose")
    if "planned_start" in body and body["planned_start"] is not None:
        proposed["planned_start"] = format_ts(get_datetime(body, "planned_start"))
    if "planned_end" in body and body["planned_end"] is not None:
        proposed["planned_end"] = format_ts(get_datetime(body, "planned_end"))
    if "estimated_budget" in body and body["estimated_budget"] is not None:
        proposed["estimated_budget"] = get_money(body, "estimated_budget")
    if "urgent" in body and body["urgent"] is not None:
        proposed["urgent"] = get_bool(body, "urgent", required=False, default=app.get("urgent", False))

    # Range check on planned dates (schema-level)
    pstart_str = proposed.get("planned_start", app["planned_start"])
    pend_str = proposed.get("planned_end", app["planned_end"])
    ps = parse_ts(pstart_str)
    pe = parse_ts(pend_str)
    if pe <= ps:
        raise APIError(ERR_VALIDATION, "planned_end must be > planned_start", 422)

    # OCC: version optional (priority 19, AFTER schema)
    if "version" in body and body["version"] is not None:
        if not isinstance(body["version"], int) or isinstance(body["version"], bool):
            raise APIError(ERR_VALIDATION, "version must be an integer", 422)
        if body["version"] != app["version"]:
            raise APIError(ERR_VERSION_CONFLICT, "version mismatch", 409)

    if proposed:
        app.update(proposed)
        bump(app)
    return success(ser_app(app))


# ===================== Submit =====================
@bp.route("/travel-applications/<aid>/submit", methods=["POST"])
@require_auth(["Applicant"])
def submit_application(aid):
    app = _load_app_or_404(aid)
    _ownership_or_forbid(app)
    if app["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "TravelApplication is not in DRAFT", 409)
    # Applicant matches
    if app["applicant_id"] != g.user_id:
        raise APIError(ERR_NOT_CURRENT_APPROVER, "Acting user is not the applicant", 403)
    # planned_end > planned_start
    ps = parse_ts(app["planned_start"])
    pe = parse_ts(app["planned_end"])
    if pe <= ps:
        raise APIError(ERR_VALIDATION, "planned_end must be > planned_start", 422)
    # estimated_budget >= 0 (already non-negative on create)
    if app["estimated_budget"] is None or app["estimated_budget"] < 0:
        raise APIError(ERR_VALIDATION, "estimated_budget must be >= 0", 422)
    # applicant ACTIVE
    applicant = STORE.employees.get(app["applicant_id"])
    if not applicant or applicant.get("status") != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "Applicant is not ACTIVE", 409)

    # Compute chain
    chain = compute_required_chain(
        estimated_budget=app["estimated_budget"],
        travel_scope=app["travel_scope"],
        urgent=app.get("urgent", False),
    )
    # Pin standard version
    version_pinned = pin_standard_version(app)

    app["required_chain"] = chain
    app["standard_version_pinned"] = version_pinned
    app["status"] = "SUBMITTED"
    bump(app)
    return success(ser_app(app))


# ===================== Approve =====================
@bp.route("/travel-applications/<aid>/approve", methods=["POST"])
@require_auth(["Supervisor", "DeptHead", "Finance", "GeneralManager"])
def approve_application(aid):
    from services.audit import write_approval_record
    app = _load_app_or_404(aid)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise APIError(ERR_VALIDATION, "Request body must be a JSON object", 422)
    comment = body.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise APIError(ERR_VALIDATION, "comment must be a string", 422)

    # State legality (PRD §2.8 priority 5): the application must be in a
    # state that admits the requested transition per §3. The requested
    # transition is role-scoped — Supervisor moves SUBMITTED →
    # SUPERVISOR_APPROVED, DeptHead moves SUPERVISOR_APPROVED →
    # DEPT_HEAD_APPROVED, Finance moves SUPERVISOR_APPROVED or
    # DEPT_HEAD_APPROVED → FINANCE_APPROVED, GM moves FINANCE_APPROVED →
    # GM_APPROVED. The simultaneity hazard text in §3.2 pins the race
    # loser's error to ERR_INVALID_STATE precisely because, after the
    # winner advances, the loser's role no longer has a valid from-state
    # for its transition.
    role_admitted_from = {
        "Supervisor": {"SUBMITTED"},
        "DeptHead": {"SUPERVISOR_APPROVED"},
        "Finance": {"SUPERVISOR_APPROVED", "DEPT_HEAD_APPROVED"},
        "GeneralManager": {"FINANCE_APPROVED"},
    }
    admitted = role_admitted_from.get(g.role, set())
    if app["status"] not in admitted:
        raise APIError(ERR_INVALID_STATE,
                        "Application is not in a state that admits this approval",
                        409)

    # Check current chain step is this role (PRD §2.8 priority 6)
    step = assert_current_approver(app, g.role, g.user_id)

    from_status = app["status"]
    # Decide target status based on step + chain
    chain: list[str] = app["required_chain"]
    if step == "SUPERVISOR":
        # Next status depends on chain composition
        to_status = "SUPERVISOR_APPROVED"
    elif step == "DEPT_HEAD":
        to_status = "DEPT_HEAD_APPROVED"
    elif step == "FINANCE":
        # if GM also in chain -> FINANCE_APPROVED, else go straight to APPROVED
        to_status = "FINANCE_APPROVED" if "GM" in chain else "APPROVED"
    elif step == "GM":
        # GM is always last in chain; auto-transition through GM_APPROVED -> APPROVED
        to_status = "APPROVED"
    else:
        raise APIError(ERR_INVALID_STATE, "Unknown chain step", 409)

    actor_role_label = step  # SUPERVISOR / DEPT_HEAD / FINANCE / GM
    app["status"] = to_status
    bump(app)

    write_approval_record(
        subject_type="TRAVEL_APPLICATION",
        subject_id=app["id"],
        actor_id=g.user_id,
        actor_role=actor_role_label,
        action="APPROVE",
        comment=comment,
        from_status=from_status,
        to_status=to_status,
    )
    return success(ser_app(app))


# ===================== Reject =====================
@bp.route("/travel-applications/<aid>/reject", methods=["POST"])
@require_auth(["Supervisor", "DeptHead", "Finance", "GeneralManager"])
def reject_application(aid):
    from services.audit import write_approval_record
    app = _load_app_or_404(aid)
    body = require_body(request.get_json(silent=True))
    reason = get_str(body, "rejection_reason")

    # Reject is valid only in those four chain states
    rejectable = {"SUBMITTED", "SUPERVISOR_APPROVED", "DEPT_HEAD_APPROVED", "FINANCE_APPROVED"}
    if app["status"] not in rejectable:
        raise APIError(ERR_INVALID_STATE, "Application is not in a rejectable state", 409)

    # Actor must be the current chain step
    step = assert_current_approver(app, g.role, g.user_id)

    from_status = app["status"]
    app["status"] = "REJECTED"
    app["rejection_reason"] = reason
    bump(app)
    write_approval_record(
        subject_type="TRAVEL_APPLICATION",
        subject_id=app["id"],
        actor_id=g.user_id,
        actor_role=step,
        action="REJECT",
        comment=reason,
        from_status=from_status,
        to_status="REJECTED",
    )
    return success(ser_app(app))


# ===================== Cancel =====================
@bp.route("/travel-applications/<aid>/cancel", methods=["POST"])
@require_auth(["Applicant"])
def cancel_application(aid):
    app = _load_app_or_404(aid)
    _ownership_or_forbid(app)
    if app["applicant_id"] != g.user_id:
        raise APIError(ERR_NOT_CURRENT_APPROVER, "Acting user is not the applicant", 403)
    # DRAFT cancel: trivial
    # APPROVED cancel: only when no ACTIVE segments exist
    if app["status"] == "DRAFT":
        app["status"] = "CANCELLED"
        bump(app)
        return success(ser_app(app))
    if app["status"] == "APPROVED":
        if has_active_segments(app["id"]):
            raise APIError(ERR_INVALID_STATE,
                            "Cannot cancel an APPROVED application with active segments",
                            409)
        app["status"] = "CANCELLED"
        bump(app)
        return success(ser_app(app))
    raise APIError(ERR_INVALID_STATE,
                    f"Cannot cancel application in {app['status']}", 409)


# ===================== Complete =====================
@bp.route("/travel-applications/<aid>/complete", methods=["POST"])
@require_auth(["Applicant"])
def complete_application(aid):
    app = _load_app_or_404(aid)
    _ownership_or_forbid(app)
    if app["applicant_id"] != g.user_id:
        raise APIError(ERR_NOT_CURRENT_APPROVER, "Acting user is not the applicant", 403)
    if app["status"] != "BOOKING_LOCKED":
        raise APIError(ERR_INVALID_STATE, "Application is not in BOOKING_LOCKED", 409)
    # current time >= max(ACTIVE seg.end_at)
    max_end = None
    for seg in STORE.itinerary_segments.values():
        if seg["application_id"] != app["id"] or seg["status"] != "ACTIVE":
            continue
        e = parse_ts(seg["end_at"])
        if max_end is None or e > max_end:
            max_end = e
    if max_end is None:
        # No active segments — cannot complete (no trip has happened)
        raise APIError(ERR_INVALID_STATE, "No active segments to complete", 409)
    if CLOCK.now() < max_end:
        raise APIError(ERR_INVALID_STATE,
                        "Server clock has not reached the last segment's end_at", 409)
    app["status"] = "COMPLETED"
    bump(app)
    emit_external_sync(
        subject_type="TRAVEL_APPLICATION",
        subject_id=app["id"],
        target="BOOKING_PLATFORM",
        event="TRIP_COMPLETED",
        actor_id=g.user_id,
    )
    return success(ser_app(app))


# ===================== Itineraries =====================
def _validate_segment_time_bounds(app, seg_start, seg_end):
    ps = parse_ts(app["planned_start"])
    pe = parse_ts(app["planned_end"])
    if seg_start < ps or seg_end > pe:
        raise APIError(ERR_SEGMENT_OUTSIDE_TRIP,
                        "Segment time outside trip planned bounds", 422)
    if seg_end <= seg_start:
        raise APIError(ERR_VALIDATION, "end_at must be > start_at", 422)


def _check_transport_overlap(app_id, seg_type, seg_start, seg_end, exclude_id=None):
    """Two ACTIVE non-HOTEL segments under the same app must not strictly overlap.
    Equal endpoints are allowed."""
    if seg_type not in {"FLIGHT", "TRAIN", "CAR"}:
        return
    for s in STORE.itinerary_segments.values():
        if s["application_id"] != app_id or s["status"] != "ACTIVE":
            continue
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if s["segment_type"] not in {"FLIGHT", "TRAIN", "CAR"}:
            continue
        a = parse_ts(s["start_at"])
        b = parse_ts(s["end_at"])
        # Strict overlap: (a < seg_end) and (seg_start < b)
        if a < seg_end and seg_start < b:
            raise APIError(ERR_SEGMENT_TIME_OVERLAP,
                            "Transport segments overlap", 422)


def _check_hotel_overlap(app_id, seg_type, seg_start, seg_end, exclude_id=None):
    if seg_type != "HOTEL":
        return
    for s in STORE.itinerary_segments.values():
        if s["application_id"] != app_id or s["status"] != "ACTIVE":
            continue
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if s["segment_type"] != "HOTEL":
            continue
        a = parse_ts(s["start_at"])
        b = parse_ts(s["end_at"])
        # Half-open overlap: [a, b) overlaps [seg_start, seg_end) iff a < seg_end and seg_start < b
        if a < seg_end and seg_start < b:
            raise APIError(ERR_HOTEL_NIGHT_OVERLAP,
                            "Hotel night intervals overlap", 422)


def _check_budget_after_total(app, simulated_active_costs):
    """simulated_active_costs is a list of Decimals representing post-change active set."""
    from utils import round_money
    total = sum(simulated_active_costs, Decimal("0.00"))
    total = round_money(total)
    if total > round_money(app["estimated_budget"] * BUDGET_OVERRUN_FACTOR):
        raise APIError(ERR_BUDGET_OVERRUN,
                        "total_booked_cost exceeds budget overrun threshold", 422)


def _check_option_eligible(seg_type, applicant_level, option_code):
    eligible = STORE.eligible_options.get((seg_type, applicant_level), set())
    if option_code not in eligible:
        raise APIError(ERR_OPTION_NOT_ELIGIBLE,
                        f"Option {option_code} not eligible for ({seg_type}, {applicant_level})",
                        422)


@bp.route("/travel-applications/<aid>/itineraries", methods=["POST"])
@require_auth(["Applicant"])
def book_itinerary(aid):
    app = _load_app_or_404(aid)
    _ownership_or_forbid(app)
    if app["applicant_id"] != g.user_id:
        raise APIError(ERR_NOT_CURRENT_APPROVER, "Acting user is not the applicant", 403)
    # Application must be APPROVED or BOOKING_LOCKED
    if app["status"] not in {"APPROVED", "BOOKING_LOCKED"}:
        raise APIError(ERR_INVALID_STATE,
                        "Application must be APPROVED or BOOKING_LOCKED to book", 409)
    body = require_body(request.get_json(silent=True))
    seg_type = get_enum(body, "segment_type", SEGMENT_TYPES)
    option_code = get_str(body, "option_code")
    start_at = get_datetime(body, "start_at")
    end_at = get_datetime(body, "end_at")
    cost = get_money(body, "cost")

    applicant = STORE.employees.get(app["applicant_id"])
    applicant_level = applicant["employee_level"] if applicant else None

    # Priority-ordered validations (per §2.8 priorities 7..10, then 14)
    _check_option_eligible(seg_type, applicant_level, option_code)
    _validate_segment_time_bounds(app, start_at, end_at)
    _check_transport_overlap(app["id"], seg_type, start_at, end_at)
    _check_hotel_overlap(app["id"], seg_type, start_at, end_at)
    # Budget: simulated active set with this new cost added
    sim_costs = [s["cost"] for s in STORE.itinerary_segments.values()
                  if s["application_id"] == app["id"] and s["status"] == "ACTIVE"]
    sim_costs.append(cost)
    _check_budget_after_total(app, sim_costs)

    # Insert
    sid = new_uuid()
    now = CLOCK.now_iso()
    seg = {
        "id": sid,
        "application_id": app["id"],
        "segment_type": seg_type,
        "option_code": option_code,
        "start_at": format_ts(start_at),
        "end_at": format_ts(end_at),
        "cost": cost,
        "status": "ACTIVE",
        "prior_segment_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.itinerary_segments[sid] = seg
    # Recompute total + cascade application status
    recompute_total_booked_cost(app)
    if app["status"] == "APPROVED":
        app["status"] = "BOOKING_LOCKED"
    bump(app)
    return success(ser_seg(seg), status=201)


@bp.route("/travel-applications/<aid>/itineraries", methods=["GET"])
@require_auth(["Applicant", "Supervisor", "DeptHead", "Finance", "GeneralManager", "Admin"])
def list_itineraries(aid):
    app = _load_app_or_404(aid)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    rows = [s for s in STORE.itinerary_segments.values() if s["application_id"] == app["id"]]
    if status_f is not None:
        if status_f not in {"ACTIVE", "CHANGED", "CANCELLED"}:
            raise APIError(ERR_VALIDATION, "status filter invalid", 422)
        rows = [s for s in rows if s["status"] == status_f]
    rows.sort(key=lambda r: r["created_at"])
    page, pag = paginate(rows, limit, offset)
    return success([ser_seg(r) for r in page], pagination=pag)


def _load_segment_under_app(app, seg_id):
    seg = STORE.itinerary_segments.get(seg_id)
    if not seg or seg["application_id"] != app["id"]:
        raise APIError(ERR_NOT_FOUND, f"Itinerary segment {seg_id} not found", 404)
    return seg


@bp.route("/travel-applications/<aid>/itineraries/<seg_id>/change", methods=["POST"])
@require_auth(["Applicant"])
def change_itinerary(aid, seg_id):
    app = _load_app_or_404(aid)
    _ownership_or_forbid(app)
    if app["applicant_id"] != g.user_id:
        raise APIError(ERR_NOT_CURRENT_APPROVER, "Acting user is not the applicant", 403)
    seg = _load_segment_under_app(app, seg_id)
    if app["status"] != "BOOKING_LOCKED":
        raise APIError(ERR_INVALID_STATE, "Application is not in BOOKING_LOCKED", 409)
    if seg["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "Segment is not ACTIVE", 409)

    body = require_body(request.get_json(silent=True))
    new_type = get_enum(body, "segment_type", SEGMENT_TYPES)
    new_opt = get_str(body, "option_code")
    new_start = get_datetime(body, "start_at")
    new_end = get_datetime(body, "end_at")
    new_cost = get_money(body, "cost")

    applicant = STORE.employees.get(app["applicant_id"])
    applicant_level = applicant["employee_level"] if applicant else None

    # Re-evaluate against the post-change state (old seg is excluded as ACTIVE)
    _check_option_eligible(new_type, applicant_level, new_opt)
    _validate_segment_time_bounds(app, new_start, new_end)
    _check_transport_overlap(app["id"], new_type, new_start, new_end, exclude_id=seg["id"])
    _check_hotel_overlap(app["id"], new_type, new_start, new_end, exclude_id=seg["id"])
    sim_costs = [s["cost"] for s in STORE.itinerary_segments.values()
                  if s["application_id"] == app["id"] and s["status"] == "ACTIVE" and s["id"] != seg["id"]]
    sim_costs.append(new_cost)
    _check_budget_after_total(app, sim_costs)

    # Perform replacement
    seg["status"] = "CHANGED"
    bump(seg)
    new_id = new_uuid()
    now = CLOCK.now_iso()
    new_seg = {
        "id": new_id,
        "application_id": app["id"],
        "segment_type": new_type,
        "option_code": new_opt,
        "start_at": format_ts(new_start),
        "end_at": format_ts(new_end),
        "cost": new_cost,
        "status": "ACTIVE",
        "prior_segment_id": seg["id"],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.itinerary_segments[new_id] = new_seg
    recompute_total_booked_cost(app)
    bump(app)
    emit_external_sync(
        subject_type="TRAVEL_APPLICATION",
        subject_id=app["id"],
        target="BOOKING_PLATFORM",
        event="CHANGED",
        actor_id=g.user_id,
        extra_payload={"prior_segment_id": seg["id"], "new_segment_id": new_id},
    )
    return success(ser_seg(new_seg))


@bp.route("/travel-applications/<aid>/itineraries/<seg_id>/cancel", methods=["POST"])
@require_auth(["Applicant"])
def cancel_itinerary(aid, seg_id):
    app = _load_app_or_404(aid)
    _ownership_or_forbid(app)
    if app["applicant_id"] != g.user_id:
        raise APIError(ERR_NOT_CURRENT_APPROVER, "Acting user is not the applicant", 403)
    seg = _load_segment_under_app(app, seg_id)
    if app["status"] != "BOOKING_LOCKED":
        raise APIError(ERR_INVALID_STATE, "Application is not in BOOKING_LOCKED", 409)
    if seg["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "Segment is not ACTIVE", 409)
    seg["status"] = "CANCELLED"
    bump(seg)
    recompute_total_booked_cost(app)
    bump(app)
    emit_external_sync(
        subject_type="TRAVEL_APPLICATION",
        subject_id=app["id"],
        target="BOOKING_PLATFORM",
        event="CANCELLED",
        actor_id=g.user_id,
        extra_payload={"segment_id": seg["id"]},
    )
    return success(ser_seg(seg))


# ===================== Budget Projection =====================
@bp.route("/travel-applications/<aid>/budget-projection", methods=["GET"])
@require_auth(["Applicant", "Finance"])
def budget_projection(aid):
    from services.budget_projection import project as run_projection
    app = _load_app_or_404(aid)
    if g.role == "Applicant" and app["applicant_id"] != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Applicant is not the owner", 403)
    return success(run_projection(app))
