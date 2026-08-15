"""BandProgram endpoints."""
from flask import Blueprint, request
from db import store, new_id, now_iso
from errors import (
    raise_err, ERR_PROGRAM_NOT_FOUND, ERR_PROGRAM_NOT_IN_REQUIRED_STATE,
    ERR_PROGRAM_HAS_OPEN_OBLIGATIONS, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import program_out
from services.validators import body, require, check_unknown, to_int, to_str, to_enum
from services.clock_eval import apply_time_transitions

bp = Blueprint("programs", __name__)


def _get_program_or_404(pid):
    p = store.programs.get(pid)
    if p is None:
        raise_err(ERR_PROGRAM_NOT_FOUND, f"program {pid} not found")
    return p


def _program_posture_open(p):
    if p["status"] not in ("ENROLLMENT_OPEN", "SEASON_ACTIVE"):
        raise_err(ERR_PROGRAM_NOT_IN_REQUIRED_STATE,
                  "program is not in ENROLLMENT_OPEN or SEASON_ACTIVE")


@bp.route("/band/programs", methods=["POST"])
def create_program():
    uid, role = require_roles(["BandDirector"])
    data = body()
    check_unknown(data, {"season_name", "music_budget_cents", "repair_budget_cents",
                         "rental_fee_mode", "scoring_mode", "subsidy_pool_cents",
                         "delinquency_grace_cents"})
    require(data, "season_name", "music_budget_cents", "repair_budget_cents")
    season_name = to_str(data["season_name"], "season_name")
    music_budget_cents = to_int(data["music_budget_cents"], "music_budget_cents")
    repair_budget_cents = to_int(data["repair_budget_cents"], "repair_budget_cents")
    rental_fee_mode = to_enum(data.get("rental_fee_mode", "FLAT"), "rental_fee_mode", {"FLAT", "PRORATED"})
    scoring_mode = to_enum(data.get("scoring_mode", "RAW_WEIGHTED"), "scoring_mode", {"RAW_WEIGHTED", "RANK_NORMALIZED"})
    subsidy_pool_cents = to_int(data.get("subsidy_pool_cents", 0), "subsidy_pool_cents")
    delinquency_grace_cents = to_int(data.get("delinquency_grace_cents", 2500), "delinquency_grace_cents")

    pid = new_id()
    now_s = now_iso()
    p = {
        "id": pid,
        "season_name": season_name,
        "status": "SETUP",
        "rental_fee_mode": rental_fee_mode,
        "scoring_mode": scoring_mode,
        "music_budget_cents": music_budget_cents,
        "repair_budget_cents": repair_budget_cents,
        "subsidy_pool_cents": subsidy_pool_cents,
        "delinquency_grace_cents": delinquency_grace_cents,
        "music_spent_cents": 0,
        "repair_spent_cents": 0,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.programs[pid] = p
    return success(program_out(p), status=201)


@bp.route("/band/programs", methods=["GET"])
def list_programs():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = sorted(store.programs.values(), key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([program_out(p) for p in page], is_list=True, pagination=pag)


@bp.route("/band/programs/<pid>", methods=["GET"])
def get_program(pid):
    require_roles(["Any"])
    apply_time_transitions()
    p = _get_program_or_404(pid)
    return success(program_out(p))


@bp.route("/band/programs/<pid>", methods=["PATCH"])
def patch_program(pid):
    uid, role = require_roles(["BandDirector"])
    p = _get_program_or_404(pid)
    data = body()
    check_unknown(data, {"expected_program_version", "music_budget_cents",
                         "repair_budget_cents", "subsidy_pool_cents",
                         "delinquency_grace_cents", "rental_fee_mode", "scoring_mode"})
    require(data, "expected_program_version")
    expected = to_int(data["expected_program_version"], "expected_program_version")
    if expected != p["version"]:
        raise_err(ERR_STALE_VERSION, "expected_program_version does not match current version")
    if "music_budget_cents" in data:
        p["music_budget_cents"] = to_int(data["music_budget_cents"], "music_budget_cents")
    if "repair_budget_cents" in data:
        p["repair_budget_cents"] = to_int(data["repair_budget_cents"], "repair_budget_cents")
    if "subsidy_pool_cents" in data:
        p["subsidy_pool_cents"] = to_int(data["subsidy_pool_cents"], "subsidy_pool_cents")
    if "delinquency_grace_cents" in data:
        p["delinquency_grace_cents"] = to_int(data["delinquency_grace_cents"], "delinquency_grace_cents")
    if "rental_fee_mode" in data:
        p["rental_fee_mode"] = to_enum(data["rental_fee_mode"], "rental_fee_mode", {"FLAT", "PRORATED"})
    if "scoring_mode" in data:
        p["scoring_mode"] = to_enum(data["scoring_mode"], "scoring_mode", {"RAW_WEIGHTED", "RANK_NORMALIZED"})
    p["version"] += 1
    p["updated_at"] = now_iso()
    return success(program_out(p))


@bp.route("/band/programs/<pid>/advance", methods=["POST"])
def advance_program(pid):
    uid, role = require_roles(["BandDirector"])
    p = _get_program_or_404(pid)
    data = body()
    check_unknown(data, {"to_state"})
    require(data, "to_state")
    to_state = to_enum(data["to_state"], "to_state",
                       {"SETUP", "ENROLLMENT_OPEN", "SEASON_ACTIVE", "CLOSED"})

    # Valid transitions: SETUP->ENROLLMENT_OPEN->SEASON_ACTIVE->CLOSED
    valid_next = {
        "SETUP": "ENROLLMENT_OPEN",
        "ENROLLMENT_OPEN": "SEASON_ACTIVE",
        "SEASON_ACTIVE": "CLOSED",
    }
    cur = p["status"]
    if cur == "CLOSED" or valid_next.get(cur) != to_state:
        raise_err(ERR_PROGRAM_NOT_IN_REQUIRED_STATE,
                  f"cannot advance program from {cur} to {to_state}")
    if to_state == "CLOSED":
        # check open obligations
        for a in store.instrument_assignments.values():
            if store.instruments.get(a["instrument_id"]) and \
               store.instruments[a["instrument_id"]]["program_id"] == pid and \
               a["status"] in ("ACTIVE", "OVERDUE"):
                raise_err(ERR_PROGRAM_HAS_OPEN_OBLIGATIONS,
                          "program has open instrument assignments")
        for ua in store.uniform_assignments.values():
            u = store.uniforms.get(ua["uniform_id"])
            if u and u["program_id"] == pid and ua["status"] == "ISSUED":
                raise_err(ERR_PROGRAM_HAS_OPEN_OBLIGATIONS,
                          "program has open uniform assignments")
        for t in store.trips.values():
            if t["program_id"] == pid and t["status"] in ("PLANNING", "ROSTER_OPEN", "ROSTER_LOCKED", "FINALIZED"):
                raise_err(ERR_PROGRAM_HAS_OPEN_OBLIGATIONS,
                          "program has open trips")
    p["status"] = to_state
    p["version"] += 1
    p["updated_at"] = now_iso()
    return success(program_out(p))
