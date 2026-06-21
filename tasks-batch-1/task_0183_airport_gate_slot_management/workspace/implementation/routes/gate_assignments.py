"""GateAssignment routes: create (OCC-guarded) + at-gate lifecycle."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success, list_success
from services import occupancy

bp = Blueprint("gate_assignments", __name__)

READ_ROLES = {"OpsAdmin", "GateController", "RampAgent"}
STAND_TYPES = {"GATE", "REMOTE"}


@bp.route("/gate-assignments", methods=["POST"])
def create_assignment():
    _, role = authenticate()
    require_roles(role, {"GateController"})
    body = helpers.get_body()

    # ---- priority 3: existence (path none; body FKs left-to-right) ----
    # FK declaration order for this body: flight_id, then the stand id selected
    # by stand_type. We must validate flight_id existence (404) before body
    # well-formedness of other fields? Per §2.9 existence (3) precedes
    # well-formedness (4). But we need flight_id present to look it up. A
    # missing required field is well-formedness (400). The PRD orders existence
    # before well-formedness; however an absent flight_id cannot be checked for
    # existence. We treat: if flight_id is provided, check its existence first;
    # other malformed-body checks come after. This matches "FKs validated in
    # declaration order" while a truly missing FK is a 400.
    flight = None
    if body.get("flight_id") is not None:
        flight = db.flights.get(body["flight_id"])
        if flight is None:
            raise errors.not_found("Flight not found.")

    stand_type = body.get("stand_type")
    # The stand FK existence (gate_id / remote_stand_id) is checked after we
    # know the discriminator; but existence (priority 3) precedes body
    # well-formedness (priority 4). The chosen stand id, when present and
    # pointing nowhere, is a 404.
    gate = None
    remote = None
    if stand_type == "GATE" and body.get("gate_id") is not None:
        gate = db.gates.get(body["gate_id"])
        if gate is None:
            raise errors.not_found("Gate not found.")
    elif stand_type == "REMOTE" and body.get("remote_stand_id") is not None:
        remote = db.remote_stands.get(body["remote_stand_id"])
        if remote is None:
            raise errors.not_found("Remote stand not found.")

    # ---- priority 4: body well-formedness ----
    helpers.require_fields(body, ["flight_id", "stand_type", "start_utc", "end_utc"])
    helpers.check_enum(stand_type, STAND_TYPES, "stand_type")

    gate_id = body.get("gate_id")
    remote_stand_id = body.get("remote_stand_id")
    # discriminator must match exactly one of the two stand references
    if stand_type == "GATE":
        if gate_id is None or remote_stand_id is not None:
            raise errors.invalid_request(
                "stand_type=GATE requires gate_id set and remote_stand_id null.")
    else:  # REMOTE
        if remote_stand_id is None or gate_id is not None:
            raise errors.invalid_request(
                "stand_type=REMOTE requires remote_stand_id set and gate_id null.")

    start_dt, start_raw = helpers.parse_dt(body["start_utc"], "start_utc")
    end_dt, end_raw = helpers.parse_dt(body["end_utc"], "end_utc")
    if end_dt <= start_dt:
        raise errors.invalid_request("end_utc must be strictly later than start_utc.")

    # expected_gate_version, if present, must be an int (well-formedness).
    expected_version = None
    if body.get("expected_gate_version") is not None:
        expected_version = helpers.parse_int(body["expected_gate_version"], "expected_gate_version")

    # ---- priority 6: cross-state guard (stand ACTIVE) ----
    if stand_type == "GATE":
        if gate["status"] != "ACTIVE":
            raise errors.cross_state_blocked("Gate is not ACTIVE.")
    else:
        if remote["status"] != "ACTIVE":
            raise errors.cross_state_blocked("Remote stand is not ACTIVE.")

    # ---- priority 7: wingspan fit ----
    stand = gate if stand_type == "GATE" else remote
    if stand["max_wingspan_m"] < flight["aircraft_wingspan_m"]:
        raise errors.wingspan_exceeded()

    occupancy_minutes = helpers.whole_minutes(start_dt, end_dt)

    # ---- priority 8: gate window conflict (GATE only) ----
    if stand_type == "GATE":
        if occupancy.gate_window_conflicts(gate_id, start_dt, end_dt, gate["buffer_minutes"]):
            raise errors.gate_window_conflict()

    # ---- priority 11: remote stand capacity (REMOTE only) ----
    if stand_type == "REMOTE":
        if occupancy.remote_capacity_exceeded(remote_stand_id, start_dt, end_dt,
                                              remote["capacity"]):
            raise errors.remote_stand_full()

    # ---- priority 13: minimum turn time ----
    if occupancy_minutes < flight["min_turn_minutes"]:
        raise errors.turn_time_too_short()

    # ---- priority 15: OCC stale gate version (GATE only, when provided) ----
    if stand_type == "GATE" and expected_version is not None:
        if expected_version != gate["version"]:
            raise errors.stale_gate_version()

    # ---- all checks passed: create ----
    rec = {
        "id": db.new_id(),
        "flight_id": flight["id"],
        "stand_type": stand_type,
        "gate_id": gate_id if stand_type == "GATE" else None,
        "remote_stand_id": remote_stand_id if stand_type == "REMOTE" else None,
        "start_utc": start_raw,
        "end_utc": end_raw,
        "status": "PLANNED",
        "tow_target_stand_id": None,
        "occupancy_minutes": occupancy_minutes,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    db.stamp_create(rec)
    db.gate_assignments[rec["id"]] = rec

    # side effect: first assignment for the flight -> handling_status ASSIGNED
    if flight["handling_status"] == "UNASSIGNED":
        flight["handling_status"] = "ASSIGNED"
        db.touch(flight)

    # side effect: GATE create increments the target Gate.version by 1
    if stand_type == "GATE":
        db.touch(gate)  # bumps version + updated_at

    return success(helpers.serialize(rec), status=201)


@bp.route("/gate-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.gate_assignments.get(aid)
    if rec is None:
        raise errors.not_found("Gate assignment not found.")
    return success(helpers.serialize(rec), status=200)


@bp.route("/gate-assignments", methods=["GET"])
def list_assignments():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    flight_id = request.args.get("flight_id")
    gate_id = request.args.get("gate_id")
    remote_stand_id = request.args.get("remote_stand_id")
    status = request.args.get("status")
    recs = list(db.gate_assignments.values())
    if flight_id is not None:
        recs = [r for r in recs if r.get("flight_id") == flight_id]
    if gate_id is not None:
        recs = [r for r in recs if r.get("gate_id") == gate_id]
    if remote_stand_id is not None:
        recs = [r for r in recs if r.get("remote_stand_id") == remote_stand_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)


def _get_assignment_or_404(aid):
    rec = db.gate_assignments.get(aid)
    if rec is None:
        raise errors.not_found("Gate assignment not found.")
    return rec


@bp.route("/gate-assignments/<aid>/occupy", methods=["POST"])
def occupy(aid):
    _, role = authenticate()
    require_roles(role, {"RampAgent"})
    a = _get_assignment_or_404(aid)
    # state from-check (priority 5)
    if a["status"] != "PLANNED":
        raise errors.invalid_state("Assignment is not PLANNED.")
    flight = db.flights[a["flight_id"]]
    # cross-state guard (priority 6): flight schedule SCHEDULED/ACTIVE; stand ACTIVE
    if flight["schedule_status"] not in ("SCHEDULED", "ACTIVE"):
        raise errors.cross_state_blocked("Flight schedule is not SCHEDULED/ACTIVE.")
    if a["stand_type"] == "GATE":
        if db.gates[a["gate_id"]]["status"] != "ACTIVE":
            raise errors.cross_state_blocked("Gate is not ACTIVE.")
    else:
        if db.remote_stands[a["remote_stand_id"]]["status"] != "ACTIVE":
            raise errors.cross_state_blocked("Remote stand is not ACTIVE.")

    a["status"] = "OCCUPIED"
    occupancy.inc_source_counter(a)
    db.touch(a)
    flight["handling_status"] = "AT_GATE"
    db.touch(flight)
    return success(helpers.serialize(a), status=200)


@bp.route("/gate-assignments/<aid>/tow", methods=["POST"])
def tow(aid):
    _, role = authenticate()
    require_roles(role, {"GateController"})
    a = _get_assignment_or_404(aid)
    body = helpers.get_body()

    # existence (priority 3): target_remote_stand_id FK
    target_id = body.get("target_remote_stand_id")
    target = None
    if target_id is not None:
        target = db.remote_stands.get(target_id)
        if target is None:
            raise errors.not_found("Target remote stand not found.")

    # well-formedness (priority 4)
    helpers.require_fields(body, ["target_remote_stand_id"])

    # state from-check (priority 5): OCCUPIED and stand_type GATE
    if a["status"] != "OCCUPIED":
        raise errors.invalid_state("Assignment is not OCCUPIED.")
    if a["stand_type"] != "GATE":
        raise errors.invalid_state("Only GATE assignments can be towed.")

    # cross-state guard (priority 6): target stand ACTIVE
    if target["status"] != "ACTIVE":
        raise errors.cross_state_blocked("Target remote stand is not ACTIVE.")

    # wingspan fit (priority 7)
    flight = db.flights[a["flight_id"]]
    if target["max_wingspan_m"] < flight["aircraft_wingspan_m"]:
        raise errors.wingspan_exceeded()

    # remote capacity (priority 11): occupancy_count < capacity
    if target["occupancy_count"] >= target["capacity"]:
        raise errors.remote_stand_full()

    # transition
    a["status"] = "TOWED_AWAY"
    a["tow_target_stand_id"] = target_id
    target["occupancy_count"] += 1
    db.touch(target)
    db.touch(a)
    flight["handling_status"] = "TOWED_OFF"
    db.touch(flight)
    return success(helpers.serialize(a), status=200)


@bp.route("/gate-assignments/<aid>/return", methods=["POST"])
def return_to_gate(aid):
    _, role = authenticate()
    require_roles(role, {"GateController"})
    a = _get_assignment_or_404(aid)
    if a["status"] != "TOWED_AWAY":
        raise errors.invalid_state("Assignment is not TOWED_AWAY.")
    target_id = a.get("tow_target_stand_id")
    if target_id is not None and target_id in db.remote_stands:
        target = db.remote_stands[target_id]
        target["occupancy_count"] -= 1
        db.touch(target)
    a["tow_target_stand_id"] = None
    a["status"] = "OCCUPIED"
    db.touch(a)
    flight = db.flights[a["flight_id"]]
    flight["handling_status"] = "AT_GATE"
    db.touch(flight)
    return success(helpers.serialize(a), status=200)


@bp.route("/gate-assignments/<aid>/depart", methods=["POST"])
def depart(aid):
    _, role = authenticate()
    require_roles(role, {"RampAgent"})
    a = _get_assignment_or_404(aid)
    if a["status"] != "OCCUPIED":
        raise errors.invalid_state("Assignment is not OCCUPIED.")
    occupancy.teardown_counters(a)  # decrement source stand counter
    a["status"] = "RELEASED"
    db.touch(a)
    flight = db.flights[a["flight_id"]]
    flight["handling_status"] = "DEPARTED"
    db.touch(flight)
    return success(helpers.serialize(a), status=200)


@bp.route("/gate-assignments/<aid>/cancel", methods=["POST"])
def cancel(aid):
    _, role = authenticate()
    require_roles(role, {"GateController"})
    a = _get_assignment_or_404(aid)
    if a["status"] not in ("PLANNED", "OCCUPIED", "TOWED_AWAY"):
        raise errors.invalid_state("Assignment cannot be cancelled from its current state.")
    occupancy.teardown_counters(a)  # pinned reconciliation (no-op if PLANNED)
    a["status"] = "CANCELLED"
    db.touch(a)
    return success(helpers.serialize(a), status=200)
