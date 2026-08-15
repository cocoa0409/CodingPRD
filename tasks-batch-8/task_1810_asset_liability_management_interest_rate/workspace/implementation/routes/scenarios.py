"""RateScenario endpoints (PRD 3.3)."""

import store
from calc import PRESET_CODES
from envelope import list_response, object_response
from errors import ApiError
from serializers import scenario_json
from services import stamp_new, touch
from validate import opt_int, req_enum, req_int, req_str

from routes.common import READ_ROLES, endpoint, get_or_404

SCENARIO_KINDS = ("PARALLEL_SHOCK", "RAMP", "REGULATORY_PRESET")


@endpoint("POST", "/books/<book_id>/scenarios", roles=["TreasuryAnalyst"])
def create_scenario(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    body = ctx.body
    # Rung 4: generic shape, then the kind-conditional required fields.
    name = req_str(body, "name")
    kind = req_enum(body, "kind", SCENARIO_KINDS)
    horizon = opt_int(body, "horizon_months", default=12)
    if horizon not in (12, 24):
        raise ApiError("ERR_INVALID_REQUEST")
    shock_bps = None
    ramp_total_bps = None
    ramp_months = None
    preset_code = None
    if kind == "PARALLEL_SHOCK":
        shock_bps = req_int(body, "shock_bps")
    elif kind == "RAMP":
        ramp_total_bps = req_int(body, "ramp_total_bps")
        ramp_months = req_int(body, "ramp_months", min_v=1)
    else:  # REGULATORY_PRESET
        preset_code = req_enum(body, "preset_code", PRESET_CODES)
    scenario = {
        "book_id": book["id"],
        "name": name,
        "kind": kind,
        "shock_bps": shock_bps,
        "ramp_total_bps": ramp_total_bps,
        "ramp_months": ramp_months,
        "preset_code": preset_code,
        "horizon_months": horizon,
        "status": "ACTIVE",
    }
    stamp_new(scenario)
    store.scenarios[scenario["id"]] = scenario
    return object_response(scenario_json(scenario), 201)


@endpoint("GET", "/books/<book_id>/scenarios", roles=READ_ROLES)
def list_scenarios(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    rows = [s for s in store.scenarios.values() if s["book_id"] == book["id"]]
    kind = ctx.args.get("kind")
    if kind is not None:
        rows = [s for s in rows if s["kind"] == kind]
    status = ctx.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return list_response(rows, ctx.args, scenario_json)


@endpoint("GET", "/scenarios/<scenario_id>", roles=READ_ROLES)
def get_scenario(ctx):
    scenario = get_or_404(store.scenarios, ctx.param("scenario_id"))
    return object_response(scenario_json(scenario))


@endpoint("POST", "/scenarios/<scenario_id>/archive", roles=["TreasuryAnalyst"])
def archive_scenario(ctx):
    scenario = get_or_404(store.scenarios, ctx.param("scenario_id"))
    if scenario["status"] != "ACTIVE":  # rung 6
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    scenario["status"] = "ARCHIVED"
    touch(scenario)
    return object_response(scenario_json(scenario))
