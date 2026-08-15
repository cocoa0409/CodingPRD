"""MarketAssumption endpoints."""
from db import DB, new_id
from errors import ApiError
from middleware import auth, READ_ROLES
from response import ok, ok_list
from services import deal_assumptions
from util import (
    assumption_view,
    get_assumption,
    get_deal,
    init_common_fields,
    json_body,
    paginate,
    parse_int_field,
    parse_pagination,
    parse_str_field,
    touch,
)


def register(app):
    @app.post("/re-underwriting/deals/<deal_id>/assumptions")
    def create_assumption(deal_id):
        _user_id, _role = auth(allowed=["Analyst"])
        d = get_deal(deal_id)
        body = json_body()
        label = parse_str_field(body, "label")
        g1 = parse_int_field(body, "market_rent_growth_yr1_bps")
        gs = parse_int_field(body, "market_rent_growth_steady_bps")
        eg = parse_int_field(body, "expense_growth_bps")
        exit_cap = parse_int_field(body, "exit_cap_rate_bps")
        if exit_cap <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "exit_cap_rate_bps must be > 0")
        hold = parse_int_field(body, "hold_period_years")
        if not (1 <= hold <= 15):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "hold_period_years must be between 1 and 15"
            )
        capex = parse_int_field(body, "capex_per_unit_cents")
        if capex < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "capex_per_unit_cents must be >= 0")
        lease_up = parse_int_field(body, "lease_up_months")
        if not (0 <= lease_up <= 36):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "lease_up_months must be between 0 and 36"
            )

        # is_active default: true iff this is the first assumption for the deal
        is_active = not any(True for _ in deal_assumptions(deal_id))

        rec = {
            "id": new_id(),
            "deal_id": deal_id,
            "label": label,
            "market_rent_growth_yr1_bps": g1,
            "market_rent_growth_steady_bps": gs,
            "expense_growth_bps": eg,
            "exit_cap_rate_bps": exit_cap,
            "hold_period_years": hold,
            "capex_per_unit_cents": capex,
            "lease_up_months": lease_up,
            "is_active": is_active,
        }
        init_common_fields(rec)
        DB["market_assumptions"][rec["id"]] = rec
        touch(d)  # bump parent deal version
        return ok(assumption_view(rec), status=201)

    @app.post("/re-underwriting/assumptions/<assumption_id>/activate")
    def activate_assumption(assumption_id):
        _user_id, _role = auth(allowed=["Analyst"])
        target = get_assumption(assumption_id)
        deal_id = target["deal_id"]
        # deactivate all others on the same deal
        for m in deal_assumptions(deal_id):
            if m["id"] != assumption_id and m["is_active"]:
                m["is_active"] = False
                # Note: per PRD 3.3, only the target's version increments.
        target["is_active"] = True
        touch(target)
        return ok(assumption_view(target))

    @app.get("/re-underwriting/deals/<deal_id>/assumptions")
    def list_assumptions(deal_id):
        auth(allowed=READ_ROLES)
        get_deal(deal_id)
        limit, offset = parse_pagination()
        items = sorted(deal_assumptions(deal_id), key=lambda m: m["created_at"])
        page, total = paginate(items, limit, offset)
        return ok_list([assumption_view(m) for m in page], total, limit, offset)

    @app.get("/re-underwriting/assumptions/<assumption_id>")
    def get_assumption_route(assumption_id):
        auth(allowed=READ_ROLES)
        m = get_assumption(assumption_id)
        return ok(assumption_view(m))
