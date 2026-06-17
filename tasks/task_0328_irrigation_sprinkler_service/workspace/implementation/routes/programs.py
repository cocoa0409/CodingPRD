"""ControllerProgram routes (PRD §3.2)."""
from flask import Blueprint, request

from db import db, LOCK, stamp_new, touch
import domain
import errors
import lookups
from domain import serialize, VALVE_SWITCH_BUFFER_SEC
from errors import fail
from listing import list_response
from middleware import get_auth, require_role
from response import success
from validation import get_body, require_str, require_slots

bp = Blueprint("programs", __name__)


@bp.route("/controller-programs", methods=["POST"])
def create_program():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Technician"})
    with LOCK:
        body = get_body()
        system_id = require_str(body, "system_id")
        lookups.get_system(system_id)
        slots = require_slots(body, "slots")
        rec = {
            "system_id": system_id,
            "program_state": "DRAFT",
            "slots": slots,
            "total_run_minutes": 0,
        }
        stamp_new(rec)
        domain.recompute_program_total(rec)
        db.controller_programs[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/controller-programs/<pid>", methods=["GET"])
def get_program(pid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Technician"})
    with LOCK:
        rec = lookups.get_program(pid)
        return success(serialize(rec), status=200)


@bp.route("/controller-programs", methods=["GET"])
def list_programs():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Technician"})
    with LOCK:
        rows = list(db.controller_programs.values())
        system_id = request.args.get("system_id")
        if system_id is not None:
            rows = [p for p in rows if p["system_id"] == system_id]
        return list_response(rows)


def _check_slot_overlap(program):
    """Buffered, gap-aware overlap check (PRD §3.2).

    Sort by start_sec ASC, tie-break by run_minutes ASC, then by the referenced
    zone's created_at ASC (never by id). Walk adjacent pairs; conflict when
    (B.start - A.end) < VALVE_SWITCH_BUFFER_SEC. Exact adjacency (gap 0) rejects.
    """
    def zone_created_at(slot):
        z = db.zones.get(slot["zone_id"])
        # Zone existence is not a precondition of activation in the spec; if the
        # zone is missing, fall back to a deterministic key so sorting stays stable.
        return (z["created_at"], z.get("_seq", 0)) if z else ("", 0)

    ordered = sorted(
        program["slots"],
        key=lambda s: (s["start_sec"], s["run_minutes"], zone_created_at(s)),
    )
    for a, b in zip(ordered, ordered[1:]):
        a_end = a["start_sec"] + a["run_minutes"] * 60
        if (b["start_sec"] - a_end) < VALVE_SWITCH_BUFFER_SEC:
            return False
    return True


@bp.route("/controller-programs/<pid>/activate", methods=["POST"])
def activate_program(pid):
    _, role = get_auth()
    require_role(role, {"Technician"})
    with LOCK:
        program = lookups.get_program(pid)
        # State precondition (priority 5)
        if program["program_state"] != "DRAFT":
            fail(errors.ERR_PROGRAM_NOT_DRAFT, "Program is not in DRAFT")
        # Empty-program guard (priority 10, boundary empty-set)
        if len(program["slots"]) == 0:
            fail(errors.ERR_EMPTY_PROGRAM, "Program has no slots")
        # Season gate (priority 9): system.season_state must be ACTIVE
        system = db.irrigation_systems.get(program["system_id"])
        if system is None or system["season_state"] != "ACTIVE":
            fail(errors.ERR_SEASON_STATE_BLOCKS_PROGRAM, "System is not in ACTIVE season")
        # Slot overlap with buffer (priority 10)
        if not _check_slot_overlap(program):
            fail(errors.ERR_PROGRAM_SLOT_OVERLAP, "Program slots conflict within valve-switch buffer")

        program["program_state"] = "ACTIVE"
        touch(program)
        # Promote referenced MAPPED zones to ACTIVE; recompute system zone_count.
        slot_zone_ids = {s["zone_id"] for s in program["slots"]}
        for zid in slot_zone_ids:
            z = db.zones.get(zid)
            if z and z["zone_state"] == "MAPPED":
                z["zone_state"] = "ACTIVE"
                touch(z)
        domain.recompute_system_derived(system)
        return success(serialize(program), status=200)
