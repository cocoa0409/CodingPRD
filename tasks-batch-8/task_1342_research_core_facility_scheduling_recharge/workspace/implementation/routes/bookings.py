"""Bookings (PRD §3.6-§3.7): request, approval with preemption, cancel,
reschedule, check-in, complete, no-show."""

from flask import Blueprint, request

from auth import (
    authenticate, require_roles, is_entity_role, auth_id, auth_role,
    check_create_ownership,
)
from errors import fail
from helpers import (
    Body, validate_body, is_int, dt_ok, parse_dt,
    check_training, confirmed_downtime_conflict, booking_blocks,
    effective_rate_set_for_fy, rate_line_for, provisional_estimate,
    grant_status, grant_ledger, grant_authorized, ser_booking,
    release_encumbrance, post_penalty_entry_if_any, open_batch,
    user_has_priority_award, fiscal_year_of,
    pct_of, whole_minutes, EARLY_CHECKIN_MINUTES,
)
from datetime import timedelta
from store import store, now
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch, fmt_ts

bp = Blueprint("bookings", __name__)


def get_booking_or_404(bid):
    b = store.bookings.get(bid)
    if b is None:
        fail("ERR_NOT_FOUND", "Booking not found")
    return b


def _check_overlap(instrument_id, start_at, end_at, incoming_priority, exclude_id=None):
    """Priority 16 — buffered half-open overlap vs APPROVED/IN_PROGRESS.
    A PRIORITY request may overlap STANDARD APPROVED victims."""
    inst = store.instruments.get(instrument_id)
    if inst is None:
        return
    for other in store.bookings.values():
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["instrument_id"] != instrument_id:
            continue
        if other["status"] not in ("APPROVED", "IN_PROGRESS"):
            continue
        if incoming_priority == "PRIORITY" and other["status"] == "APPROVED" and other["priority"] == "STANDARD":
            continue  # potential preemption victim
        if booking_blocks(other, start_at, end_at, inst):
            fail("ERR_BOOKING_OVERLAP", "Window overlaps another booking on this instrument")


def _check_grant_booking_rules(user, grant_id):
    """Priorities 31-34 for INTERNAL/EXTERNAL affiliation, grant state,
    window and authorization. `user` and `grant_id` assumed resolved."""
    if user["affiliation"] == "INTERNAL":
        if not grant_id:
            fail("ERR_GRANT_AFFILIATION_MISMATCH", "INTERNAL bookings require a grant_id")
    else:
        if grant_id:
            fail("ERR_GRANT_AFFILIATION_MISMATCH", "EXTERNAL bookings must not carry a grant_id")
        return None
    grant = store.grants.get(grant_id)
    if grant is None:
        return None  # existence already reported at priority 4 when applicable
    if grant_status(grant) != "ACTIVE":
        fail("ERR_GRANT_INACTIVE", "Grant is not ACTIVE")
    return grant


def _check_grant_window(grant, start_at):
    day = start_at.date()
    if day < grant["_start_date"] or day > grant["_end_date"]:
        fail("ERR_GRANT_WINDOW_VIOLATION", "Booking date outside the grant's chargeable window")


@bp.route("/bookings", methods=["POST"])
def create_booking():
    authenticate()
    require_roles("Researcher", "ExternalClient")
    body = Body(request.get_json(silent=True))
    # Priority 2 — entity-backed ownership (create only for self)
    check_create_ownership(body)
    user_id = body.get("user_id")
    instrument_id = body.get("instrument_id")
    grant_id = body.get("grant_id")
    # Priority 4 — body FK existence
    if user_id is not None and user_id not in store.users:
        fail("ERR_NOT_FOUND", "user_id does not reference an existing user")
    if instrument_id is not None and instrument_id not in store.instruments:
        fail("ERR_NOT_FOUND", "instrument_id does not reference an existing instrument")
    if grant_id is not None and grant_id not in store.grants:
        fail("ERR_NOT_FOUND", "grant_id does not reference an existing grant")
    user = store.users.get(user_id)
    inst = store.instruments.get(instrument_id)
    start_at = parse_dt(body.get("start_at"))
    end_at = parse_dt(body.get("end_at"))
    priority = body.get("priority", "STANDARD")
    # Priority 10 — instrument AVAILABLE
    if inst is not None and inst["status"] != "AVAILABLE":
        fail("ERR_INSTRUMENT_UNAVAILABLE", "Instrument is not AVAILABLE")
    # Priority 11 — user ACTIVE
    if user is not None and user["status"] != "ACTIVE":
        fail("ERR_USER_SUSPENDED", "Suspended users cannot book")
    # Priorities 12-13 — training
    if user is not None and inst is not None and end_at is not None:
        check_training(user_id, inst, end_at)
    # Priority 14 — strictly future start
    if start_at is not None and not (start_at > now()):
        fail("ERR_BOOKING_IN_PAST", "start_at must be strictly in the future")
    # Priority 15 — duration bounds
    if start_at is not None and end_at is not None and inst is not None:
        dur = whole_minutes(end_at - start_at)
        if dur < inst["min_booking_minutes"] or dur > inst["max_booking_minutes"]:
            fail("ERR_DURATION_OUT_OF_RANGE", "Duration outside the instrument's bounds")
    # Priority 16 — overlap
    if start_at is not None and end_at is not None and inst is not None and priority in ("STANDARD", "PRIORITY"):
        _check_overlap(instrument_id, start_at, end_at, priority)
    # Priority 17 — confirmed downtime conflict (closed-interval)
    if start_at is not None and end_at is not None and inst is not None:
        if confirmed_downtime_conflict(instrument_id, start_at, end_at):
            fail("ERR_DOWNTIME_CONFLICT", "Window intersects a CONFIRMED downtime event")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"user_id", "instrument_id", "grant_id", "start_at", "end_at", "priority"},
        required={"user_id", "instrument_id", "start_at", "end_at"},
        checkers={
            "user_id": lambda v: isinstance(v, str),
            "instrument_id": lambda v: isinstance(v, str),
            "grant_id": lambda v: isinstance(v, str),
            "start_at": dt_ok,
            "end_at": dt_ok,
            "priority": lambda v: v in ("STANDARD", "PRIORITY"),
        },
    )
    if not (end_at > start_at):
        fail("ERR_INVALID_REQUEST", "end_at must be after start_at")
    # Priority 24 — duplicate booking
    for b in store.bookings.values():
        if (b["user_id"] == user_id and b["instrument_id"] == instrument_id
                and b["_start_at"] == start_at
                and b["status"] in ("REQUESTED", "APPROVED", "IN_PROGRESS")):
            fail("ERR_DUPLICATE_BOOKING", "Duplicate booking for user+instrument+start_at")
    # Priority 27 — priority entitlement
    if priority == "PRIORITY":
        if user["affiliation"] == "EXTERNAL" or not user_has_priority_award(user_id):
            fail("ERR_PRIORITY_NOT_AVAILABLE", "No ACTIVE priority-conveying award")
    # Priorities 31-34 — grant affiliation / active / window / authorization
    grant = _check_grant_booking_rules(user, grant_id)
    if grant is not None:
        _check_grant_window(grant, start_at)
        if not grant_authorized(grant, user_id):
            fail("ERR_GRANT_NOT_AUTHORIZED", "Booker is neither the PI nor an authorized user")
    booking = new_entity({
        "user_id": user_id,
        "instrument_id": instrument_id,
        "grant_id": grant_id if user["affiliation"] == "INTERNAL" else None,
        "start_at": fmt_ts(start_at),
        "end_at": fmt_ts(end_at),
        "priority": priority,
        "status": "REQUESTED",
        "cancellation_reason": None,
        "penalty_cents": 0,
        "penalty_waived": False,
        "estimated_charge_cents": None,
        "encumbered_cents": 0,
        "rate_set_id": None,
        "applied_rate_cents_per_hour": None,
        "applied_increment_minutes": None,
        "applied_min_charge_minutes": None,
        "_start_at": start_at,
        "_end_at": end_at,
    })
    store.bookings[booking["id"]] = booking
    return ok_object(ser_booking(booking), status=201)


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient")
    limit, offset = parse_pagination(request.args)
    items = list(store.bookings.values())
    if is_entity_role():
        items = [b for b in items if b["user_id"] == auth_id()]
    else:
        user_id = request.args.get("user_id")
        if user_id is not None:
            items = [b for b in items if b["user_id"] == user_id]
    for param in ("instrument_id", "grant_id", "rate_set_id"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b.get(param) == v]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate(sort_default(items), limit, offset, ser_booking)


@bp.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient")
    b = get_booking_or_404(bid)
    if is_entity_role() and b["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Entity-backed callers may only access their own resources")
    return ok_object(ser_booking(b))


@bp.route("/bookings/<bid>/approve", methods=["POST"])
def approve_booking(bid):
    authenticate()
    require_roles("CoreStaff")
    b = get_booking_or_404(bid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    # Priority 6 — state legality + EFFECTIVE rate set gate
    if b["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Only a REQUESTED booking can be approved")
    fy = fiscal_year_of(b["_start_at"])
    rs = effective_rate_set_for_fy(fy)
    line = rate_line_for(rs, b["instrument_id"]) if rs else None
    if rs is None or line is None:
        fail("ERR_INVALID_STATE", "No EFFECTIVE rate set covers this booking's fiscal year")
    # Priority 10 — instrument AVAILABLE
    inst = store.instruments.get(b["instrument_id"])
    if inst is None or inst["status"] != "AVAILABLE":
        fail("ERR_INSTRUMENT_UNAVAILABLE", "Instrument is not AVAILABLE")
    # Priority 11 — user ACTIVE
    user = store.users.get(b["user_id"])
    if user is None or user["status"] != "ACTIVE":
        fail("ERR_USER_SUSPENDED", "The booking's user is suspended")
    # Priorities 12-13 — training
    check_training(b["user_id"], inst, b["_end_at"])
    # Priority 28 (PRIORITY preemption feasibility) — evaluated before the
    # overlap rule consumes the same set; see PRD §3.6 all-or-nothing rule.
    victims = []
    if b["priority"] == "PRIORITY":
        blockers = []
        for other in store.bookings.values():
            if other["id"] == bid or other["instrument_id"] != b["instrument_id"]:
                continue
            if not booking_blocks(other, b["_start_at"], b["_end_at"], inst):
                continue
            if other["status"] == "APPROVED" and other["priority"] == "STANDARD":
                victims.append(other)
            else:
                blockers.append(other)  # IN_PROGRESS or APPROVED PRIORITY
        if blockers:
            fail("ERR_PREEMPTION_BLOCKED", "Window cannot be cleared by preemption")
    else:
        # Priority 16 — overlap for STANDARD approvals
        _check_overlap(b["instrument_id"], b["_start_at"], b["_end_at"], "STANDARD")
    # Priority 17 — downtime conflict
    if confirmed_downtime_conflict(b["instrument_id"], b["_start_at"], b["_end_at"]):
        fail("ERR_DOWNTIME_CONFLICT", "Window intersects a CONFIRMED downtime event")
    # Pin the rate snapshot and compute the provisional estimate
    rate = (line["internal_rate_cents_per_hour"] if user["affiliation"] == "INTERNAL"
            else line["external_rate_cents_per_hour"])
    estimate = provisional_estimate(b["_start_at"], b["_end_at"], rate)
    # Priorities 32-33 + 35 — grant re-checks and fiscal capacity
    grant = None
    if user["affiliation"] == "INTERNAL":
        grant = store.grants.get(b["grant_id"])
        if grant is None:
            fail("ERR_NOT_FOUND", "grant_id does not reference an existing grant")
        if grant_status(grant) != "ACTIVE":
            fail("ERR_GRANT_INACTIVE", "Grant is not ACTIVE")
        _check_grant_window(grant, b["_start_at"])
        _, _, available = grant_ledger(grant)
        if available < estimate:
            fail("ERR_GRANT_BUDGET_EXCEEDED", "Grant budget_available_cents below the estimate")
    # ---- commit ----
    b["rate_set_id"] = rs["id"]
    b["applied_rate_cents_per_hour"] = rate
    b["applied_increment_minutes"] = line["billing_increment_minutes"]
    b["applied_min_charge_minutes"] = line["min_charge_minutes"]
    b["estimated_charge_cents"] = estimate
    b["encumbered_cents"] = estimate if user["affiliation"] == "INTERNAL" else 0
    b["status"] = "APPROVED"
    touch(b)
    # Preemption victims (all-or-nothing already verified above): rank
    # created_at DESC, tie-break start_at ASC (insertion order as final tie).
    victims.sort(key=lambda v: v["_seq"])
    victims.sort(key=lambda v: v["_start_at"])
    victims.sort(key=lambda v: v["created_at"], reverse=True)
    for victim in victims:
        victim["status"] = "PREEMPTED"
        victim["cancellation_reason"] = "PREEMPTION"
        victim["penalty_waived"] = True
        victim["penalty_cents"] = 0
        release_encumbrance(victim)
        touch(victim)
    return ok_object(ser_booking(b))


@bp.route("/bookings/<bid>/reject", methods=["POST"])
def reject_booking(bid):
    authenticate()
    require_roles("CoreStaff")
    b = get_booking_or_404(bid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            if k not in ("reason",):
                fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if b["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Only a REQUESTED booking can be rejected")
    b["status"] = "REJECTED"
    touch(b)
    return ok_object(ser_booking(b))


@bp.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    authenticate()
    require_roles("Researcher", "ExternalClient", "CoreStaff")
    b = get_booking_or_404(bid)
    if is_entity_role() and b["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Entity-backed callers may only cancel their own bookings")
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            if k not in ("reason",):
                fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    # Priority 6/41 — state + actor time-window legality
    if b["status"] not in ("REQUESTED", "APPROVED"):
        fail("ERR_INVALID_STATE", "Only REQUESTED or APPROVED bookings can be cancelled")
    if b["status"] == "APPROVED" and not (now() < b["_start_at"]):
        fail("ERR_INVALID_STATE", "APPROVED bookings may be cancelled only before start_at")
    reason = "STAFF" if auth_role() == "CoreStaff" else "USER"
    penalty = 0
    if b["status"] == "APPROVED":
        inst = store.instruments.get(b["instrument_id"])
        notice_minutes = whole_minutes(b["_start_at"] - now())
        free_minutes = inst["cancellation_free_notice_hours"] * 60
        if notice_minutes < free_minutes:
            penalty = pct_of(b["estimated_charge_cents"], inst["late_cancel_penalty_pct"])
    # Priority 7 — entry-posting actions require an OPEN batch (only when a
    # penalty entry would actually post)
    if penalty > 0 and open_batch() is None:
        fail("ERR_BATCH_NOT_OPEN", "No OPEN recharge batch for the penalty entry")
    was_approved = b["status"] == "APPROVED"
    b["status"] = "CANCELLED"
    b["cancellation_reason"] = reason
    b["penalty_waived"] = False
    b["penalty_cents"] = penalty
    if was_approved:
        release_encumbrance(b)
    touch(b)
    if penalty > 0:
        post_penalty_entry_if_any(b)
    return ok_object(ser_booking(b))


@bp.route("/bookings/<bid>/reschedule", methods=["POST"])
def reschedule_booking(bid):
    authenticate()
    require_roles("Researcher", "ExternalClient", "CoreStaff")
    b = get_booking_or_404(bid)
    if is_entity_role() and b["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Entity-backed callers may only reschedule their own bookings")
    body = Body(request.get_json(silent=True))
    # Priority 5 — OCC
    expected = body.get("expected_booking_version")
    if expected is not None and is_int(expected) and expected != b["version"]:
        fail("ERR_STALE_VERSION", "expected_booking_version does not match the booking's current version")
    # Priority 6 — only APPROVED bookings reschedule
    if b["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED booking can be rescheduled")
    inst = store.instruments.get(b["instrument_id"])
    start_at = parse_dt(body.get("start_at"))
    end_at = parse_dt(body.get("end_at"))
    # Priorities 12-13 — training currency re-validated
    if end_at is not None and inst is not None:
        check_training(b["user_id"], inst, end_at)
    # Priority 14 — future-dated
    if start_at is not None and not (start_at > now()):
        fail("ERR_BOOKING_IN_PAST", "start_at must be strictly in the future")
    # Priority 15 — duration bounds
    if start_at is not None and end_at is not None and inst is not None:
        dur = whole_minutes(end_at - start_at)
        if dur < inst["min_booking_minutes"] or dur > inst["max_booking_minutes"]:
            fail("ERR_DURATION_OUT_OF_RANGE", "Duration outside the instrument's bounds")
    # Priority 16 — overlap (excluding self)
    if start_at is not None and end_at is not None and inst is not None:
        _check_overlap(b["instrument_id"], start_at, end_at, b["priority"], exclude_id=bid)
    # Priority 17 — downtime conflict
    if start_at is not None and end_at is not None and inst is not None:
        if confirmed_downtime_conflict(b["instrument_id"], start_at, end_at):
            fail("ERR_DOWNTIME_CONFLICT", "Window intersects a CONFIRMED downtime event")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"expected_booking_version", "start_at", "end_at"},
        required={"expected_booking_version", "start_at", "end_at"},
        checkers={
            "expected_booking_version": is_int,
            "start_at": dt_ok,
            "end_at": dt_ok,
        },
    )
    if not (end_at > start_at):
        fail("ERR_INVALID_REQUEST", "end_at must be after start_at")
    # Commit: re-estimate against the pinned snapshot; adjust encumbrance.
    b["start_at"] = fmt_ts(start_at)
    b["end_at"] = fmt_ts(end_at)
    b["_start_at"] = start_at
    b["_end_at"] = end_at
    new_estimate = provisional_estimate(start_at, end_at, b["applied_rate_cents_per_hour"])
    b["estimated_charge_cents"] = new_estimate
    user = store.users.get(b["user_id"])
    if user is not None and user["affiliation"] == "INTERNAL":
        b["encumbered_cents"] = new_estimate
    touch(b)
    return ok_object(ser_booking(b))


@bp.route("/bookings/<bid>/check-in", methods=["POST"])
def check_in_booking(bid):
    authenticate()
    require_roles("CoreStaff")
    b = get_booking_or_404(bid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if b["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED booking can be checked in")
    earliest = b["_start_at"] - timedelta(minutes=EARLY_CHECKIN_MINUTES)
    if not (earliest <= now() <= b["_end_at"]):
        fail("ERR_INVALID_STATE", "Outside the check-in window")
    b["status"] = "IN_PROGRESS"
    touch(b)
    return ok_object(ser_booking(b))


@bp.route("/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    authenticate()
    require_roles("CoreStaff")
    b = get_booking_or_404(bid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if b["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "Only an IN_PROGRESS booking can be completed")
    b["status"] = "COMPLETED"
    release_encumbrance(b)
    touch(b)
    return ok_object(ser_booking(b))


@bp.route("/bookings/<bid>/no-show", methods=["POST"])
def no_show_booking(bid):
    authenticate()
    require_roles("CoreStaff")
    b = get_booking_or_404(bid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if b["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED booking can be marked no-show")
    if not (now() > b["_start_at"]):
        fail("ERR_INVALID_STATE", "No-show applies only after start_at has passed")
    inst = store.instruments.get(b["instrument_id"])
    penalty = pct_of(b["estimated_charge_cents"], inst["no_show_penalty_pct"])
    if penalty > 0 and open_batch() is None:
        fail("ERR_BATCH_NOT_OPEN", "No OPEN recharge batch for the penalty entry")
    b["status"] = "NO_SHOW"
    b["penalty_cents"] = penalty
    b["penalty_waived"] = False
    release_encumbrance(b)
    touch(b)
    if penalty > 0:
        post_penalty_entry_if_any(b)
    return ok_object(ser_booking(b))
