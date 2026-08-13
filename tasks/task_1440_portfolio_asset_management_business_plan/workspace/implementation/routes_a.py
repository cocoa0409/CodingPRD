"""Routes: logical clock, portfolios, property managers, assets, sale pipeline,
and their reverse-reachability list endpoints."""
from datetime import timedelta
from flask import Blueprint

from core import (
    store, ALL_ROLES, ASSET_CLASSES, SALE_ACTIONS,
    auth_user, require_role, body, req_str, req_int, req_pos_int, req_enum, req_date,
    opt_str, opt_int, get_or_404, new_record, touch,
    success_object, list_response, bad_request, forbidden, conflict, unprocessable,
    clock_now, clock_date, now_iso, fmt_clock, parse_iso8601,
    assets_of_portfolio, assets_of_manager, plans_of_asset, projects_of_asset,
    strategies_of_asset, loans_of_asset, valuations_of_asset, scorecards_of_asset,
    scorecards_of_manager, decisions_of_asset, covenants_of_loan, close_plan,
    waive_loan_covenants, annualized_noi, rhu_div,
    ser_portfolio, ser_manager, ser_asset, ser_plan, ser_project, ser_strategy,
    ser_loan, ser_valuation, ser_scorecard, ser_decision,
)

bp = Blueprint("routes_a", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def a_set_clock():
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    b = body()
    raw = req_str(b, "to_iso8601")
    dt = parse_iso8601(raw)
    if dt is None:
        raise bad_request("to_iso8601 must be a valid ISO 8601 datetime")
    if not (dt > store.clock):
        raise bad_request("to_iso8601 must be strictly after the current logical time")
    store.clock = dt
    return success_object({"current_utc": fmt_clock(dt)})


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------

@bp.route("/api/portfolios", methods=["POST"])
def a_create_portfolio():
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    b = body()
    name = req_str(b, "name")
    currency = opt_str(b, "base_currency", "USD")
    fysm = opt_int(b, "fiscal_year_start_month", 1)
    if fysm < 1 or fysm > 12:
        raise bad_request("fiscal_year_start_month must be in 1..12")
    rec = new_record()
    rec.update({"name": name, "base_currency": currency,
                "fiscal_year_start_month": fysm, "status": "ACTIVE"})
    store.portfolios[rec["id"]] = rec
    return success_object(ser_portfolio(rec), 201)


@bp.route("/api/portfolios/<string:rid>", methods=["GET"])
def a_get_portfolio(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    return success_object(ser_portfolio(get_or_404(store.portfolios, rid, "portfolio")))


@bp.route("/api/portfolios/<string:rid>/archive", methods=["POST"])
def a_archive_portfolio(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    p = get_or_404(store.portfolios, rid, "portfolio")
    if p["status"] != "ACTIVE":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Portfolio is not ACTIVE")
    if any(a["status"] != "SOLD" for a in assets_of_portfolio(p["id"])):
        raise conflict("ERR_PORTFOLIO_NOT_EMPTY", "Portfolio still has assets that are not SOLD")
    p["status"] = "ARCHIVED"
    touch(p)
    return success_object(ser_portfolio(p))


@bp.route("/api/portfolios/<string:rid>/performance-report", methods=["GET"])
def a_performance_report(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    p = get_or_404(store.portfolios, rid, "portfolio")
    assets = [a for a in assets_of_portfolio(p["id"])
              if a["status"] in ("OWNED", "LISTED_FOR_SALE", "UNDER_CONTRACT")]
    total_value = 0
    total_noi = 0
    num = 0
    den = 0
    for a in assets:
        total_value += a["current_value_cents"] or 0
        noi = annualized_noi(a)
        total_noi += noi if noi is not None else 0
        cards = [s for s in scorecards_of_asset(a["id"]) if s["status"] == "FINALIZED"]
        occ = 0
        if cards:
            cards.sort(key=lambda s: (s["period_label"], s["_seq"]))
            occ = cards[-1]["occupancy_pct"]
        num += occ * a["net_rentable_sqft"]
        den += a["net_rentable_sqft"]
    weighted = rhu_div(num, den) if den > 0 else 0
    cap = rhu_div(total_noi * 10000, total_value) if total_value > 0 else None
    return success_object({
        "total_value_cents": total_value,
        "portfolio_noi_cents": total_noi,
        "weighted_occupancy_pct": weighted,
        "implied_cap_rate_bps": cap,
        "asset_count": len(assets),
    })


@bp.route("/api/portfolios/<string:rid>/assets", methods=["GET"])
def a_portfolio_assets(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    p = get_or_404(store.portfolios, rid, "portfolio")
    return list_response(assets_of_portfolio(p["id"]), ser_asset)


# ---------------------------------------------------------------------------
# Property managers
# ---------------------------------------------------------------------------

@bp.route("/api/property-managers", methods=["POST"])
def a_create_manager():
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    b = body()
    firm = req_str(b, "firm_name")
    email = req_str(b, "contact_email")
    rec = new_record()
    rec.update({"firm_name": firm, "contact_email": email,
                "status": "ACTIVE", "probation_streak": 0})
    store.managers[rec["id"]] = rec
    return success_object(ser_manager(rec), 201)


@bp.route("/api/property-managers/<string:rid>", methods=["GET"])
def a_get_manager(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    return success_object(ser_manager(get_or_404(store.managers, rid, "property manager")))


@bp.route("/api/property-managers/<string:rid>/suspend", methods=["POST"])
def a_suspend_manager(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    m = get_or_404(store.managers, rid, "property manager")
    b = body()
    terminate = b.get("terminate", False)
    if not isinstance(terminate, bool):
        raise bad_request("terminate must be a boolean")
    if m["status"] != "ACTIVE":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Manager is not ACTIVE")
    if terminate:
        if any(a["property_manager_id"] == m["id"] and
               a["status"] in ("OWNED", "LISTED_FOR_SALE", "UNDER_CONTRACT")
               for a in store.assets.values()):
            raise conflict("ERR_MANAGER_IN_USE",
                           "Manager is still referenced by a non-SOLD asset")
        m["status"] = "TERMINATED"
    else:
        m["status"] = "SUSPENDED"
    touch(m)
    return success_object(ser_manager(m))


@bp.route("/api/property-managers/<string:rid>/reinstate", methods=["POST"])
def a_reinstate_manager(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    m = get_or_404(store.managers, rid, "property manager")
    if m["status"] != "SUSPENDED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Manager is not SUSPENDED")
    m["status"] = "ACTIVE"
    m["probation_streak"] = 0
    touch(m)
    return success_object(ser_manager(m))


@bp.route("/api/property-managers/<string:rid>/assets", methods=["GET"])
def a_manager_assets(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    m = get_or_404(store.managers, rid, "property manager")
    return list_response(assets_of_manager(m["id"]), ser_asset)


@bp.route("/api/property-managers/<string:rid>/performance-scorecards", methods=["GET"])
def a_manager_scorecards(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    m = get_or_404(store.managers, rid, "property manager")
    return list_response(scorecards_of_manager(m["id"]), ser_scorecard)


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

@bp.route("/api/assets", methods=["POST"])
def a_create_asset():
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    b = body()
    pid = req_str(b, "portfolio_id")
    get_or_404(store.portfolios, pid, "portfolio")
    mid = req_str(b, "property_manager_id")
    get_or_404(store.managers, mid, "property manager")
    name = req_str(b, "name")
    address = req_str(b, "address")
    aclass = req_enum(b, "asset_class", ASSET_CLASSES)
    sqft = req_pos_int(b, "net_rentable_sqft")
    price = req_pos_int(b, "acquisition_price_cents")
    acq = req_date(b, "acquisition_date")
    hold = req_pos_int(b, "hold_period_years")
    if acq > clock_date():
        raise unprocessable("ERR_FUTURE_PERIOD",
                            "acquisition_date must not be after the current clock date")
    rec = new_record()
    rec.update({"portfolio_id": pid, "property_manager_id": mid, "name": name,
                "address": address, "asset_class": aclass, "net_rentable_sqft": sqft,
                "acquisition_price_cents": price, "acquisition_date": acq.isoformat(),
                "hold_period_years": hold, "status": "OWNED",
                "current_value_cents": None, "current_plan_id": None,
                "sale_agreed_price_cents": None, "final_sale_price_cents": None})
    store.assets[rec["id"]] = rec
    return success_object(ser_asset(rec), 201)


@bp.route("/api/assets/<string:rid>", methods=["GET"])
def a_get_asset(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    return success_object(ser_asset(get_or_404(store.assets, rid, "asset")))


@bp.route("/api/assets/<string:rid>/record-sale", methods=["POST"])
def a_record_sale(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    a = get_or_404(store.assets, rid, "asset")
    b = body()
    action = req_enum(b, "action", SALE_ACTIONS)
    if action == "CONTRACT":
        if a["status"] != "LISTED_FOR_SALE":
            raise conflict("ERR_ASSET_NOT_SELLABLE", "Asset is not LISTED_FOR_SALE")
        if not any(d["asset_id"] == a["id"] and d["trigger_type"] == "SELL"
                   and d["status"] in ("RATIFIED", "EXECUTED")
                   for d in store.decisions.values()):
            raise conflict("ERR_ASSET_NOT_SELLABLE",
                           "No RATIFIED or EXECUTED SELL disposition decision exists for this asset")
        price = req_pos_int(b, "sale_agreed_price_cents")
        a["sale_agreed_price_cents"] = price
        a["status"] = "UNDER_CONTRACT"
        touch(a)
    elif action == "CLOSE":
        if a["status"] != "UNDER_CONTRACT":
            raise conflict("ERR_ASSET_NOT_SELLABLE", "Asset is not UNDER_CONTRACT")
        price = req_pos_int(b, "final_sale_price_cents")
        a["final_sale_price_cents"] = price
        a["current_value_cents"] = price
        a["current_plan_id"] = None
        a["status"] = "SOLD"
        touch(a)
        for loan in loans_of_asset(a["id"]):
            if loan["status"] in ("CURRENT", "WATCH"):
                loan["status"] = "PAID_OFF"
                touch(loan)
                waive_loan_covenants(loan)
        for plan in plans_of_asset(a["id"]):
            if plan["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED"):
                close_plan(plan)
    else:  # DELIST
        if a["status"] != "LISTED_FOR_SALE":
            raise conflict("ERR_ASSET_NOT_SELLABLE", "Asset is not LISTED_FOR_SALE")
        a["status"] = "OWNED"
        touch(a)
    return success_object(ser_asset(a))


# --- Asset sub-resource lists -------------------------------------------------

@bp.route("/api/assets/<string:rid>/business-plans", methods=["GET"])
def a_asset_plans(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    a = get_or_404(store.assets, rid, "asset")
    return list_response(plans_of_asset(a["id"]), ser_plan)


@bp.route("/api/assets/<string:rid>/capital-projects", methods=["GET"])
def a_asset_projects(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    a = get_or_404(store.assets, rid, "asset")
    return list_response(projects_of_asset(a["id"]), ser_project)


@bp.route("/api/assets/<string:rid>/lease-strategies", methods=["GET"])
def a_asset_strategies(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    a = get_or_404(store.assets, rid, "asset")
    return list_response(strategies_of_asset(a["id"]), ser_strategy)


@bp.route("/api/assets/<string:rid>/loans", methods=["GET"])
def a_asset_loans(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    a = get_or_404(store.assets, rid, "asset")
    return list_response(loans_of_asset(a["id"]), ser_loan)


@bp.route("/api/assets/<string:rid>/valuations", methods=["GET"])
def a_asset_valuations(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    a = get_or_404(store.assets, rid, "asset")
    return list_response(valuations_of_asset(a["id"]), ser_valuation)


@bp.route("/api/assets/<string:rid>/performance-scorecards", methods=["GET"])
def a_asset_scorecards(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    a = get_or_404(store.assets, rid, "asset")
    return list_response(scorecards_of_asset(a["id"]), ser_scorecard)


@bp.route("/api/assets/<string:rid>/disposition-decisions", methods=["GET"])
def a_asset_decisions(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    a = get_or_404(store.assets, rid, "asset")
    return list_response(decisions_of_asset(a["id"]), ser_decision)
