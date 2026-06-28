"""RunnerTrip & RunnerLeg endpoints (PRD §3.4; scaffold §1.5)."""

from flask import Blueprint, g, request

import errors
import repo
from clock import clock, parse_iso8601
from db import db
from helpers import (get_json_body, require_str, require_int,
                     parse_pagination, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import runner_trip_out, runner_leg_out

bp = Blueprint("runner_trips", __name__)

NON_TERMINAL_TRIP_STATES = {"PLANNED", "DISPATCHED", "RETURNED"}

# Priority order key for sequence_index assignment: EXPEDITE before STANDARD.
_PRIORITY_RANK = {"EXPEDITE": 0, "STANDARD": 1}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test. Adjacency does not overlap."""
    return a_start < b_end and b_start < a_end


@bp.route("/dmv/runner-trips", methods=["POST"])
@require_roles("RunnerDispatcher")
def create_runner_trip():
    body = get_json_body()
    dmv_office_code = require_str(body, "dmv_office_code")
    capacity = require_int(body, "capacity")
    window_start_raw = require_str(body, "window_start_at")
    window_end_raw = require_str(body, "window_end_at")

    try:
        ws = parse_iso8601(window_start_raw)
        we = parse_iso8601(window_end_raw)
    except (ValueError, TypeError):
        raise errors.invalid_request("window_start_at/window_end_at must be ISO 8601")

    # capacity >= 1 is a typed constraint -> ERR_VALIDATION.
    if capacity < 1:
        raise errors.validation("capacity must be >= 1")

    # window_end_at must be strictly after window_start_at.
    if not (we > ws):
        raise errors.validation("window_end_at must be strictly after window_start_at")

    # Window overlap (priority 10): reject if half-open window overlaps any
    # existing non-terminal trip to the SAME dmv_office_code.
    for t in db.runner_trips.values():
        if t["dmv_office_code"] != dmv_office_code:
            continue
        if t["trip_status"] not in NON_TERMINAL_TRIP_STATES:
            continue
        ets = parse_iso8601(t["window_start_at"])
        ete = parse_iso8601(t["window_end_at"])
        if _intervals_overlap(ws, we, ets, ete):
            raise errors.trip_window_overlap("trip window overlaps an existing trip")

    rec = repo.make_runner_trip(dmv_office_code, capacity, window_start_raw,
                                window_end_raw)
    return success(runner_trip_out(rec), 201)


@bp.route("/dmv/runner-trips/<tid>", methods=["GET"])
@require_roles("PlatformAdmin", "RunnerDispatcher")
def get_runner_trip(tid):
    t = db.runner_trips.get(tid)
    if t is None:
        raise errors.not_found("runner trip not found")
    return success(runner_trip_out(t), 200)


@bp.route("/dmv/runner-trips/<tid>/legs", methods=["POST"])
@require_roles("RunnerDispatcher")
def attach_leg(tid):
    body = get_json_body()
    trip = db.runner_trips.get(tid)
    if trip is None:
        raise errors.not_found("runner trip not found")

    submission_id = require_str(body, "submission_id")
    submission = db.submissions.get(submission_id)
    if submission is None:
        raise errors.not_found("submission not found")

    # State eligibility (priority 5): submission QUEUED and trip PLANNED.
    if submission["submission_status"] != "QUEUED":
        raise errors.invalid_state("submission must be QUEUED to attach")
    if trip["trip_status"] != "PLANNED":
        raise errors.invalid_state("trip must be PLANNED to attach a leg")

    # SLA window (priority 11): expedited submissions attachable only while
    # clock_now strictly before sla_deadline_at.
    if submission["priority_class"] == "EXPEDITE":
        deadline_raw = submission["sla_deadline_at"]
        if deadline_raw is not None:
            deadline = parse_iso8601(deadline_raw)
            if not (clock.now() < deadline):
                raise errors.sla_expired("EXPEDITE SLA window has expired")

    # Capacity (priority 12): assigned_leg_count < capacity.
    if trip["assigned_leg_count"] >= trip["capacity"]:
        raise errors.trip_at_capacity("trip is at capacity")

    # OCC (priority 17): expected_runnertrip_version required and must match.
    expected = body.get("expected_runnertrip_version")
    if expected is None:
        raise errors.invalid_request("expected_runnertrip_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_runnertrip_version must be an integer")
    if expected != trip["version"]:
        raise errors.stale_version("expected_runnertrip_version is stale")

    # sequence_index by queue priority then created_at ASC at attach time.
    existing_legs = [l for l in db.runner_legs.values() if l["trip_id"] == tid]
    seq = len(existing_legs)

    leg = repo.make_runner_leg(tid, submission_id, seq)

    # Reassign sequence_index across all legs of this trip by priority then created_at.
    _resequence_trip_legs(tid)

    submission["submission_status"] = "ASSIGNED"
    submission["leg_id"] = leg["id"]
    repo.bump(submission)

    trip["assigned_leg_count"] = trip["assigned_leg_count"] + 1
    repo.bump(trip)

    return success(runner_leg_out(leg), 201)


def _resequence_trip_legs(trip_id):
    """Assign sequence_index by submission priority then leg created_at ASC."""
    legs = [l for l in db.runner_legs.values() if l["trip_id"] == trip_id]

    def sort_key(leg):
        sub = db.submissions.get(leg["submission_id"])
        rank = _PRIORITY_RANK.get(sub["priority_class"], 1) if sub else 1
        return (rank, leg.get("created_at", ""), leg.get("_seq", 0))

    for idx, leg in enumerate(sorted(legs, key=sort_key)):
        leg["sequence_index"] = idx


@bp.route("/dmv/runner-trips/<tid>/legs", methods=["GET"])
@require_roles("PlatformAdmin", "RunnerDispatcher")
def list_trip_legs(tid):
    trip = db.runner_trips.get(tid)
    if trip is None:
        raise errors.not_found("runner trip not found")
    limit, offset = parse_pagination()
    legs = [l for l in db.runner_legs.values() if l["trip_id"] == tid]
    # Ordered by sequence_index.
    legs.sort(key=lambda l: l["sequence_index"])
    total = len(legs)
    page = legs[offset:offset + limit]
    return list_success([runner_leg_out(l) for l in page], limit, offset, total)


@bp.route("/dmv/runner-trips/<tid>/dispatch", methods=["POST"])
@require_roles("RunnerDispatcher")
def dispatch_trip(tid):
    trip = db.runner_trips.get(tid)
    if trip is None:
        raise errors.not_found("runner trip not found")
    if trip["trip_status"] != "PLANNED":
        raise errors.invalid_state("trip must be PLANNED to dispatch")
    if trip["assigned_leg_count"] < 1:
        raise errors.invalid_state("trip must carry at least one leg to dispatch")

    # Fork: every attached leg advances to FILED.
    for leg in db.runner_legs.values():
        if leg["trip_id"] == tid and leg["leg_status"] == "ATTACHED":
            leg["leg_status"] = "FILED"
            repo.bump(leg)
            sub = db.submissions.get(leg["submission_id"])
            # Submission already ASSIGNED at attach; idempotent confirm.
            if sub is not None and sub["submission_status"] == "QUEUED":
                sub["submission_status"] = "ASSIGNED"
                repo.bump(sub)

    trip["trip_status"] = "DISPATCHED"
    repo.bump(trip)
    return success(runner_trip_out(trip), 200)


@bp.route("/dmv/runner-trips/<tid>/return", methods=["POST"])
@require_roles("RunnerDispatcher")
def return_trip(tid):
    trip = db.runner_trips.get(tid)
    if trip is None:
        raise errors.not_found("runner trip not found")
    if trip["trip_status"] != "DISPATCHED":
        raise errors.invalid_state("trip must be DISPATCHED to return")
    trip["trip_status"] = "RETURNED"
    repo.bump(trip)
    return success(runner_trip_out(trip), 200)


@bp.route("/dmv/runner-trips/<tid>/close", methods=["POST"])
@require_roles("RunnerDispatcher")
def close_trip(tid):
    trip = db.runner_trips.get(tid)
    if trip is None:
        raise errors.not_found("runner trip not found")
    if trip["trip_status"] != "RETURNED":
        raise errors.invalid_state("trip must be RETURNED to close")
    # Join: every attached leg must be RESOLVED.
    legs = [l for l in db.runner_legs.values() if l["trip_id"] == tid]
    if any(l["leg_status"] != "RESOLVED" for l in legs):
        raise errors.invalid_state("all legs must be RESOLVED to close the trip")
    trip["trip_status"] = "CLOSED"
    repo.bump(trip)
    return success(runner_trip_out(trip), 200)


# ---- RunnerLeg reads ----

@bp.route("/dmv/runner-legs", methods=["GET"])
@require_roles("PlatformAdmin", "RunnerDispatcher")
def list_runner_legs():
    limit, offset = parse_pagination()
    trip_id = request.args.get("trip_id")
    submission_id = request.args.get("submission_id")
    leg_status = request.args.get("leg_status")
    items = list(db.runner_legs.values())
    if trip_id is not None:
        items = [l for l in items if l["trip_id"] == trip_id]
    if submission_id is not None:
        items = [l for l in items if l["submission_id"] == submission_id]
    if leg_status is not None:
        items = [l for l in items if l["leg_status"] == leg_status]
    page, total = paginate(items, limit, offset)
    return list_success([runner_leg_out(l) for l in page], limit, offset, total)


@bp.route("/dmv/runner-legs/<lid>", methods=["GET"])
@require_roles("PlatformAdmin", "RunnerDispatcher")
def get_runner_leg(lid):
    l = db.runner_legs.get(lid)
    if l is None:
        raise errors.not_found("runner leg not found")
    return success(runner_leg_out(l), 200)
