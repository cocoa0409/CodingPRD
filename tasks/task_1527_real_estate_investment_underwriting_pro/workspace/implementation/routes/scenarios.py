"""Scenario, debt-sizing, and waterfall endpoints."""
from flask import request

from db import DB, new_id
from errors import ApiError
from middleware import auth, READ_ROLES
from response import ok, ok_list
from services import (
    compute_scenario,
    deal_scenarios,
    run_waterfall,
    size_debt,
    scenario_debt_sizings,
    scenario_waterfalls,
)
from util import (
    debt_sizing_view,
    get_assumption,
    get_deal,
    get_scenario,
    init_common_fields,
    json_body,
    paginate,
    parse_enum_field,
    parse_int_field,
    parse_pagination,
    scenario_view,
    touch,
    waterfall_view,
)

SCENARIO_KINDS = ["BASE", "DOWNSIDE", "UPSIDE", "STRESS"]


def register(app):
    @app.post("/re-underwriting/deals/<deal_id>/scenarios")
    def create_scenario(deal_id):
        _user_id, _role = auth(allowed=["Analyst"])
        d = get_deal(deal_id)
        body = json_body()

        # body FK existence
        assumption_id = body.get("assumption_id")
        if assumption_id is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "Missing required field: assumption_id"
            )
        assumption = DB["market_assumptions"].get(assumption_id)
        if assumption is None:
            raise ApiError("ERR_NOT_FOUND", 404, "MarketAssumption does not exist")

        scenario_kind = parse_enum_field(body, "scenario_kind", SCENARIO_KINDS)
        occupancy_stress_pct = parse_int_field(body, "occupancy_stress_pct")
        if not (0 <= occupancy_stress_pct <= 100):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "occupancy_stress_pct must be between 0 and 100",
            )

        # referential: assumption must belong to same deal
        if assumption["deal_id"] != deal_id:
            raise ApiError(
                "ERR_ASSUMPTION_MISMATCH",
                422,
                "assumption_id resolves to a MarketAssumption that does not belong to the deal",
            )

        # OCC check
        expected = body.get("expected_deal_version")
        if expected is not None:
            if isinstance(expected, bool) or not isinstance(expected, int):
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    "expected_deal_version must be an integer",
                )
            if expected != d["version"]:
                raise ApiError(
                    "ERR_STALE_VERSION",
                    412,
                    "expected_deal_version does not match deal.version",
                )

        rec = {
            "id": new_id(),
            "deal_id": deal_id,
            "scenario_kind": scenario_kind,
            "assumption_id": assumption_id,
            "occupancy_stress_pct": occupancy_stress_pct,
            "status": "DRAFT",
            "computed_noi_yr1_cents": None,
            "computed_irr_bps": None,
            "computed_equity_multiple_bp": None,
            "superseded_by_id": None,
        }
        init_common_fields(rec)
        DB["scenarios"][rec["id"]] = rec
        touch(d)  # bump parent deal version
        return ok(scenario_view(rec), status=201)

    @app.get("/re-underwriting/deals/<deal_id>/scenarios")
    def list_deal_scenarios(deal_id):
        auth(allowed=READ_ROLES)
        get_deal(deal_id)
        limit, offset = parse_pagination()
        items = [s for s in deal_scenarios(deal_id)]
        items = _apply_scenario_filters(items)
        items.sort(key=lambda s: s["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([scenario_view(s) for s in page], total, limit, offset)

    @app.get("/re-underwriting/scenarios")
    def list_all_scenarios():
        auth(allowed=READ_ROLES)
        limit, offset = parse_pagination()
        items = list(DB["scenarios"].values())
        deal_id = request.args.get("deal_id")
        if deal_id is not None:
            items = [s for s in items if s["deal_id"] == deal_id]
        items = _apply_scenario_filters(items)
        items.sort(key=lambda s: s["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([scenario_view(s) for s in page], total, limit, offset)

    @app.get("/re-underwriting/scenarios/<scenario_id>")
    def get_scenario_route(scenario_id):
        auth(allowed=READ_ROLES)
        s = get_scenario(scenario_id)
        return ok(scenario_view(s))

    @app.post("/re-underwriting/scenarios/<scenario_id>/compute")
    def compute(scenario_id):
        user_id, _role = auth(allowed=["Analyst"])
        s = get_scenario(scenario_id)
        d = DB["deals"][s["deal_id"]]
        if s["status"] != "DRAFT":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Scenario is not in DRAFT status"
            )
        if d["status"] != "UNDERWRITING":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Deal is not in UNDERWRITING status"
            )
        if d["analyst_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", 403, "Caller is not the deal's analyst")
        compute_scenario(s)
        return ok(scenario_view(s))

    @app.post("/re-underwriting/scenarios/<scenario_id>/debt-sizing")
    def create_debt_sizing(scenario_id):
        _user_id, _role = auth(allowed=["Analyst"])
        s = get_scenario(scenario_id)
        if s["status"] != "COMPUTED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Scenario is not in COMPUTED status"
            )
        d = DB["deals"][s["deal_id"]]
        body = json_body()
        interest_rate_bps = parse_int_field(body, "interest_rate_bps")
        amortization_years = parse_int_field(body, "amortization_years")
        if not (1 <= amortization_years <= 30):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "amortization_years must be between 1 and 30",
            )
        io_months = parse_int_field(body, "io_months")
        if not (0 <= io_months <= 120):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "io_months must be between 0 and 120"
            )
        min_dscr_pct = parse_int_field(body, "min_dscr_pct")
        max_ltv_pct = parse_int_field(body, "max_ltv_pct")

        result = size_debt(
            s, d, interest_rate_bps, amortization_years, io_months, min_dscr_pct, max_ltv_pct
        )

        rec = {
            "id": new_id(),
            "scenario_id": scenario_id,
            "loan_amount_cents": result["loan_amount_cents"],
            "interest_rate_bps": interest_rate_bps,
            "amortization_years": amortization_years,
            "io_months": io_months,
            "min_dscr_pct": min_dscr_pct,
            "max_ltv_pct": max_ltv_pct,
            "dscr_at_size_pct": result["dscr_at_size_pct"],
            "ltv_at_size_pct": result["ltv_at_size_pct"],
            "sizing_constraint": result["sizing_constraint"],
        }
        init_common_fields(rec)
        DB["debt_sizings"][rec["id"]] = rec
        return ok(debt_sizing_view(rec), status=201)

    @app.get("/re-underwriting/scenarios/<scenario_id>/debt-sizing")
    def list_debt_sizings(scenario_id):
        auth(allowed=READ_ROLES)
        get_scenario(scenario_id)
        limit, offset = parse_pagination()
        items = sorted(scenario_debt_sizings(scenario_id), key=lambda x: x["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([debt_sizing_view(x) for x in page], total, limit, offset)

    @app.post("/re-underwriting/scenarios/<scenario_id>/waterfall")
    def create_waterfall(scenario_id):
        _user_id, _role = auth(allowed=["Analyst"])
        s = get_scenario(scenario_id)
        if s["status"] != "COMPUTED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Scenario is not in COMPUTED status"
            )
        d = DB["deals"][s["deal_id"]]
        assumption = DB["market_assumptions"][s["assumption_id"]]
        body = json_body()
        pref_return_bps = parse_int_field(body, "pref_return_bps")
        promote_tier1_bps = parse_int_field(body, "promote_tier1_bps")
        tier1_hurdle_bps = parse_int_field(body, "tier1_hurdle_bps")
        promote_tier2_bps = parse_int_field(body, "promote_tier2_bps")
        if promote_tier2_bps < promote_tier1_bps:
            raise ApiError(
                "ERR_PROMOTE_REGRESSIVE",
                422,
                "promote_tier2_bps must be >= promote_tier1_bps",
            )

        result = run_waterfall(
            s, d, assumption, pref_return_bps, promote_tier1_bps, tier1_hurdle_bps, promote_tier2_bps
        )
        rec = {
            "id": new_id(),
            "scenario_id": scenario_id,
            "pref_return_bps": pref_return_bps,
            "promote_tier1_bps": promote_tier1_bps,
            "tier1_hurdle_bps": tier1_hurdle_bps,
            "promote_tier2_bps": promote_tier2_bps,
            "lp_split_cents": result["lp_split_cents"],
            "gp_split_cents": result["gp_split_cents"],
            "gp_promote_cents": result["gp_promote_cents"],
        }
        init_common_fields(rec)
        DB["waterfalls"][rec["id"]] = rec
        return ok(waterfall_view(rec), status=201)

    @app.get("/re-underwriting/scenarios/<scenario_id>/waterfall")
    def list_waterfalls(scenario_id):
        auth(allowed=READ_ROLES)
        get_scenario(scenario_id)
        limit, offset = parse_pagination()
        items = sorted(scenario_waterfalls(scenario_id), key=lambda x: x["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([waterfall_view(x) for x in page], total, limit, offset)


def _apply_scenario_filters(items):
    status = request.args.get("status")
    scenario_kind = request.args.get("scenario_kind")
    assumption_id = request.args.get("assumption_id")
    superseded_by_id = request.args.get("superseded_by_id")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if scenario_kind is not None:
        items = [s for s in items if s["scenario_kind"] == scenario_kind]
    if assumption_id is not None:
        items = [s for s in items if s["assumption_id"] == assumption_id]
    if superseded_by_id is not None:
        items = [s for s in items if s["superseded_by_id"] == superseded_by_id]
    return items
