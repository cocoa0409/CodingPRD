"""Composite setup helpers.

Most testable claims require the system to be in a state that takes several
API calls to reach (scenario + line + pledged asset + tested/approved/
activated playbook, or metrics holding specific bands). These builders
encapsulate those chains so tests focus on assertions.

All builders use get_success_data() so setup failures surface as clear
"Setup step failed" errors. The SoD anchors (created_by_user_id,
acknowledged_by_user_id) are threaded explicitly: playbooks are created with
the `creator` user id and approved by `approver` (PRD §3.9 SoD gate).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .constants import AS_OF_DATE, READING_T1, READING_T2
from .factories import (
    create_action_payload,
    create_board_limit_payload,
    create_borrowing_line_payload,
    create_ewi_metric_payload,
    create_funding_source_payload,
    create_intraday_snapshot_payload,
    create_liquid_asset_payload,
    create_playbook_payload,
    create_projection_run_payload,
    create_reading_payload,
    create_scenario_payload,
)
from .test_users import (
    USER_ANALYST_1,
    USER_COMMITTEE_1,
    USER_OFFICER_1,
    USER_OFFICER_2,
    USER_OPS_1,
    make_analyst_headers,
    make_committee_headers,
    make_officer_headers,
    make_ops_headers,
)

# Header constants for the fixture layer (analyst fixtures always draft as the
# creator id so approve/activate chains pass the SoD gate).
ANALYST = make_analyst_headers(USER_ANALYST_1)
OFFICER = make_officer_headers(USER_OFFICER_1)
OFFICER_2 = make_officer_headers(USER_OFFICER_2)
COMMITTEE = make_committee_headers(USER_COMMITTEE_1)
OPS = make_ops_headers(USER_OPS_1)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def make_scenario(
    name="Scenario",
    tier="BASELINE",
    deposit_runoff_pct=5,
    wholesale_renewal_pct=80,
    level2_addon_bps=0,
    horizon_days=30,
    headers=None,
):
    """Create a scenario (starts ACTIVE, run_count 0)."""
    resp = _api.create_scenario(
        create_scenario_payload(
            name=name,
            tier=tier,
            deposit_runoff_pct=deposit_runoff_pct,
            wholesale_renewal_pct=wholesale_renewal_pct,
            level2_addon_bps=level2_addon_bps,
            horizon_days=horizon_days,
        ),
        headers or OFFICER,
    )
    return get_success_data(resp)


def make_asset(asset_class="LEVEL_1", reference="REF", market_value_cents=1_000_000, headers=None):
    """Register a liquid asset (arrives UNENCUMBERED, class haircut derived)."""
    resp = _api.create_liquid_asset(
        create_liquid_asset_payload(
            asset_class=asset_class,
            reference=reference,
            market_value_cents=market_value_cents,
        ),
        headers or OPS,
    )
    return get_success_data(resp)


def make_line(
    provider_name="Provider",
    line_type="FED_DISCOUNT_WINDOW",
    total_capacity_cents=100_000_000,
    advance_rate_bps=10_000,
    headers=None,
):
    """Establish a borrowing line (ACTIVE, all computed figures zero)."""
    resp = _api.create_borrowing_line(
        create_borrowing_line_payload(
            provider_name=provider_name,
            line_type=line_type,
            total_capacity_cents=total_capacity_cents,
            advance_rate_bps=advance_rate_bps,
        ),
        headers or OPS,
    )
    return get_success_data(resp)


def make_pledge(asset_id, line_id, headers=None):
    """Pledge an UNENCUMBERED asset to an ACTIVE line."""
    resp = _api.create_collateral_pledge(
        {"asset_id": asset_id, "line_id": line_id}, headers or OPS,
    )
    return get_success_data(resp)


def make_funding_source(
    counterparty_name="Counterparty",
    channel="RETAIL_DEPOSIT",
    balance_cents=1_000_000,
    matures_in_days=None,
    headers=None,
):
    """Record a funding source; matures_in_days omitted when None (demand deposit)."""
    payload = create_funding_source_payload(
        counterparty_name=counterparty_name, channel=channel, balance_cents=balance_cents,
    )
    if matures_in_days is not None:
        payload["matures_in_days"] = matures_in_days
    resp = _api.create_funding_source(payload, headers or ANALYST)
    return get_success_data(resp)


def make_metric(
    code="M",
    name="metric",
    unit="PCT_BPS",
    direction="ABOVE_BREACHES",
    amber_threshold=1000,
    red_threshold=5000,
    min_reading_interval_hours=0,
    headers=None,
):
    """Configure an EWI metric (starts GREEN, last_reading_at empty)."""
    resp = _api.create_ewi_metric(
        create_ewi_metric_payload(
            code=code,
            name=name,
            unit=unit,
            direction=direction,
            amber_threshold=amber_threshold,
            red_threshold=red_threshold,
            min_reading_interval_hours=min_reading_interval_hours,
        ),
        headers or OFFICER,
    )
    return get_success_data(resp)


def post_reading(metric_id, value, observed_at=READING_T1, headers=None):
    """Post a metric reading (recomputes band; may trigger auto posture)."""
    resp = _api.post_metric_reading(
        metric_id,
        create_reading_payload(observed_at=observed_at, value=value),
        headers or ANALYST,
    )
    return get_success_data(resp)


def make_board_limit(
    subject="WHOLESALE_RELIANCE_PCT",
    direction="ABOVE_BREACHES",
    limit_value=4000,
    severity="BOARD",
    ewi_metric_id=None,
    headers=None,
):
    """Create a board limit; ewi_metric_id included only when supplied."""
    payload = create_board_limit_payload(
        subject=subject, direction=direction, limit_value=limit_value, severity=severity,
    )
    if ewi_metric_id is not None:
        payload["ewi_metric_id"] = ewi_metric_id
    resp = _api.create_board_limit(payload, headers or OFFICER)
    return get_success_data(resp)


def make_playbook(
    scenario_id,
    name="Playbook",
    min_activation_posture="NORMAL",
    target_capacity_cents=1_000_000,
    creator=USER_ANALYST_1,
):
    """Draft a playbook; created_by_user_id = the creator's X-User-ID."""
    resp = _api.create_playbook(
        create_playbook_payload(
            name=name,
            scenario_id=scenario_id,
            min_activation_posture=min_activation_posture,
            target_capacity_cents=target_capacity_cents,
        ),
        make_analyst_headers(creator),
    )
    return get_success_data(resp)


def add_action(
    playbook_id,
    kind="LINE_DRAWDOWN",
    sequence_no=1,
    estimated_proceeds_cents=1_000_000,
    settlement_lag_days=0,
    asset_id=None,
    line_id=None,
    prerequisite_action_id=None,
    headers=None,
):
    """Add an action to a DRAFT playbook (starts PENDING)."""
    payload = create_action_payload(
        kind=kind,
        sequence_no=sequence_no,
        estimated_proceeds_cents=estimated_proceeds_cents,
        settlement_lag_days=settlement_lag_days,
    )
    if asset_id is not None:
        payload["asset_id"] = asset_id
    if line_id is not None:
        payload["line_id"] = line_id
    if prerequisite_action_id is not None:
        payload["prerequisite_action_id"] = prerequisite_action_id
    resp = _api.add_playbook_action(playbook_id, payload, headers or ANALYST)
    return get_success_data(resp)


def make_projection_run(scenario_id, model_variant, expected_scenario_version,
                        as_of_date=AS_OF_DATE, headers=None):
    """Create a DRAFT projection run under a scenario (OCC on scenario version)."""
    resp = _api.create_projection_run(
        scenario_id,
        create_projection_run_payload(
            model_variant=model_variant,
            as_of_date=as_of_date,
            expected_scenario_version=expected_scenario_version,
        ),
        headers or ANALYST,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: funding and collateral composites
# ---------------------------------------------------------------------------

def setup_line_with_pledge(
    total_capacity_cents=100_000_000,
    advance_rate_bps=10_000,
    asset_class="LEVEL_1",
    market_value_cents=200_000_000,
    line_type="FED_DISCOUNT_WINDOW",
    provider_name="Provider",
    reference="P1",
):
    """Line + one pledged asset. Returns (line, asset, pledge)."""
    line = make_line(
        provider_name=provider_name,
        line_type=line_type,
        total_capacity_cents=total_capacity_cents,
        advance_rate_bps=advance_rate_bps,
    )
    asset = make_asset(asset_class=asset_class, reference=reference,
                       market_value_cents=market_value_cents)
    pledge = make_pledge(asset["id"], line["id"])
    return line, asset, pledge


# ---------------------------------------------------------------------------
# Tier 3: playbook lifecycle chains
# ---------------------------------------------------------------------------

def make_tested_playbook(scenario_id, actions, name="Playbook",
                         min_activation_posture="NORMAL",
                         target_capacity_cents=1_000_000,
                         creator=USER_ANALYST_1):
    """DRAFT playbook + actions + passing capacity test. Returns (playbook, action list).

    Each entry in `actions` is a kwargs dict for add_action().
    """
    playbook = make_playbook(
        scenario_id,
        name=name,
        min_activation_posture=min_activation_posture,
        target_capacity_cents=target_capacity_cents,
        creator=creator,
    )
    created = [add_action(playbook["id"], **a) for a in actions]
    resp = _api.run_capacity_test(playbook["id"], OFFICER)
    result = get_success_data(resp)
    assert result["result"] == "PASSED", (
        f"capacity test expected PASSED during setup, got {result['result']}: {result}"
    )
    playbook = get_success_data(_api.get_playbook(playbook["id"], ANALYST))
    return playbook, created


def make_approved_playbook(scenario_id, actions, name="Playbook",
                           min_activation_posture="NORMAL",
                           target_capacity_cents=1_000_000,
                           creator=USER_ANALYST_1,
                           approver=USER_OFFICER_2):
    """TESTED playbook approved by someone other than its creator (SoD gate)."""
    playbook, created = make_tested_playbook(
        scenario_id, actions, name=name,
        min_activation_posture=min_activation_posture,
        target_capacity_cents=target_capacity_cents, creator=creator,
    )
    resp = _api.approve_playbook(playbook["id"], make_officer_headers(approver))
    playbook = get_success_data(resp)
    return playbook, created


def make_activated_playbook(scenario_id, actions, name="Playbook",
                            min_activation_posture="NORMAL",
                            target_capacity_cents=1_000_000,
                            creator=USER_ANALYST_1,
                            approver=USER_OFFICER_2):
    """Fully walked to ACTIVATED (posture gate satisfied; every PENDING action -> READY)."""
    playbook, created = make_approved_playbook(
        scenario_id, actions, name=name,
        min_activation_posture=min_activation_posture,
        target_capacity_cents=target_capacity_cents,
        creator=creator, approver=approver,
    )
    resp = _api.activate_playbook(playbook["id"], COMMITTEE)
    playbook = get_success_data(resp)
    return playbook, created


def setup_active_drawdown_playbook(
    target_capacity_cents=1_000_000,
    draw_amount_cents=1_000_000,
    settlement_lag_days=0,
    min_activation_posture="NORMAL",
    line_capacity_cents=100_000_000,
    advance_rate_bps=10_000,
    pledged_asset_value_cents=200_000_000,
    pledged_asset_class="LEVEL_1",
):
    """Scenario + funded line + ACTIVATED playbook with one READY LINE_DRAWDOWN action.

    Returns dict with scenario, line, asset, pledge, playbook, action.
    """
    scenario = make_scenario(name="Base", tier="BASELINE")
    line, asset, pledge = setup_line_with_pledge(
        total_capacity_cents=line_capacity_cents,
        advance_rate_bps=advance_rate_bps,
        asset_class=pledged_asset_class,
        market_value_cents=pledged_asset_value_cents,
    )
    playbook, actions = make_activated_playbook(
        scenario["id"],
        [{
            "kind": "LINE_DRAWDOWN",
            "sequence_no": 1,
            "estimated_proceeds_cents": draw_amount_cents,
            "settlement_lag_days": settlement_lag_days,
            "line_id": line["id"],
        }],
        min_activation_posture=min_activation_posture,
        target_capacity_cents=target_capacity_cents,
    )
    return {
        "scenario": scenario,
        "line": line,
        "asset": asset,
        "pledge": pledge,
        "playbook": playbook,
        "action": actions[0],
        "actions": actions,
    }


def setup_executing_drawdown(**overrides):
    """ACTIVE playbook whose single drawdown action stands EXECUTING."""
    ctx = setup_active_drawdown_playbook(**overrides)
    resp = _api.execute_playbook_action(ctx["action"]["id"], OPS)
    ctx["action"] = get_success_data(resp)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: posture / breach composites
# ---------------------------------------------------------------------------

def make_metrics_with_bands(specs):
    """Create one metric per spec and post its reading.

    Each spec: {code, value, observed_at?, direction?, amber?, red?, cadence?}.
    Returns list of (metric, reading).
    """
    out = []
    for spec in specs:
        metric = make_metric(
            code=spec["code"],
            name=spec.get("name", spec["code"]),
            unit=spec.get("unit", "PCT_BPS"),
            direction=spec.get("direction", "ABOVE_BREACHES"),
            amber_threshold=spec.get("amber_threshold", 1000),
            red_threshold=spec.get("red_threshold", 5000),
            min_reading_interval_hours=spec.get("min_reading_interval_hours", 0),
        )
        reading = post_reading(
            metric["id"], spec["value"],
            observed_at=spec.get("observed_at", READING_T1),
        )
        out.append((metric, reading))
    return out


def setup_red_metric_with_limit(limit_value=4000, reading_value=6000,
                                amber=1000, red=5000):
    """Metric + EWI_METRIC limit + RED reading.

    The RED band makes breach detection open a breach and the auto posture
    evaluation enters SEVERE, which escalates the fresh OPEN breach in the
    same request. Returns (metric, limit, breach).
    """
    metric = make_metric(code="M", name="m", amber_threshold=amber, red_threshold=red)
    limit = make_board_limit(
        subject="EWI_METRIC", direction="ABOVE_BREACHES", limit_value=limit_value,
        severity="BOARD", ewi_metric_id=metric["id"],
    )
    post_reading(metric["id"], reading_value, observed_at=READING_T1)
    breaches, _meta = _list(_api.list_limit_breaches(limit["id"], OFFICER))
    assert len(breaches) == 1, f"expected exactly one breach, got {len(breaches)}"
    return metric, limit, breaches[0]


def setup_wholesale_breach(limit_value=4000, retail_cents=6_000_000_000,
                           wholesale_sources=(("W1", "WHOLESALE_UNSECURED", 4_000_000_000, 20),
                                              ("W2", "WHOLESALE_SECURED", 1_000_000_000, 8)),
                           acknowledger=USER_OFFICER_1):
    """Funding mix breaching a WHOLESALE_RELIANCE_PCT limit; breach ACKNOWLEDGED.

    Returns (limit, breach).
    """
    limit = make_board_limit(
        subject="WHOLESALE_RELIANCE_PCT", direction="ABOVE_BREACHES",
        limit_value=limit_value, severity="BOARD",
    )
    make_funding_source(counterparty_name="RetailA", channel="RETAIL_DEPOSIT",
                        balance_cents=retail_cents)
    for name, channel, cents, matures in wholesale_sources:
        make_funding_source(counterparty_name=name, channel=channel,
                            balance_cents=cents, matures_in_days=matures)
    evaluation = get_success_data(_api.run_funding_evaluation(OFFICER))
    assert evaluation["breaches_created"] >= 1, "expected at least one breach in setup"
    breaches, _meta = _list(_api.list_limit_breaches(limit["id"], OFFICER))
    assert len(breaches) == 1, f"expected exactly one breach on the limit, got {len(breaches)}"
    breach = breaches[0]
    resp = _api.acknowledge_breach(breach["id"], make_officer_headers(acknowledger))
    breach = get_success_data(resp)
    return limit, breach


def _list(resp):
    """Paginated list helper: returns (data_list, meta)."""
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(resp)
