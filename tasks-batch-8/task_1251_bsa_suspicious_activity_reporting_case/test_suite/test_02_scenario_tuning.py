"""Scenario lifecycle and threshold tuning: state gating, window overlap,
OCC on proposals, version pinning, segregation of duties (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    assert_scenario,
    assert_threshold,
    create_active_scenario,
    create_scenario,
    create_staff,
    generate_alert,
    post_cash_deposits,
    create_account,
    create_customer,
    propose_threshold,
    get_success_data,
    make_manager_headers,
    propose_threshold_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_threshold_activation_rejected_while_scenario_suspended(api):
    """PRD §3.2: "Activation by a `BSAManager` requires the parent scenario to
    be `ACTIVE` (otherwise `ERR_SCENARIO_NOT_ACTIVE`) and, when a currently
    `ACTIVE` version exists, requires the new version's `effective_from` to be
    no earlier than the current active version's `effective_from`."

    Design: Difficulty/cross_entity_state_dependency/threshold_activate_gated_by_scenario_state
    """
    staff = create_staff()
    scenario = create_scenario(
        staff, scenario_code="VELOCITY-WIRE-1D", name="Wire velocity 1d",
        applies_to_txn_types=["WIRE_OUT"], direction_filter="DEBIT")
    threshold = propose_threshold(
        staff, scenario, threshold_amount_cents=5_000_000, lookback_days=1,
        min_transaction_count=5, weight_amount=0.5, weight_velocity=0.4,
        weight_geo=0.1)
    validate_success(api.approve_threshold(threshold["id"], staff.manager), 200)
    validate_success(api.activate_scenario(scenario["id"], staff.manager), 200)
    suspended = validate_success(api.suspend_scenario(scenario["id"], staff.manager), 200)
    assert suspended["status"] == "SUSPENDED"

    res = api.activate_threshold(threshold["id"], staff.manager)
    validate_error(res, ApiErrorId.ERR_SCENARIO_NOT_ACTIVE)
    assert res.status_code == 409
    versions, _meta = validate_paginated(
        api.list_thresholds(scenario["id"], staff.admin))
    assert versions[0]["status"] == "APPROVED", (
        "the rejected activation must leave the threshold APPROVED"
    )


def test_threshold_activation_succeeds_after_scenario_resumed(api):
    """PRD §3.2: "An `ACTIVE` scenario may be suspended (which blocks evaluation
    while suspended, moving the scenario to `SUSPENDED`) and later reactivated"
    PRD §3.2: "the scenario's `current_active_threshold_id` is re-pointed to the
    new version while the scenario's `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/threshold_activate_gated_by_scenario_state
    """
    staff = create_staff()
    scenario = create_scenario(
        staff, scenario_code="VELOCITY-WIRE-1D", name="Wire velocity 1d",
        applies_to_txn_types=["WIRE_OUT"], direction_filter="DEBIT")
    threshold = propose_threshold(
        staff, scenario, threshold_amount_cents=5_000_000, lookback_days=1,
        min_transaction_count=5, weight_amount=0.5, weight_velocity=0.4,
        weight_geo=0.1)
    validate_success(api.approve_threshold(threshold["id"], staff.manager), 200)
    validate_success(api.activate_scenario(scenario["id"], staff.manager), 200)
    validate_success(api.suspend_scenario(scenario["id"], staff.manager), 200)

    resumed = validate_success(api.activate_scenario(scenario["id"], staff.manager), 200)
    assert resumed["status"] == "ACTIVE"
    activated = validate_success(api.activate_threshold(threshold["id"], staff.manager), 200)
    assert_threshold(activated)
    assert activated["status"] == "ACTIVE"
    scenario_after = validate_success(api.get_scenario(scenario["id"], staff.admin), 200)
    assert scenario_after["current_active_threshold_id"] == threshold["id"]


def test_overlapping_threshold_window_proposal_rejected(api):
    """PRD §3.2: "The new version's effective window — half-open, lower bound
    inclusive, upper bound exclusive — must not overlap the effective window of
    any other `PROPOSED` or `APPROVED` version of the same scenario, though
    adjacency is allowed; a violation is `ERR_THRESHOLD_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/threshold_window_half_open_overlap
    """
    staff = create_staff()
    scenario, _v1 = create_active_scenario(staff)
    v2 = propose_threshold(
        staff, scenario, threshold_amount_cents=950_000,
        weight_amount=0.55, weight_velocity=0.3, weight_geo=0.15,
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z",
        tuning_rationale="Summer tuning experiment", backtest_precision=0.78,
        backtest_recall=0.63)
    assert v2["status"] == "PROPOSED"
    scenario = get_success_data(api.get_scenario(scenario["id"], staff.admin))

    res = api.propose_threshold(scenario["id"], propose_threshold_payload(
        scenario["version"], threshold_amount_cents=900_000,
        min_transaction_count=2, weight_amount=0.6, weight_velocity=0.3,
        weight_geo=0.1, effective_from="2026-06-15T00:00:00Z",
        tuning_rationale="Overlapping proposal", backtest_precision=0.7,
        backtest_recall=0.7,
    ), staff.analyst)
    validate_error(res, ApiErrorId.ERR_THRESHOLD_WINDOW_OVERLAP)
    assert res.status_code == 409


def test_adjacent_threshold_window_proposal_accepted(api):
    """PRD §3.2: "The new version's effective window — half-open, lower bound
    inclusive, upper bound exclusive — must not overlap the effective window of
    any other `PROPOSED` or `APPROVED` version of the same scenario, though
    adjacency is allowed; a violation is `ERR_THRESHOLD_WINDOW_OVERLAP`."

    The adjacent proposal reuses the scenario version captured before the
    rejected overlap attempt, proving the rejection did not consume a version.

    Design: Difficulty/resource_temporal_overlap/threshold_window_half_open_overlap
    """
    staff = create_staff()
    scenario, _v1 = create_active_scenario(staff)
    v2 = propose_threshold(
        staff, scenario, threshold_amount_cents=950_000,
        weight_amount=0.55, weight_velocity=0.3, weight_geo=0.15,
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z",
        tuning_rationale="Summer tuning experiment", backtest_precision=0.78,
        backtest_recall=0.63)
    scenario = get_success_data(api.get_scenario(scenario["id"], staff.admin))

    rejected = api.propose_threshold(scenario["id"], propose_threshold_payload(
        scenario["version"], threshold_amount_cents=900_000,
        min_transaction_count=2, weight_amount=0.6, weight_velocity=0.3,
        weight_geo=0.1, effective_from="2026-06-15T00:00:00Z",
        tuning_rationale="Overlapping proposal", backtest_precision=0.7,
        backtest_recall=0.7,
    ), staff.analyst)
    validate_error(rejected, ApiErrorId.ERR_THRESHOLD_WINDOW_OVERLAP)

    adjacent = validate_success(api.propose_threshold(
        scenario["id"], propose_threshold_payload(
            scenario["version"], threshold_amount_cents=900_000,
            min_transaction_count=2, weight_amount=0.6, weight_velocity=0.3,
            weight_geo=0.1, effective_from="2026-07-01T00:00:00Z",
            tuning_rationale="Adjacent proposal starting exactly at v2.effective_to",
            backtest_precision=0.7, backtest_recall=0.7),
        staff.analyst), 201)
    assert_threshold(adjacent)
    assert adjacent["status"] == "PROPOSED"
    assert adjacent["effective_from"] == v2["effective_to"], (
        "the probe starts exactly at the prior version's exclusive upper bound"
    )


def test_stale_threshold_proposal_rejected(api):
    """PRD §2.9: "Proposing a new threshold version against a monitoring
    scenario requires `expected_scenario_version` equal to the scenario's
    current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP
    412)."
    PRD §3.2: "Versions receive a `version_number` assigned per scenario in
    `created_at` order, starting at 1."

    Design: Corner/complexity_layers/threshold_propose_stale_version_rejected
    """
    staff = create_staff()
    scenario = create_scenario(staff)
    stale_version = scenario["version"]
    first = propose_threshold(staff, scenario, effective_to="2026-06-01T00:00:00Z")
    assert first["version_number"] == 1

    res = api.propose_threshold(scenario["id"], propose_threshold_payload(
        stale_version, threshold_amount_cents=950_000,
        weight_amount=0.55, weight_velocity=0.3, weight_geo=0.15,
        effective_from="2026-06-01T00:00:00Z",
        tuning_rationale="Stale-view retune attempt", backtest_precision=0.72,
        backtest_recall=0.61,
    ), staff.analyst)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412

    fresh_version = get_success_data(api.get_scenario(scenario["id"], staff.admin))["version"]
    second = validate_success(api.propose_threshold(
        scenario["id"], propose_threshold_payload(
            fresh_version, threshold_amount_cents=950_000,
            weight_amount=0.55, weight_velocity=0.3, weight_geo=0.15,
            effective_from="2026-06-01T00:00:00Z",
            tuning_rationale="Fresh-view retune", backtest_precision=0.72,
            backtest_recall=0.61),
        staff.analyst), 201)
    assert second["status"] == "PROPOSED"
    assert second["version_number"] == 2


def test_alert_pins_generating_threshold_version(api):
    """PRD §3.3: "The threshold id is pinned at generation and never re-pointed,
    so historical alerts always show the weights that produced them."
    PRD §3.2: "On activation, the prior `ACTIVE` version (if any) transitions to
    `SUPERSEDED` with its `effective_to` overwritten to the new version's
    `effective_from` — half-open adjacency is thus maintained — and the
    scenario's `current_active_threshold_id` is re-pointed to the new version
    while the scenario's `version` increments by 1."

    Design: Corner/complexity_layers/alert_pins_generating_threshold_version
    """
    staff = create_staff()
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-8603")
    scenario, v1 = create_active_scenario(staff)
    post_cash_deposits(staff, account["id"], [
        (400_000, "2026-04-28T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-04-29T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-04-30T10:00:00Z", "US", "ATM"),
    ])
    alert = generate_alert(staff, scenario["id"], account["id"], "2026-05-01T00:00:00Z")
    assert alert["scenario_threshold_id"] == v1["id"]

    scenario = get_success_data(api.get_scenario(scenario["id"], staff.admin))
    v2 = propose_threshold(
        staff, scenario, threshold_amount_cents=900_000, min_transaction_count=2,
        weight_amount=0.6, weight_velocity=0.3, weight_geo=0.1,
        effective_from="2026-06-01T00:00:00Z",
        tuning_rationale="Tightened after review", backtest_precision=0.8,
        backtest_recall=0.7)
    validate_success(api.approve_threshold(v2["id"], staff.manager), 200)
    validate_success(api.activate_threshold(v2["id"], staff.manager), 200)

    alert_after = validate_success(api.get_alert(alert["id"], staff.analyst), 200)
    assert alert_after["scenario_threshold_id"] == v1["id"], (
        "the alert must stay pinned to the threshold version that generated it"
    )
    versions, _meta = validate_paginated(
        api.list_thresholds(scenario["id"], staff.analyst))
    assert versions[0]["id"] == v1["id"]
    assert versions[0]["status"] == "SUPERSEDED"
    assert_same_instant(versions[0]["effective_to"], "2026-06-01T00:00:00Z")
    scenario_after = validate_success(api.get_scenario(scenario["id"], staff.admin), 200)
    assert scenario_after["current_active_threshold_id"] == v2["id"]


def test_retired_scenario_cannot_be_reactivated(api):
    """PRD §3.2: "either `ACTIVE` or `SUSPENDED` may be retired into the
    terminal `RETIRED` state — but retirement is blocked with
    `ERR_SCENARIO_HAS_OPEN_ALERTS` while any alert of the scenario sits in `NEW`
    or `UNDER_TRIAGE`."

    Design: Corner/state_machines/retired_scenario_activate_rejected
    """
    staff = create_staff()
    scenario = create_scenario(staff)
    threshold = propose_threshold(staff, scenario)
    validate_success(api.approve_threshold(threshold["id"], staff.manager), 200)
    validate_success(api.activate_scenario(scenario["id"], staff.manager), 200)
    retired = validate_success(api.retire_scenario(scenario["id"], staff.manager), 200)
    assert_scenario(retired)
    assert retired["status"] == "RETIRED"

    res = api.activate_scenario(scenario["id"], staff.manager)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert res.status_code == 409
    after = validate_success(api.get_scenario(scenario["id"], staff.admin), 200)
    assert after["status"] == "RETIRED"


def test_threshold_approval_by_proposer_rejected(api):
    """PRD §3.2: "Approval by a `BSAManager` is segregation-gated against
    `proposed_by_analyst_id` and stamps `approved_by_analyst_id`."
    PRD §2.1: "On each, the caller's `X-User-ID` must differ from the actor who
    performed the prior step (the proposer, the drafter, or the assigned analyst
    as applicable), or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    Design: Corner/rbac/sod_threshold_approve_by_proposer_rejected
    """
    staff = create_staff()
    scenario = create_scenario(staff)
    threshold = propose_threshold(staff, scenario)

    proposer_as_manager = make_manager_headers(staff.analyst_id)
    res = api.approve_threshold(threshold["id"], proposer_as_manager)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert res.status_code == 403
    versions, _meta = validate_paginated(
        api.list_thresholds(scenario["id"], staff.admin))
    assert versions[0]["status"] == "PROPOSED"
