"""Program cycles, the ops checkpoint and the logical clock (PRD 3.1, 2.5)."""
from flask import Blueprint

import calc
import config as C
import domain
import guards as G
import response as R
import serialize as Z
import store as S
from errors import ApiError
from guards import route

bp = Blueprint("cycles", __name__)


@route(bp, "/program-cycles", ["POST"], [C.ROLE_PROGRAM_MANAGER])
def create_program_cycle():
    payload = G.body()
    cycle_code = G.v_str(payload, "cycle_code", min_len=1, max_len=64)
    starts_at = G.v_dt(payload, "starts_at")
    ends_at = G.v_dt(payload, "ends_at")
    capacity_slot_total = G.v_int(payload, "capacity_slot_total", minimum=1)
    if ends_at <= starts_at:
        raise ApiError("ERR_VALIDATION", "ends_at must be strictly after starts_at")
    for existing in S.all_rows("program_cycles"):
        if existing["cycle_code"] == cycle_code:
            raise ApiError("ERR_VALIDATION", "cycle_code must be unique")
    row = S.insert(
        "program_cycles",
        {
            "cycle_code": cycle_code,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "capacity_slot_total": capacity_slot_total,
            "last_recalculated_at": None,
            "recalc_epoch": 0,
        },
    )
    return R.created(Z.program_cycle(row))


@route(
    bp,
    "/program-cycles/<cycle_id>",
    ["GET"],
    [C.ROLE_PROGRAM_MANAGER, C.ROLE_SCOPING_SPECIALIST, C.ROLE_PARTNER_CONTACT],
)
def get_program_cycle(cycle_id):
    cycle = G.g04_cycle(cycle_id)
    return R.ok(Z.program_cycle(cycle))


@route(
    bp, "/program-cycles/<cycle_id>/recalculate", ["POST"], [C.ROLE_PROGRAM_MANAGER]
)
def recalculate_program_cycle(cycle_id):
    cycle = G.g04_cycle(cycle_id)
    domain.recalculate_cycle(cycle)
    return R.ok(Z.program_cycle(cycle))


@route(
    bp,
    "/program-cycles/<cycle_id>/engagements",
    ["GET"],
    [C.ROLE_PROGRAM_MANAGER, C.ROLE_SCOPING_SPECIALIST],
)
def list_cycle_engagements(cycle_id):
    cycle = G.g04_cycle(cycle_id)
    rows = calc.cycle_engagements(cycle["id"])
    return R.paginate(rows, Z.engagement)


@route(bp, "/_clock/set_current_utc", ["POST"], [C.ROLE_PROGRAM_MANAGER])
def set_clock():
    payload = G.body()
    target = G.v_dt(payload, "to_iso8601")
    G.g42_no_clock_regression(target)
    S.set_clock(target)
    return R.ok({})
