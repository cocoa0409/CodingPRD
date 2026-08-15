"""Routes: logical clock, stress scenarios, projection runs, liquid assets,
HQLA summary, funding sources and funding evaluations."""
from flask import Blueprint, g, request

from db import mint_id, store
from errors import (
    ApiError,
    ERR_DUPLICATE_ACTIVE_SCENARIO,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LAST_BASELINE_SCENARIO,
    ERR_NOT_FOUND,
    ERR_SCENARIO_IN_USE,
    ERR_SCENARIO_RETIRED,
    ERR_STALE_VERSION,
)
from helpers import (
    MISSING,
    fmt_dt,
    get_json_body,
    new_entity,
    opt_int,
    paginate,
    parse_dt,
    pub,
    req_date,
    req_enum,
    req_int,
    req_str,
    sorted_by_created,
    touch,
)
from middleware import BIZ4, require_roles
from responses import ok, ok_list
from services import (
    compute_projection,
    detect_breaches,
    funding_concentration,
    hqla_adjusted_total,
)

bp = Blueprint("core", __name__)

TIERS = ("BASELINE", "MODERATE", "SEVERE")
MODEL_VARIANTS = ("CONTRACTUAL", "BEHAVIORAL")
ASSET_CLASSES = ("LEVEL_1", "LEVEL_2A", "LEVEL_2B")
CHANNELS = ("RETAIL_DEPOSIT", "WHOLESALE_UNSECURED", "WHOLESALE_SECURED", "BROKERED")
HAIRCUT_BPS = {"LEVEL_1": 0, "LEVEL_2A": 1500, "LEVEL_2B": 2500}


def _get_or_404(table, entity_id, label):
    ent = table.get(entity_id)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{label} not found: {entity_id}")
    return ent


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------
@bp.post("/liquidity/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    body = get_json_body(required=True)
    raw = body.get("to_iso8601", MISSING)
    if raw is MISSING:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field to_iso8601 must be an ISO-8601 datetime.")
    store.clock = dt
    return ok({"current_utc": fmt_dt(store.clock)})


# ---------------------------------------------------------------------------
# Stress scenarios
# ---------------------------------------------------------------------------
@bp.post("/liquidity/stress-scenarios")
@require_roles("RiskOfficer")
def create_scenario():
    body = get_json_body(required=True)
    name = req_str(body, "name")
    tier = req_enum(body, "tier", TIERS)
    runoff = req_int(body, "deposit_runoff_pct", 0, 100)
    renewal = req_int(body, "wholesale_renewal_pct", 0, 100)
    addon = req_int(body, "level2_addon_bps", 0, 10000)
    horizon = req_int(body, "horizon_days", 1, 365)
    if any(s["tier"] == tier and s["status"] == "ACTIVE" for s in store.scenarios.values()):
        raise ApiError(
            ERR_DUPLICATE_ACTIVE_SCENARIO, 409,
            f"An ACTIVE StressScenario already exists for tier {tier}.")
    ent = new_entity({
        "id": mint_id(),
        "name": name,
        "tier": tier,
        "deposit_runoff_pct": runoff,
        "wholesale_renewal_pct": renewal,
        "level2_addon_bps": addon,
        "horizon_days": horizon,
        "status": "ACTIVE",
        "run_count": 0,
    })
    store.scenarios[ent["id"]] = ent
    return ok(pub(ent), status=201)


@bp.get("/liquidity/stress-scenarios")
@require_roles(*BIZ4)
def list_scenarios():
    items = list(store.scenarios.values())
    tier = request.args.get("tier")
    status = request.args.get("status")
    if tier is not None:
        items = [s for s in items if s["tier"] == tier]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(s) for s in page], pagination)


@bp.get("/liquidity/stress-scenarios/<scenario_id>")
@require_roles(*BIZ4)
def get_scenario(scenario_id):
    return ok(pub(_get_or_404(store.scenarios, scenario_id, "StressScenario")))


@bp.post("/liquidity/stress-scenarios/<scenario_id>/retire")
@require_roles("RiskOfficer")
def retire_scenario(scenario_id):
    sc = _get_or_404(store.scenarios, scenario_id, "StressScenario")
    if sc["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Scenario is not ACTIVE.")
    if sc["tier"] == "BASELINE":
        others = [
            s for s in store.scenarios.values()
            if s["id"] != sc["id"] and s["tier"] == "BASELINE" and s["status"] == "ACTIVE"
        ]
        if not others:
            raise ApiError(
                ERR_LAST_BASELINE_SCENARIO, 409,
                "The last ACTIVE BASELINE scenario cannot be retired.")
    if any(r["scenario_id"] == sc["id"] and r["status"] == "DRAFT" for r in store.runs.values()):
        raise ApiError(
            ERR_SCENARIO_IN_USE, 409,
            "Scenario has a DRAFT ProjectionRun and cannot be retired.")
    sc["status"] = "RETIRED"
    touch(sc)
    return ok(pub(sc))


# ---------------------------------------------------------------------------
# Projection runs
# ---------------------------------------------------------------------------
@bp.get("/liquidity/stress-scenarios/<scenario_id>/projection-runs")
@require_roles(*BIZ4)
def list_runs(scenario_id):
    _get_or_404(store.scenarios, scenario_id, "StressScenario")
    items = [r for r in store.runs.values() if r["scenario_id"] == scenario_id]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(r) for r in page], pagination)


@bp.post("/liquidity/stress-scenarios/<scenario_id>/projection-runs")
@require_roles("TreasuryAnalyst")
def create_run(scenario_id):
    sc = _get_or_404(store.scenarios, scenario_id, "StressScenario")
    body = get_json_body(required=True)
    variant = req_enum(body, "model_variant", MODEL_VARIANTS)
    as_of = req_date(body, "as_of_date")
    expected = req_int(body, "expected_scenario_version")
    # OCC (priority 5) precedes the scenario-status gate (priority 7).
    if expected != sc["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_scenario_version does not match the scenario's current version.")
    if sc["status"] != "ACTIVE":
        raise ApiError(ERR_SCENARIO_RETIRED, 409, "Scenario is RETIRED.")
    # Create-with-supersede: discard the existing DRAFT for (scenario, variant).
    for r in store.runs.values():
        if (
            r["scenario_id"] == sc["id"]
            and r["model_variant"] == variant
            and r["status"] == "DRAFT"
        ):
            r["status"] = "DISCARDED"
            touch(r)
    ent = new_entity({
        "id": mint_id(),
        "scenario_id": sc["id"],
        "model_variant": variant,
        "as_of_date": as_of,
        "horizon_days": sc["horizon_days"],
        "status": "DRAFT",
        "total_inflows_cents": 0,
        "total_outflows_cents": 0,
        "net_cumulative_gap_cents": 0,
        "hqla_available_cents": 0,
        "survival_days": 0,
        "finalized_at": None,
    })
    store.runs[ent["id"]] = ent
    sc["run_count"] += 1
    touch(sc)
    return ok(pub(ent), status=201)


@bp.get("/liquidity/projection-runs/<run_id>")
@require_roles(*BIZ4)
def get_run(run_id):
    return ok(pub(_get_or_404(store.runs, run_id, "ProjectionRun")))


@bp.post("/liquidity/projection-runs/<run_id>/finalize")
@require_roles("TreasuryAnalyst")
def finalize_run(run_id):
    run = _get_or_404(store.runs, run_id, "ProjectionRun")
    if run["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "ProjectionRun is not DRAFT.")
    sc = store.scenarios.get(run["scenario_id"])
    if sc is None:
        raise ApiError(ERR_NOT_FOUND, 404, "StressScenario not found.")
    if sc["status"] != "ACTIVE":
        raise ApiError(ERR_SCENARIO_RETIRED, 409, "Scenario is RETIRED.")
    results = compute_projection(run, sc)
    run.update(results)
    run["status"] = "FINALIZED"
    run["finalized_at"] = fmt_dt(store.clock)
    run["_final_seq"] = store.next_seq()
    touch(run)
    # Supersede prior FINALIZED runs for the same (scenario, variant).
    for r in store.runs.values():
        if (
            r["id"] != run["id"]
            and r["scenario_id"] == run["scenario_id"]
            and r["model_variant"] == run["model_variant"]
            and r["status"] == "FINALIZED"
        ):
            r["status"] = "SUPERSEDED"
            touch(r)
    # SURVIVAL_DAYS breach detection.
    detect_breaches(
        {"SURVIVAL_DAYS"},
        {"SURVIVAL_DAYS": run["survival_days"]},
        "PROJECTION_FINALIZE",
        run["id"],
    )
    return ok(pub(run))


# ---------------------------------------------------------------------------
# Liquid assets
# ---------------------------------------------------------------------------
@bp.post("/liquidity/liquid-assets")
@require_roles("TreasuryOps")
def create_asset():
    body = get_json_body(required=True)
    asset_class = req_enum(body, "asset_class", ASSET_CLASSES)
    reference = req_str(body, "reference")
    mv = req_int(body, "market_value_cents", min_v=1)
    ent = new_entity({
        "id": mint_id(),
        "asset_class": asset_class,
        "reference": reference,
        "market_value_cents": mv,
        "haircut_bps": HAIRCUT_BPS[asset_class],
        "encumbrance_status": "UNENCUMBERED",
    })
    store.assets[ent["id"]] = ent
    return ok(pub(ent), status=201)


@bp.get("/liquidity/liquid-assets")
@require_roles(*BIZ4)
def list_assets():
    items = list(store.assets.values())
    asset_class = request.args.get("asset_class")
    encumbrance = request.args.get("encumbrance_status")
    if asset_class is not None:
        items = [a for a in items if a["asset_class"] == asset_class]
    if encumbrance is not None:
        items = [a for a in items if a["encumbrance_status"] == encumbrance]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(a) for a in page], pagination)


@bp.patch("/liquidity/liquid-assets/<asset_id>")
@require_roles("TreasuryOps")
def reprice_asset(asset_id):
    asset = _get_or_404(store.assets, asset_id, "LiquidAsset")
    body = get_json_body(required=True)
    asset["market_value_cents"] = req_int(body, "market_value_cents", min_v=1)
    touch(asset)
    return ok(pub(asset))


@bp.get("/liquidity/hqla-summary")
@require_roles(*BIZ4)
def hqla_summary():
    scenario_id = request.args.get("scenario_id")
    if scenario_id is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required query parameter: scenario_id")
    sc = store.scenarios.get(scenario_id)
    if sc is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"StressScenario not found: {scenario_id}")
    baseline, count = hqla_adjusted_total(0)
    stress, _ = hqla_adjusted_total(sc["level2_addon_bps"])
    return ok({
        "baseline_total_cents": baseline,
        "stress_total_cents": stress,
        "asset_count": count,
    })


# ---------------------------------------------------------------------------
# Funding sources and concentration evaluations
# ---------------------------------------------------------------------------
@bp.post("/liquidity/funding-sources")
@require_roles("TreasuryAnalyst")
def create_funding_source():
    body = get_json_body(required=True)
    name = req_str(body, "counterparty_name")
    channel = req_enum(body, "channel", CHANNELS)
    balance = req_int(body, "balance_cents", min_v=1)
    matures = opt_int(body, "matures_in_days", default=None, min_v=0, allow_null=True)
    ent = new_entity({
        "id": mint_id(),
        "counterparty_name": name,
        "channel": channel,
        "balance_cents": balance,
        "matures_in_days": matures,
    })
    store.funding_sources[ent["id"]] = ent
    return ok(pub(ent), status=201)


@bp.post("/liquidity/funding-evaluations")
@require_roles("RiskOfficer")
def funding_evaluation():
    total, wholesale_bps, top_bps, top_name = funding_concentration()
    created = detect_breaches(
        {"WHOLESALE_RELIANCE_PCT", "TOP_COUNTERPARTY_PCT"},
        {
            "WHOLESALE_RELIANCE_PCT": wholesale_bps,
            "TOP_COUNTERPARTY_PCT": top_bps,
        },
        "FUNDING_EVALUATION",
        None,
    )
    # Computed read: creates no resource, so 200 per PRD §4 status rule.
    return ok({
        "total_funding_cents": total,
        "wholesale_reliance_bps": wholesale_bps,
        "top_counterparty_bps": top_bps,
        "top_counterparty_name": top_name,
        "breaches_created": created,
    })
