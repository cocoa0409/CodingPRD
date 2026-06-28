"""Crossfit Box API — Flask entry point.

In-memory only. The store starts empty on every boot; no entity is seeded.
start.sh re-invokes this before every per-test reboot, wiping all state.
"""
import os

from flask import Flask, request

from clock import clock
from db import db
from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER,
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_PLAN_SHAPE_INVALID,
    ERR_INVALID_STATE, ERR_MEMBERSHIP_NOT_OWNED, ERR_RESERVATION_SUSPENDED,
    ERR_FOUNDATIONS_NOT_COMPLETED, ERR_RESERVATION_WINDOW_CLOSED,
    ERR_DROP_IN_NOT_ALLOWED, ERR_DUPLICATE_RESERVATION,
    ERR_SESSION_TIME_CONFLICT, ERR_COACH_DOUBLE_BOOKED,
    ERR_NO_PUNCHES_REMAINING, ERR_ROSTER_FULL, ERR_COACH_NOT_CERTIFIED,
    ERR_STALE_SESSION_VERSION,
)
from middleware import get_identity, require_role
from response import success, list_success, error_body
from serialize import view, plain, member_view
import helpers as H
import services as S
from helpers import (
    parse_iso, parse_pagination, require_body,
    req_str, opt_str, req_int, opt_int, req_number, opt_bool, req_enum,
    RESERVATION_CUTOFF_MINUTES, COACH_TURNAROUND_MINUTES,
    NO_SHOW_SUSPEND_THRESHOLD,
)
from datetime import timedelta

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    body = error_body(e.error_id, e.message)
    return body, e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = error_body(ERR_NOT_FOUND, "Resource not found.")
    return body, 404


@app.errorhandler(405)
def handle_405(e):
    body = error_body(ERR_NOT_FOUND, "Method not allowed.")
    return body, 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = error_body(ERR_INVALID_REQUEST, "Unexpected error: %s" % str(e))
    return body, 422


# ---------------------------------------------------------------------------
# Lookup helpers (existence checks -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def must_get(store, _id):
    obj = store.get(_id)
    if obj is None:
        raise err(ERR_NOT_FOUND, "Referenced resource does not exist.")
    return obj


# ---------------------------------------------------------------------------
# Ownership helper (PRD §2.1)
# ---------------------------------------------------------------------------
def assert_member_owns(role, user_id, owner_member_id):
    """When an entity-backed Member acts on a resource not their own -> 403."""
    if role == "Member" and user_id != owner_member_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Member does not own this resource.")


# ===========================================================================
# MembershipPlan
# ===========================================================================
@app.route("/box/membership-plans", methods=["POST"])
def create_plan():
    role, uid = get_identity()
    require_role(role, ["BoxManager"])
    body = require_body()
    name = req_str(body, "name")
    plan_type = req_enum(body, "plan_type", {"UNLIMITED", "PUNCH"})
    monthly_fee = req_int(body, "monthly_fee_cents", minimum=0)
    commitment_months = opt_int(body, "commitment_months", default=0, minimum=0)
    etf = opt_int(body, "early_termination_fee_cents", default=0, minimum=0)
    requires_foundations = opt_bool(body, "requires_foundations", default=True)

    # Plan-shape consistency (ERR_PLAN_SHAPE_INVALID, within body-validation stage)
    punch_count = body.get("punch_count")
    if plan_type == "PUNCH":
        if punch_count is None:
            raise err(ERR_PLAN_SHAPE_INVALID, "PUNCH plan must supply punch_count.")
        if isinstance(punch_count, bool) or not isinstance(punch_count, int) or punch_count < 1:
            raise err(ERR_PLAN_SHAPE_INVALID, "punch_count must be an integer >= 1.")
    else:  # UNLIMITED
        if punch_count is not None:
            raise err(ERR_PLAN_SHAPE_INVALID, "UNLIMITED plan must omit punch_count.")
        punch_count = None

    plan = {
        "name": name,
        "plan_type": plan_type,
        "monthly_fee_cents": monthly_fee,
        "punch_count": punch_count,
        "commitment_months": commitment_months,
        "early_termination_fee_cents": etf,
        "requires_foundations": requires_foundations,
        "active": True,
    }
    db.stamp_create(plan)
    db.membership_plans[plan["id"]] = plan
    return success(plain(plan), status=201)


@app.route("/box/membership-plans", methods=["GET"])
def list_plans():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach", "Anonymous"])
    limit, offset = parse_pagination()
    items = list(db.membership_plans.values())
    if "active" in request.args:
        want = request.args.get("active").lower() == "true"
        items = [p for p in items if p["active"] == want]
    if "plan_type" in request.args:
        items = [p for p in items if p["plan_type"] == request.args.get("plan_type")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(p) for p in page], limit, offset, total)


@app.route("/box/membership-plans/<pid>", methods=["GET"])
def get_plan(pid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach", "Anonymous"])
    plan = must_get(db.membership_plans, pid)
    return success(plain(plan))


@app.route("/box/membership-plans/<pid>/archive", methods=["POST"])
def archive_plan(pid):
    role, uid = get_identity()
    require_role(role, ["BoxManager"])
    plan = must_get(db.membership_plans, pid)
    plan["active"] = False
    db.touch(plan)
    return success(plain(plan))


# ===========================================================================
# Member
# ===========================================================================
@app.route("/box/members/register", methods=["POST"])
def register_member():
    # Anonymous-reachable; no auth required (PRD §2.1).
    body = require_body()
    email = req_str(body, "email").lower()
    full_name = req_str(body, "full_name")
    home_box_member = opt_bool(body, "home_box_member", default=True)

    # Unique email (case-insensitive).
    for m in db.members.values():
        if m["email"] == email:
            raise err(ERR_INVALID_REQUEST, "Email already registered.")

    member = {
        "email": email,
        "full_name": full_name,
        "home_box_member": home_box_member,
        "no_show_strikes": 0,
    }
    db.stamp_create(member)
    db.members[member["id"]] = member
    return success(member_view(member), status=201)


@app.route("/box/members/<mid>", methods=["GET"])
def get_member(mid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    member = must_get(db.members, mid)
    return success(member_view(member))


@app.route("/box/members", methods=["GET"])
def list_members():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Coach"])
    limit, offset = parse_pagination()
    items = list(db.members.values())
    if "home_box_member" in request.args:
        want = request.args.get("home_box_member").lower() == "true"
        items = [m for m in items if m["home_box_member"] == want]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([member_view(m) for m in page], limit, offset, total)


@app.route("/box/members/<mid>/clear-strikes", methods=["POST"])
def clear_strikes(mid):
    role, uid = get_identity()
    require_role(role, ["BoxManager"])
    member = must_get(db.members, mid)
    member["no_show_strikes"] = 0
    db.touch(member)
    return success(member_view(member))


# ===========================================================================
# Membership
# ===========================================================================
@app.route("/box/memberships", methods=["POST"])
def create_membership():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member"])
    body = require_body()
    member_id = req_str(body, "member_id")
    plan_id = req_str(body, "plan_id")
    # Ownership: a Member may only create memberships for themselves.
    assert_member_owns(role, uid, member_id)
    # Existence (left-to-right): member then plan.
    must_get(db.members, member_id)
    must_get(db.membership_plans, plan_id)

    membership = {
        "member_id": member_id,
        "plan_id": plan_id,
        "status": "PENDING_PAYMENT",
        "punches_remaining": None,
        "foundations_completed": False,
        "contract_start_date": None,
        "commitment_end_date": None,
        "freeze_started_at": None,
        "total_frozen_days": 0,
        "cancellation_fee_cents": 0,
    }
    db.stamp_create(membership)
    db.memberships[membership["id"]] = membership
    return success(plain(membership), status=201)


@app.route("/box/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    membership = must_get(db.memberships, mid)
    return success(plain(membership))


@app.route("/box/memberships", methods=["GET"])
def list_memberships():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    limit, offset = parse_pagination()
    items = list(db.memberships.values())
    if "member_id" in request.args:
        items = [m for m in items if m["member_id"] == request.args.get("member_id")]
    if "plan_id" in request.args:
        items = [m for m in items if m["plan_id"] == request.args.get("plan_id")]
    if "status" in request.args:
        items = [m for m in items if m["status"] == request.args.get("status")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(m) for m in page], limit, offset, total)


@app.route("/box/memberships/<mid>/confirm-payment", methods=["POST"])
def confirm_payment(mid):
    role, uid = get_identity()
    require_role(role, ["BoxManager"])
    membership = must_get(db.memberships, mid)
    if membership["status"] != "PENDING_PAYMENT":
        raise err(ERR_INVALID_STATE, "Membership is not PENDING_PAYMENT.")
    plan = db.membership_plans[membership["plan_id"]]
    S.activate_membership(membership, plan)
    return success(plain(membership))


@app.route("/box/memberships/<mid>/freeze", methods=["POST"])
def freeze_membership(mid):
    role, uid = get_identity()
    require_role(role, ["Member"])
    membership = must_get(db.memberships, mid)
    assert_member_owns(role, uid, membership["member_id"])
    if membership["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Membership is not ACTIVE.")
    from response import iso_ms
    membership["freeze_started_at"] = iso_ms(clock.now())
    membership["status"] = "FROZEN"
    # CASCADE: cancel future RESERVED reservations -> free seats -> promote.
    S.cascade_cancel_future_reserved(membership)
    db.touch(membership)
    return success(plain(membership))


@app.route("/box/memberships/<mid>/unfreeze", methods=["POST"])
def unfreeze_membership_route(mid):
    role, uid = get_identity()
    require_role(role, ["Member"])
    membership = must_get(db.memberships, mid)
    assert_member_owns(role, uid, membership["member_id"])
    if membership["status"] != "FROZEN":
        raise err(ERR_INVALID_STATE, "Membership is not FROZEN.")
    S.unfreeze_membership(membership)
    return success(plain(membership))


@app.route("/box/memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    role, uid = get_identity()
    require_role(role, ["Member"])
    membership = must_get(db.memberships, mid)
    assert_member_owns(role, uid, membership["member_id"])
    if membership["status"] not in ("ACTIVE", "FROZEN"):
        raise err(ERR_INVALID_STATE, "Membership is not ACTIVE or FROZEN.")
    plan = db.membership_plans[membership["plan_id"]]
    fee = S.compute_cancellation_fee(membership, plan)
    membership["cancellation_fee_cents"] = fee
    if membership["status"] == "ACTIVE":
        membership["status"] = "CANCEL_PENDING"
        S.cascade_cancel_future_reserved(membership)
    else:  # FROZEN
        membership["freeze_started_at"] = None
        membership["status"] = "CANCEL_PENDING"
    db.touch(membership)
    return success(plain(membership))


# ===========================================================================
# Coach
# ===========================================================================
@app.route("/box/coaches", methods=["POST"])
def create_coach():
    role, uid = get_identity()
    require_role(role, ["BoxManager"])
    body = require_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email").lower()
    certified = opt_bool(body, "certified", default=True)
    for c in db.coaches.values():
        if c["email"] == email:
            raise err(ERR_INVALID_REQUEST, "Email already registered.")
    coach = {"full_name": full_name, "email": email, "certified": certified}
    db.stamp_create(coach)
    db.coaches[coach["id"]] = coach
    return success(plain(coach), status=201)


@app.route("/box/coaches/<cid>", methods=["GET"])
def get_coach(cid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    coach = must_get(db.coaches, cid)
    return success(plain(coach))


@app.route("/box/coaches", methods=["GET"])
def list_coaches():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    limit, offset = parse_pagination()
    items = list(db.coaches.values())
    if "certified" in request.args:
        want = request.args.get("certified").lower() == "true"
        items = [c for c in items if c["certified"] == want]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(c) for c in page], limit, offset, total)


# ===========================================================================
# ProgramTrack
# ===========================================================================
@app.route("/box/program-tracks", methods=["POST"])
def create_track():
    role, uid = get_identity()
    require_role(role, ["BoxManager"])
    body = require_body()
    name = req_str(body, "name")
    track_type = req_enum(body, "track_type", {"FOUNDATIONS", "REGULAR", "COMPETITION"})
    head_coach_id = req_str(body, "head_coach_id")
    must_get(db.coaches, head_coach_id)
    track = {"name": name, "track_type": track_type, "head_coach_id": head_coach_id}
    db.stamp_create(track)
    db.program_tracks[track["id"]] = track
    return success(plain(track), status=201)


@app.route("/box/program-tracks/<tid>", methods=["GET"])
def get_track(tid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    track = must_get(db.program_tracks, tid)
    return success(plain(track))


@app.route("/box/program-tracks", methods=["GET"])
def list_tracks():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    limit, offset = parse_pagination()
    items = list(db.program_tracks.values())
    if "track_type" in request.args:
        items = [t for t in items if t["track_type"] == request.args.get("track_type")]
    if "head_coach_id" in request.args:
        items = [t for t in items if t["head_coach_id"] == request.args.get("head_coach_id")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(t) for t in page], limit, offset, total)


@app.route("/box/program-tracks/<tid>/leaderboard", methods=["GET"])
def leaderboard(tid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    track = must_get(db.program_tracks, tid)
    benchmark_name = request.args.get("benchmark_name")
    if benchmark_name is None or benchmark_name == "":
        raise err(ERR_INVALID_REQUEST, "benchmark_name query parameter is required.")
    limit, offset = parse_pagination()

    # Eligibility (PRD §3.6): members who hold an ACTIVE membership on a plan
    # attached to a session of the requested track. A ClassSession carries no
    # direct plan FK; the plan-to-track link is realized through the memberships
    # that have reserved a session of the track. We therefore treat a member as
    # eligible when they hold an ACTIVE membership and that membership has at
    # least one reservation on a session of this track.
    track_session_ids = {s["id"] for s in db.sessions.values() if s["track_id"] == tid}
    eligible_members = set()
    for ms in db.memberships.values():
        if ms["status"] != "ACTIVE":
            continue
        for r in db.reservations.values():
            if r.get("membership_id") == ms["id"] and r["session_id"] in track_session_ids:
                eligible_members.add(ms["member_id"])
                break

    # Candidate verified results for the benchmark, for eligible members.
    candidates = [
        r for r in db.benchmark_results.values()
        if r["benchmark_name"] == benchmark_name
        and r["verified"] is True
        and r["member_id"] in eligible_members
    ]

    # One best row per member.
    best_by_member = {}
    for r in candidates:
        cur = best_by_member.get(r["member_id"])
        if cur is None:
            best_by_member[r["member_id"]] = r
            continue
        if r["metric_kind"] == "TIME_SECONDS":
            better = r["value"] < cur["value"]
        else:
            better = r["value"] > cur["value"]
        if better:
            best_by_member[r["member_id"]] = r
        elif r["value"] == cur["value"]:
            # tie on value -> keep the one with earlier recorded_at, then created.
            if (parse_iso(r["recorded_at"]), r["_seq"]) < (parse_iso(cur["recorded_at"]), cur["_seq"]):
                best_by_member[r["member_id"]] = r

    rows = list(best_by_member.values())

    def sort_key(r):
        rec = parse_iso(r["recorded_at"])
        if r["metric_kind"] == "TIME_SECONDS":
            return (r["value"], rec, r["_seq"])
        else:
            return (-r["value"], rec, r["_seq"])

    rows.sort(key=sort_key)
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_success([plain(r) for r in page], limit, offset, total)


# ===========================================================================
# ClassSession
# ===========================================================================
@app.route("/box/sessions", methods=["POST"])
def create_session():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Coach"])
    body = require_body()
    track_id = req_str(body, "track_id")
    coach_id = req_str(body, "coach_id")
    starts_at_raw = req_str(body, "starts_at")
    duration_minutes = req_int(body, "duration_minutes", minimum=1)
    capacity = req_int(body, "capacity", minimum=1)
    drop_in_fee = opt_int(body, "drop_in_fee_cents", default=0, minimum=0)
    # Existence (left to right): track then coach.
    must_get(db.program_tracks, track_id)
    must_get(db.coaches, coach_id)
    starts_at = parse_iso(starts_at_raw)

    # Coach double-booking (priority 15): busy interval = [starts_at,
    # starts_at + duration + 15min); touching endpoints allowed.
    new_start = starts_at
    new_end = starts_at + timedelta(minutes=duration_minutes + COACH_TURNAROUND_MINUTES)
    for other in db.sessions.values():
        if other["coach_id"] != coach_id:
            continue
        if other["status"] != "SCHEDULED":
            continue
        o_start = parse_iso(other["starts_at"])
        o_end = o_start + timedelta(minutes=other["duration_minutes"] + COACH_TURNAROUND_MINUTES)
        # overlap iff new_start < o_end and o_start < new_end (touching allowed)
        if new_start < o_end and o_start < new_end:
            raise err(ERR_COACH_DOUBLE_BOOKED, "Coach is already booked in this window.")

    session = {
        "track_id": track_id,
        "coach_id": coach_id,
        "starts_at": starts_at_raw if starts_at_raw.endswith("Z") else _norm_iso(starts_at),
        "duration_minutes": duration_minutes,
        "capacity": capacity,
        "drop_in_fee_cents": drop_in_fee,
        "status": "SCHEDULED",
        "seats_reserved": 0,
        "waitlist_count": 0,
    }
    db.stamp_create(session)
    db.sessions[session["id"]] = session
    return success(plain(session), status=201)


def _norm_iso(dt):
    from response import iso_ms
    return iso_ms(dt)


@app.route("/box/sessions/<sid>", methods=["GET"])
def get_session(sid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    session = must_get(db.sessions, sid)
    return success(plain(session))


@app.route("/box/sessions", methods=["GET"])
def list_sessions():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    limit, offset = parse_pagination()
    items = list(db.sessions.values())
    if "track_id" in request.args:
        items = [s for s in items if s["track_id"] == request.args.get("track_id")]
    if "coach_id" in request.args:
        items = [s for s in items if s["coach_id"] == request.args.get("coach_id")]
    if "status" in request.args:
        items = [s for s in items if s["status"] == request.args.get("status")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(s) for s in page], limit, offset, total)


@app.route("/box/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Coach"])
    session = must_get(db.sessions, sid)
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED.")
    # Cascade: every RESERVED -> CANCELLED with full refund/punch-restore;
    # every WAITLISTED -> CANCELLED. Then seats_reserved=waitlist_count=0.
    affected = [r for r in db.reservations.values() if r["session_id"] == sid]
    affected.sort(key=lambda r: r["_seq"])
    for r in affected:
        if r["status"] == "RESERVED":
            r["status"] = "CANCELLED"
            r["waitlist_position"] = None
            if r.get("punch_consumed"):
                membership = db.memberships.get(r.get("membership_id"))
                if membership is not None and membership.get("punches_remaining") is not None:
                    membership["punches_remaining"] += 1
                    db.touch(membership)
                r["punch_consumed"] = False
            if r.get("drop_in_fee_charged_cents"):
                r["drop_in_fee_charged_cents"] = 0
            db.touch(r)
        elif r["status"] == "WAITLISTED":
            r["status"] = "CANCELLED"
            r["waitlist_position"] = None
            db.touch(r)
    session["status"] = "CANCELLED"
    session["seats_reserved"] = 0
    session["waitlist_count"] = 0
    db.touch(session)
    return success(plain(session))


@app.route("/box/sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Coach"])
    session = must_get(db.sessions, sid)
    body = request.get_json(silent=True) or {}
    attendance = body.get("attendance", {})
    if not isinstance(attendance, dict):
        raise err(ERR_INVALID_REQUEST, "attendance must be an object.")
    # State: SCHEDULED and now >= starts_at.
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED.")
    if clock.now() < parse_iso(session["starts_at"]):
        raise err(ERR_INVALID_STATE, "Session has not started yet.")

    reservations = [r for r in db.reservations.values() if r["session_id"] == sid]
    reservations.sort(key=lambda r: r["_seq"])
    for r in reservations:
        if r["status"] == "RESERVED":
            marked = attendance.get(r["id"])
            # Interpret marking: truthy "attended" / "ATTENDED" / True => attended,
            # otherwise (including unmarked) => no-show.
            attended = _is_attended_mark(marked)
            if attended:
                r["status"] = "ATTENDED"
                db.touch(r)
            else:
                r["status"] = "NO_SHOW"
                db.touch(r)
                member = db.members.get(r["member_id"])
                if member is not None:
                    member["no_show_strikes"] += 1
                    db.touch(member)
        elif r["status"] == "WAITLISTED":
            r["status"] = "CANCELLED"
            r["waitlist_position"] = None
            db.touch(r)
    session["status"] = "COMPLETED"
    # seats_reserved/waitlist_count reflect terminal reservations now; recompute.
    session["seats_reserved"] = sum(
        1 for r in db.reservations.values()
        if r["session_id"] == sid and r["status"] == "RESERVED"
    )
    session["waitlist_count"] = sum(
        1 for r in db.reservations.values()
        if r["session_id"] == sid and r["status"] == "WAITLISTED"
    )
    db.touch(session)
    return success(plain(session))


def _is_attended_mark(marked):
    if marked is True:
        return True
    if isinstance(marked, str) and marked.upper() in ("ATTENDED", "ATTEND", "PRESENT", "TRUE"):
        return True
    return False


# ===========================================================================
# Reservation
# ===========================================================================
@app.route("/box/reservations", methods=["POST"])
def create_reservation():
    role, uid = get_identity()
    require_role(role, ["Member"])
    body = require_body()
    # Body shape (priority 5): required fields/types/enums.
    session_id = req_str(body, "session_id")
    member_id = req_str(body, "member_id")
    reservation_kind = req_enum(body, "reservation_kind", {"MEMBERSHIP", "DROP_IN"})
    expected_session_version = req_int(body, "expected_session_version")
    membership_id = body.get("membership_id")

    # Ownership (priority 3): Member acts on own reservation (member_id == uid).
    assert_member_owns(role, uid, member_id)

    # Existence (priority 4), left-to-right: session, member, membership (if any).
    session = must_get(db.sessions, session_id)
    member = must_get(db.members, member_id)
    if reservation_kind == "MEMBERSHIP":
        if membership_id is None or not isinstance(membership_id, str) or membership_id == "":
            raise err(ERR_PLAN_SHAPE_INVALID, "MEMBERSHIP reservation must supply membership_id.")
        membership = must_get(db.memberships, membership_id)
    else:  # DROP_IN
        if membership_id is not None:
            raise err(ERR_PLAN_SHAPE_INVALID, "DROP_IN reservation must omit membership_id.")
        membership = None

    # Plan-shape (priority 6) already covered by the membership_id pairing above.

    # No explicit state-transition precondition fails before business rules here;
    # business rules (priority 8..19):

    # 8: membership ownership of the reservation.
    if membership is not None and membership["member_id"] != member_id:
        raise err(ERR_MEMBERSHIP_NOT_OWNED, "Membership does not belong to the reserving member.")

    # 9: reservation suspension.
    if member["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD:
        raise err(ERR_RESERVATION_SUSPENDED, "Member is reservation-suspended.")

    track = db.program_tracks.get(session["track_id"])
    plan = db.membership_plans.get(membership["plan_id"]) if membership is not None else None

    # 10: foundations prerequisite.
    if track is not None and track["track_type"] == "REGULAR" and membership is not None:
        if plan is not None and plan["requires_foundations"] and not membership["foundations_completed"]:
            raise err(ERR_FOUNDATIONS_NOT_COMPLETED, "Foundations prerequisite not completed.")

    # 11: reservation window. SCHEDULED and now <= starts_at - 60min.
    if session["status"] != "SCHEDULED":
        raise err(ERR_RESERVATION_WINDOW_CLOSED, "Session is not open for reservations.")
    cutoff = parse_iso(session["starts_at"]) - timedelta(minutes=RESERVATION_CUTOFF_MINUTES)
    if clock.now() > cutoff:
        raise err(ERR_RESERVATION_WINDOW_CLOSED, "Reservation window is closed.")

    # 12: drop-in not allowed on COMPETITION track.
    if reservation_kind == "DROP_IN" and not member["home_box_member"]:
        if track is not None and track["track_type"] == "COMPETITION":
            raise err(ERR_DROP_IN_NOT_ALLOWED, "Drop-in athletes may not book COMPETITION sessions.")

    # 13: duplicate reservation (one non-terminal per session per member).
    for r in db.reservations.values():
        if r["session_id"] == session_id and r["member_id"] == member_id \
                and r["status"] in ("RESERVED", "WAITLISTED"):
            raise err(ERR_DUPLICATE_RESERVATION, "Member already holds a reservation on this session.")

    # 14: time conflict with another non-terminal reservation of same member.
    new_start = parse_iso(session["starts_at"])
    new_end = new_start + timedelta(minutes=session["duration_minutes"])
    for r in db.reservations.values():
        if r["member_id"] != member_id:
            continue
        if r["status"] not in ("RESERVED", "WAITLISTED"):
            continue
        other_session = db.sessions.get(r["session_id"])
        if other_session is None:
            continue
        o_start = parse_iso(other_session["starts_at"])
        o_end = o_start + timedelta(minutes=other_session["duration_minutes"])
        if new_start < o_end and o_start < new_end:  # touching allowed
            raise err(ERR_SESSION_TIME_CONFLICT, "Reservation time conflicts with another reservation.")

    # Determine whether this becomes a held seat or waitlist (commit-time occupancy).
    is_full = session["seats_reserved"] >= session["capacity"]

    # 16: punch availability — checked only when committing as RESERVED, not waitlisted.
    will_be_reserved = not is_full
    if will_be_reserved and membership is not None and plan is not None and plan["plan_type"] == "PUNCH":
        if membership.get("punches_remaining") is None or membership["punches_remaining"] < 1:
            raise err(ERR_NO_PUNCHES_REMAINING, "No punches remaining.")

    # 19: OCC stale-version check (last).
    if expected_session_version != session["version"]:
        raise err(ERR_STALE_SESSION_VERSION, "Session version is stale.")

    # Build reservation.
    reservation = {
        "session_id": session_id,
        "member_id": member_id,
        "membership_id": membership_id if reservation_kind == "MEMBERSHIP" else None,
        "reservation_kind": reservation_kind,
        "status": "RESERVED",
        "waitlist_position": None,
        "drop_in_fee_charged_cents": 0,
        "punch_consumed": False,
    }

    if is_full:
        # Created directly into WAITLISTED.
        reservation["status"] = "WAITLISTED"
        reservation["waitlist_position"] = session["waitlist_count"] + 1
        db.stamp_create(reservation)
        db.reservations[reservation["id"]] = reservation
        session["waitlist_count"] += 1
        # no punch consumed, no drop-in fee charged while waitlisted
    else:
        db.stamp_create(reservation)
        db.reservations[reservation["id"]] = reservation
        session["seats_reserved"] += 1
        if reservation_kind == "MEMBERSHIP" and plan is not None and plan["plan_type"] == "PUNCH":
            membership["punches_remaining"] -= 1
            reservation["punch_consumed"] = True
            db.touch(membership)
        elif reservation_kind == "DROP_IN":
            reservation["drop_in_fee_charged_cents"] = session["drop_in_fee_cents"]

    # Every successful reservation create increments the session's version.
    db.touch(session)
    return success(plain(reservation), status=201)


@app.route("/box/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    reservation = must_get(db.reservations, rid)
    return success(plain(reservation))


@app.route("/box/reservations", methods=["GET"])
def list_reservations():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    limit, offset = parse_pagination()
    items = list(db.reservations.values())
    if "session_id" in request.args:
        items = [r for r in items if r["session_id"] == request.args.get("session_id")]
    if "member_id" in request.args:
        items = [r for r in items if r["member_id"] == request.args.get("member_id")]
    if "membership_id" in request.args:
        items = [r for r in items if r.get("membership_id") == request.args.get("membership_id")]
    if "status" in request.args:
        items = [r for r in items if r["status"] == request.args.get("status")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(r) for r in page], limit, offset, total)


@app.route("/box/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    role, uid = get_identity()
    require_role(role, ["Member"])
    reservation = must_get(db.reservations, rid)
    assert_member_owns(role, uid, reservation["member_id"])
    session = db.sessions.get(reservation["session_id"])
    # State: reservation RESERVED or WAITLISTED and session SCHEDULED.
    if reservation["status"] not in ("RESERVED", "WAITLISTED"):
        raise err(ERR_INVALID_STATE, "Reservation is not RESERVED or WAITLISTED.")
    if session is None or session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED.")

    if reservation["status"] == "RESERVED":
        reservation["status"] = "CANCELLED"
        reservation["waitlist_position"] = None
        session["seats_reserved"] -= 1
        membership = db.memberships.get(reservation.get("membership_id"))
        # Refund per late-cancel window.
        S.refund_on_cancel(reservation, session, membership)
        db.touch(reservation)
        # Promote waitlist head if any remain.
        S.promote_waitlist_head(session)
        db.touch(session)
    else:  # WAITLISTED
        reservation["status"] = "CANCELLED"
        reservation["waitlist_position"] = None
        session["waitlist_count"] -= 1
        db.touch(reservation)
        # Renumber remaining waitlisted contiguous from 1.
        S._renumber_waitlist(session["id"])
        db.touch(session)
    return success(plain(reservation))


# ===========================================================================
# BenchmarkResult
# ===========================================================================
@app.route("/box/benchmark-results", methods=["POST"])
def create_benchmark():
    role, uid = get_identity()
    require_role(role, ["Member"])
    body = require_body()
    member_id = req_str(body, "member_id")
    benchmark_name = req_enum(body, "benchmark_name",
                              {"FRAN", "GRACE", "MURPH", "BACK_SQUAT_1RM", "DEADLIFT_1RM"})
    metric_kind = req_enum(body, "metric_kind", {"TIME_SECONDS", "LOAD_KG"})
    value = req_number(body, "value", gt=0)
    recorded_at_raw = req_str(body, "recorded_at")
    assert_member_owns(role, uid, member_id)
    must_get(db.members, member_id)
    recorded_at = parse_iso(recorded_at_raw)

    result = {
        "member_id": member_id,
        "benchmark_name": benchmark_name,
        "metric_kind": metric_kind,
        "value": value,
        "recorded_at": recorded_at_raw if recorded_at_raw.endswith("Z") else _norm_iso(recorded_at),
        "verified": False,
        "is_pr": False,
    }
    db.stamp_create(result)
    db.benchmark_results[result["id"]] = result
    return success(plain(result), status=201)


@app.route("/box/benchmark-results/<bid>", methods=["GET"])
def get_benchmark(bid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    result = must_get(db.benchmark_results, bid)
    return success(plain(result))


@app.route("/box/benchmark-results", methods=["GET"])
def list_benchmarks():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    limit, offset = parse_pagination()
    items = list(db.benchmark_results.values())
    if "member_id" in request.args:
        items = [r for r in items if r["member_id"] == request.args.get("member_id")]
    if "benchmark_name" in request.args:
        items = [r for r in items if r["benchmark_name"] == request.args.get("benchmark_name")]
    if "verified" in request.args:
        want = request.args.get("verified").lower() == "true"
        items = [r for r in items if r["verified"] == want]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(r) for r in page], limit, offset, total)


@app.route("/box/benchmark-results/<bid>/verify", methods=["POST"])
def verify_benchmark(bid):
    role, uid = get_identity()
    require_role(role, ["Coach"])
    result = must_get(db.benchmark_results, bid)
    coach = db.coaches.get(uid)
    if coach is None:
        raise err(ERR_NOT_FOUND, "Acting coach does not exist.")
    # Only a certified coach may verify (priority 18).
    if not coach["certified"]:
        raise err(ERR_COACH_NOT_CERTIFIED, "Coach is not certified.")
    result["verified"] = True
    result["is_pr"] = S.compute_is_pr(result)
    db.touch(result)
    return success(plain(result))


# ===========================================================================
# CompetitionTeam
# ===========================================================================
@app.route("/box/teams", methods=["POST"])
def create_team():
    role, uid = get_identity()
    require_role(role, ["Member"])
    body = require_body()
    name = req_str(body, "name")
    captain_member_id = req_str(body, "captain_member_id")
    max_roster_size = req_int(body, "max_roster_size", minimum=1)
    assert_member_owns(role, uid, captain_member_id)
    must_get(db.members, captain_member_id)
    # Name unique among teams that are not DISBANDED.
    for t in db.teams.values():
        if t["status"] != "DISBANDED" and t["name"] == name:
            raise err(ERR_INVALID_REQUEST, "Team name already in use.")

    team = {
        "name": name,
        "captain_member_id": captain_member_id,
        "max_roster_size": max_roster_size,
        "roster_size": 1,
        "status": "FORMING",
    }
    db.stamp_create(team)
    db.teams[team["id"]] = team
    # Captain enrolled as ACCEPTED team-member row.
    tm = {"team_id": team["id"], "member_id": captain_member_id, "status": "ACCEPTED"}
    db.stamp_create(tm)
    db.team_members[tm["id"]] = tm
    return success(plain(team), status=201)


@app.route("/box/teams/<tid>", methods=["GET"])
def get_team(tid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    team = must_get(db.teams, tid)
    return success(plain(team))


@app.route("/box/teams", methods=["GET"])
def list_teams():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    limit, offset = parse_pagination()
    items = list(db.teams.values())
    if "status" in request.args:
        items = [t for t in items if t["status"] == request.args.get("status")]
    if "captain_member_id" in request.args:
        items = [t for t in items if t["captain_member_id"] == request.args.get("captain_member_id")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(t) for t in page], limit, offset, total)


@app.route("/box/teams/<tid>/lock", methods=["POST"])
def lock_team(tid):
    role, uid = get_identity()
    require_role(role, ["Member"])
    team = must_get(db.teams, tid)
    body = require_body()
    # expected_team_version recorded for the operation.
    req_int(body, "expected_team_version")
    # Ownership: acting member must be captain.
    assert_member_owns(role, uid, team["captain_member_id"])
    if team["status"] != "FORMING":
        raise err(ERR_INVALID_STATE, "Team is not FORMING.")
    if team["roster_size"] < 1:
        raise err(ERR_INVALID_STATE, "Team roster is empty.")
    # Cascade: every still-INVITED slot -> DECLINED.
    for tm in db.team_members.values():
        if tm["team_id"] == tid and tm["status"] == "INVITED":
            tm["status"] = "DECLINED"
            db.touch(tm)
    team["status"] = "LOCKED"
    db.touch(team)
    return success(plain(team))


@app.route("/box/teams/<tid>/disband", methods=["POST"])
def disband_team(tid):
    role, uid = get_identity()
    require_role(role, ["Member"])
    team = must_get(db.teams, tid)
    body = require_body()
    req_int(body, "expected_team_version")
    assert_member_owns(role, uid, team["captain_member_id"])
    if team["status"] != "FORMING":
        raise err(ERR_INVALID_STATE, "Team is not FORMING.")
    for tm in db.team_members.values():
        if tm["team_id"] == tid and tm["status"] in ("ACCEPTED", "INVITED"):
            tm["status"] = "REMOVED"
            db.touch(tm)
    team["status"] = "DISBANDED"
    team["roster_size"] = 0
    db.touch(team)
    return success(plain(team))


# ===========================================================================
# TeamMember
# ===========================================================================
@app.route("/box/team-members", methods=["POST"])
def invite_team_member():
    role, uid = get_identity()
    require_role(role, ["Member"])
    body = require_body()
    team_id = req_str(body, "team_id")
    member_id = req_str(body, "member_id")
    # Existence: team then member.
    team = must_get(db.teams, team_id)
    must_get(db.members, member_id)
    # Captain-only invitation (acting member must be captain).
    assert_member_owns(role, uid, team["captain_member_id"])
    tm = {"team_id": team_id, "member_id": member_id, "status": "INVITED"}
    db.stamp_create(tm)
    db.team_members[tm["id"]] = tm
    return success(plain(tm), status=201)


@app.route("/box/team-members/<tmid>", methods=["GET"])
def get_team_member(tmid):
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    tm = must_get(db.team_members, tmid)
    return success(plain(tm))


@app.route("/box/team-members", methods=["GET"])
def list_team_members():
    role, uid = get_identity()
    require_role(role, ["BoxManager", "Member", "Coach"])
    limit, offset = parse_pagination()
    items = list(db.team_members.values())
    if "team_id" in request.args:
        items = [t for t in items if t["team_id"] == request.args.get("team_id")]
    if "member_id" in request.args:
        items = [t for t in items if t["member_id"] == request.args.get("member_id")]
    if "status" in request.args:
        items = [t for t in items if t["status"] == request.args.get("status")]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([plain(t) for t in page], limit, offset, total)


@app.route("/box/team-members/<tmid>/accept", methods=["POST"])
def accept_team_member(tmid):
    role, uid = get_identity()
    require_role(role, ["Member"])
    tm = must_get(db.team_members, tmid)
    # Ownership: acting member is the slot's own member_id.
    assert_member_owns(role, uid, tm["member_id"])
    team = db.teams.get(tm["team_id"])
    if tm["status"] != "INVITED":
        raise err(ERR_INVALID_STATE, "Slot is not INVITED.")
    if team is None or team["status"] != "FORMING":
        raise err(ERR_INVALID_STATE, "Team is not FORMING.")
    # Roster full guard (priority 17).
    if team["roster_size"] >= team["max_roster_size"]:
        raise err(ERR_ROSTER_FULL, "Team roster is full.")
    tm["status"] = "ACCEPTED"
    db.touch(tm)
    team["roster_size"] += 1
    db.touch(team)
    return success(plain(tm))


@app.route("/box/team-members/<tmid>/decline", methods=["POST"])
def decline_team_member(tmid):
    role, uid = get_identity()
    require_role(role, ["Member"])
    tm = must_get(db.team_members, tmid)
    assert_member_owns(role, uid, tm["member_id"])
    if tm["status"] != "INVITED":
        raise err(ERR_INVALID_STATE, "Slot is not INVITED.")
    tm["status"] = "DECLINED"
    db.touch(tm)
    return success(plain(tm))


# ===========================================================================
# Test-driving / batch endpoints
# ===========================================================================
@app.route("/box/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, uid = get_identity()
    require_role(role, ["BoxManager"])
    body = require_body()
    to_iso = req_str(body, "to_iso8601")
    clock.set(parse_iso(to_iso))
    return success({})


@app.route("/box/_membership/complete-foundations", methods=["POST"])
def complete_foundations():
    role, uid = get_identity()
    require_role(role, ["Coach"])
    body = require_body()
    membership_id = req_str(body, "membership_id")
    membership = must_get(db.memberships, membership_id)
    membership["foundations_completed"] = True
    db.touch(membership)
    return success(plain(membership))


@app.route("/box/_billing/run-cycle-close", methods=["POST"])
def run_cycle_close():
    role, uid = get_identity()
    require_role(role, ["BoxManager"])
    total = 0
    finalized = []
    # Pass 1: CANCEL_PENDING ordered by created_at ASC.
    pending = [m for m in db.memberships.values() if m["status"] == "CANCEL_PENDING"]
    pending.sort(key=lambda m: (m["created_at"], m["_seq"]))
    for m in pending:
        total += m["cancellation_fee_cents"]
        plan = db.membership_plans.get(m["plan_id"])
        if plan is not None and plan["plan_type"] == "PUNCH":
            m["punches_remaining"] = 0
        m["status"] = "CANCELLED"
        db.touch(m)
        finalized.append(m["id"])
    # Pass 2: ACTIVE ordered by created_at ASC -> add monthly fee, stay ACTIVE.
    active = [m for m in db.memberships.values() if m["status"] == "ACTIVE"]
    active.sort(key=lambda m: (m["created_at"], m["_seq"]))
    for m in active:
        plan = db.membership_plans.get(m["plan_id"])
        if plan is not None:
            total += plan["monthly_fee_cents"]
    return success({"total_charged_cents": total, "finalized_membership_ids": finalized})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
