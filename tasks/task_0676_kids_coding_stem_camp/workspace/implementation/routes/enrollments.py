"""Enrollment routes & lifecycle (PRD §3.5), the most heavily guarded op.

Validation order (PRD §2.10, §3.5): auth -> role -> owner -> existence ->
state -> program_match -> age -> duplicate -> schedule_conflict ->
sibling_index -> membership_coverage -> seat_capacity -> OCC -> field_shape.
"""
from datetime import timedelta

from flask import Blueprint

import errors
from errors import err
from clock import clock
from db import db
from response import success
from serialize import out
from middleware import get_auth, require_role
from validators import get_body, parse_pagination, parse_iso, invalid
from services import lookup
from services.capacity import effective_capacity, derive_posture
from services.pricing import compute_drop_in
from services.member_service import compute_age_years
from routes.common import arg, paginate

bp = Blueprint("enrollments", __name__)

COVERAGES = {"DROP_IN", "MEMBERSHIP"}
NON_TERMINAL_ATTENDANCE = ("RESERVED", "CHECKED_IN")


def _non_terminal_enrollments_for_member(member_id, exclude_session=None):
    res = []
    for e in db.enrollments.values():
        if e["member_id"] != member_id:
            continue
        if e["attendance_status"] not in NON_TERMINAL_ATTENDANCE:
            continue
        if exclude_session is not None and e["session_id"] == exclude_session:
            continue
        res.append(e)
    return res


@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    user_id, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    body = get_body()

    # ---- existence (priority 4), left-to-right: session then member ----
    session_id = body.get("session_id")
    session = lookup.require_session(session_id)
    member_id = body.get("member_id")
    member = lookup.require_member(member_id)

    # ---- ownership (priority 3 logically, but evaluated after existence so we
    # can resolve the member's guardian). PRD lists priority 3 < 4; however the
    # owning guardian cannot be resolved without the member existing. Per PRD
    # §2.1 ownership is via member.guardian_id, so resolve then check. ----
    lookup.check_owner(role, user_id, lookup.member_guardian_id(member))

    guardian = db.guardians[member["guardian_id"]]

    # ---- state (priority 5): session must be in an enrollable posture ----
    if session["status"] not in ("OPEN", "RESTRICTED", "FULL"):
        raise err(errors.ERR_INVALID_STATE, "Session is not accepting enrollments.")

    # ---- coverage value (needed by later business rules) ----
    coverage = body.get("coverage")

    # ---- program match (priority 6) ----
    if member["program_id"] != session["program_id"]:
        raise err(errors.ERR_PROGRAM_MISMATCH, "Member is not on the session's program.")

    # ---- age (priority 7) ----
    program = db.programs[session["program_id"]]
    age = compute_age_years(member)
    if age < program["min_age"] or age > program["max_age"]:
        raise err(errors.ERR_AGE_OUT_OF_RANGE, "Member age is outside the program range.")

    # ---- duplicate (priority 8) ----
    for e in db.enrollments.values():
        if e["session_id"] == session_id and e["member_id"] == member_id \
                and e["attendance_status"] in NON_TERMINAL_ATTENDANCE:
            raise err(errors.ERR_DUPLICATE_ENROLLMENT, "Member already enrolled in this session.")

    # ---- schedule conflict (priority 9): half-open [starts_at, ends_at) ----
    s_start = parse_iso(session["starts_at"])
    s_end = parse_iso(session["ends_at"])
    for e in _non_terminal_enrollments_for_member(member_id, exclude_session=session_id):
        other = db.sessions.get(e["session_id"])
        if other is None:
            continue
        o_start = parse_iso(other["starts_at"])
        o_end = parse_iso(other["ends_at"])
        # Half-open overlap: o_start < s_end and s_start < o_end.
        if o_start < s_end and s_start < o_end:
            raise err(errors.ERR_MEMBER_SCHEDULE_CONFLICT, "Session overlaps an existing enrollment.")

    # ---- sibling_index (priority 14) ----
    guardian_id = member["guardian_id"]
    sibling_count = 0
    for e in db.enrollments.values():
        if e["session_id"] != session_id:
            continue
        if e["attendance_status"] not in NON_TERMINAL_ATTENDANCE:
            continue
        other_member = db.members.get(e["member_id"])
        if other_member is None:
            continue
        if other_member["guardian_id"] == guardian_id and e["member_id"] != member_id:
            sibling_count += 1
    expected_sibling_index = sibling_count + 1
    sibling_index = body.get("sibling_index", 1)
    if sibling_index is None:
        sibling_index = 1
    if not isinstance(sibling_index, int) or isinstance(sibling_index, bool) or sibling_index < 1:
        raise invalid("sibling_index must be an integer >= 1.")
    if sibling_index != expected_sibling_index:
        raise err(errors.ERR_INVALID_SIBLING_INDEX,
                  "sibling_index must equal %d." % expected_sibling_index)

    # ---- membership coverage (priority 15) ----
    covering_membership = None
    if coverage == "MEMBERSHIP":
        for m in db.memberships.values():
            if m["member_id"] != member_id:
                continue
            if m["status"] != "ACTIVE":
                continue
            if m["sessions_used_this_cycle"] < m["included_sessions_per_cycle"]:
                covering_membership = m
                break
        if covering_membership is None:
            raise err(errors.ERR_NO_INCLUDED_SESSIONS, "No active membership with an included seat.")

    # ---- seat capacity (priority 16) ----
    cap = effective_capacity(session)
    if session["confirmed_seat_count"] + 1 > cap:
        raise err(errors.ERR_SESSION_AT_CAPACITY, "Session is at capacity.")

    # ---- OCC (priority 18) ----
    expected_version = body.get("expected_session_version")
    if expected_version is None or isinstance(expected_version, bool) or not isinstance(expected_version, int):
        # Required, non-optional field; absence/shape is a field error (422).
        raise invalid("expected_session_version is required and must be an integer.")
    if expected_version != session["version"]:
        raise err(errors.ERR_STALE_SESSION_VERSION, "Session version is stale.")

    # ---- field shape (priority 19): coverage enum ----
    if coverage not in COVERAGES:
        raise invalid("coverage must be one of DROP_IN, MEMBERSHIP.")

    # ---- create + side effects ----
    enrollment_fields = {
        "session_id": session_id,
        "member_id": member_id,
        "coverage": coverage,
        "sibling_index": sibling_index,
        "price_cents": 0,
        "wallet_applied_cents": 0,
        "attendance_status": "RESERVED",
        "billing_status": "UNBILLED",
        "membership_id": None,
    }
    if coverage == "DROP_IN":
        price, wallet_applied = compute_drop_in(program, session, guardian, sibling_index)
        enrollment_fields["price_cents"] = price
        enrollment_fields["wallet_applied_cents"] = wallet_applied
        enrollment_fields["billing_status"] = "CHARGED"
        if wallet_applied:
            db.touch(guardian)  # wallet debited
    else:  # MEMBERSHIP
        enrollment_fields["billing_status"] = "COVERED"
        enrollment_fields["membership_id"] = covering_membership["id"]
        covering_membership["sessions_used_this_cycle"] += 1
        db.touch(covering_membership)

    rec = db.make(enrollment_fields)
    db.enrollments[rec["id"]] = rec

    # session: bump seat count, re-derive posture, bump version
    session["confirmed_seat_count"] += 1
    derive_posture(session)
    db.touch(session)

    return success(out(rec), status=201)


@bp.route("/enrollments/<rid>", methods=["GET"])
def get_enrollment(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_enrollment(rid)
    return success(out(rec))


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    limit, offset = parse_pagination()
    session_id = arg("session_id")
    member_id = arg("member_id")
    items = [e for e in db.enrollments.values()
             if (session_id is None or e["session_id"] == session_id)
             and (member_id is None or e["member_id"] == member_id)]
    return paginate(items, limit, offset)


@bp.route("/enrollments/<rid>/check-in", methods=["POST"])
def check_in(rid):
    _, role = get_auth()
    require_role(role, {"Instructor", "CenterAdmin"})
    e = lookup.require_enrollment(rid)
    session = db.sessions[e["session_id"]]
    if e["attendance_status"] != "RESERVED":
        raise err(errors.ERR_INVALID_STATE, "Enrollment is not RESERVED.")
    if session["status"] not in ("OPEN", "RESTRICTED", "FULL"):
        raise err(errors.ERR_INVALID_STATE, "Session is not in an active state.")
    starts_at = parse_iso(session["starts_at"])
    if clock.now() < starts_at:
        raise err(errors.ERR_INVALID_STATE, "Session has not started yet.")
    e["attendance_status"] = "CHECKED_IN"
    db.touch(e)
    # confirmed_seat_count unchanged (CHECKED_IN still counts); no posture change.
    return success(out(e))


@bp.route("/enrollments/<rid>/cancel", methods=["POST"])
def cancel_enrollment(rid):
    user_id, role = get_auth()
    require_role(role, {"Guardian", "CenterAdmin"})
    e = lookup.require_enrollment(rid)
    member = db.members[e["member_id"]]
    lookup.check_owner(role, user_id, member["guardian_id"])
    session = db.sessions[e["session_id"]]
    if session["status"] == "COMPLETED":
        raise err(errors.ERR_INVALID_STATE, "Session is COMPLETED.")
    if e["attendance_status"] not in ("RESERVED", "CHECKED_IN"):
        raise err(errors.ERR_INVALID_STATE, "Enrollment cannot be cancelled from its current state.")

    from_state = e["attendance_status"]
    e["attendance_status"] = "CANCELLED"

    if from_state == "CHECKED_IN":
        # No refund once checked in.
        e["billing_status"] = "FORFEITED"
    else:  # RESERVED
        if e["coverage"] == "DROP_IN":
            starts_at = parse_iso(session["starts_at"])
            delta = starts_at - clock.now()
            if delta >= timedelta(hours=24):
                e["billing_status"] = "REFUNDED"
                guardian = db.guardians[member["guardian_id"]]
                refund = e["price_cents"] + e["wallet_applied_cents"]
                if refund:
                    guardian["wallet_credit_cents"] += refund
                    db.touch(guardian)
            else:
                e["billing_status"] = "FORFEITED"
        else:  # MEMBERSHIP
            e["billing_status"] = "REFUNDED"
            mid = e.get("membership_id")
            membership = db.memberships.get(mid) if mid else None
            if membership is not None and membership["sessions_used_this_cycle"] > 0:
                membership["sessions_used_this_cycle"] -= 1
                db.touch(membership)

    db.touch(e)
    # seat freed; re-derive posture
    session["confirmed_seat_count"] = max(0, session["confirmed_seat_count"] - 1)
    derive_posture(session)
    db.touch(session)
    return success(out(e))
