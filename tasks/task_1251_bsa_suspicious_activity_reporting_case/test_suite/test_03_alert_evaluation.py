"""Alert generation: dual-variant scoring, pinned rounding order, trigger
boundaries, input-set filtering, idempotency (PRD §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_alert,
    create_account,
    create_active_scenario,
    create_customer,
    create_staff,
    evaluate_payload,
    generate_alert,
    post_cash_deposits,
    post_transaction,
    set_clock,
    setup_alert_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

# Deposits for the tuned-vs-baseline divergence: aggregate 1,000,000 cents over
# 3 in-window cash credits, exactly one with a high-risk counterparty country.
DIVERGE_DEPOSITS = [[
    (400_000, "2026-05-04T10:00:00Z", "US", "BRANCH"),
    (400_000, "2026-05-05T10:00:00Z", "US", "BRANCH"),
    (200_000, "2026-05-06T10:00:00Z", "IR", "ONLINE"),
]]

# Deposits for the rounding-order probe: aggregate 1,033,320 over 3 cash
# credits, one high-risk counterparty.
ROUNDING_DEPOSITS = [[
    (400_000, "2026-05-04T10:00:00Z", "US", "BRANCH"),
    (400_000, "2026-05-05T10:00:00Z", "US", "ATM"),
    (233_320, "2026-05-06T10:00:00Z", "IR", "BRANCH"),
]]


def _divergence_scenario(staff):
    return setup_alert_scenario(
        staff,
        deposits_per_account=DIVERGE_DEPOSITS,
        evaluated_at=None,  # evaluate at the logical clock (moved to 2026-05-10)
        scenario_overrides={
            "baseline_weight_amount": 0.5,
            "baseline_weight_velocity": 0.3,
            "baseline_weight_geo": 0.2,
            "stale_alert_days": 30,
        },
        threshold_overrides={
            "weight_amount": 0.6, "weight_velocity": 0.25, "weight_geo": 0.15,
            "tuning_rationale": "Raised amount weight after Q1 backtest",
            "backtest_precision": 0.81, "backtest_recall": 0.66,
        },
    )


def test_alert_risk_score_uses_tuned_threshold_weights(api):
    """PRD §2.7: "The `risk_score` is the tuned variant: it uses the weights
    `weight_amount`, `weight_velocity`, `weight_geo` from the
    `ScenarioThreshold` version that was `ACTIVE` at generation time."
    PRD §2.7: "Each component contribution is then computed by multiplying its
    weight by its ratio and rounding the product half-up to four decimal
    places. The three rounded contributions are summed, the sum is scaled by
    100, and the result is rounded half-up to an integer."

    Pinned arithmetic: round4(0.6*0.5)+round4(0.25*0.5)+round4(0.15/3)
    = 0.3000+0.1250+0.0500 = 0.4750 -> 47.5 -> 48.

    Design: Difficulty/dual_variant_calc/alert_score_tuned_vs_baseline_diverge
    """
    staff = create_staff()
    set_clock(staff, "2026-05-10T00:00:00Z")
    built = _divergence_scenario(staff)
    alert = validate_success(api.get_alert(built.alerts[0]["id"], staff.analyst), 200)
    assert_alert(alert)
    assert alert["risk_score"] == 48, (
        f"tuned score must be 48 under weights 0.6/0.25/0.15, got {alert['risk_score']}"
    )
    assert alert["scenario_threshold_id"] == built.threshold["id"], (
        "the threshold id is pinned at generation"
    )
    assert alert["status"] == "NEW"


def test_alert_baseline_score_uses_scenario_baseline_weights(api):
    """PRD §2.7: "The `baseline_score` is the shadow variant: it uses the
    scenario's `baseline_weight_amount`, `baseline_weight_velocity`,
    `baseline_weight_geo` so tuning teams can compare a proposed model against
    the baseline on identical inputs."
    PRD §3.3: "When the trigger fires, an `Alert` is created with ... the
    `aggregate_amount_cents` and `txn_count` measurements, and both the tuned
    `risk_score` and the baseline `baseline_score` per §2.7."

    Baseline arithmetic: 0.2500+0.1500+0.0667 = 0.4667 -> 46.67 -> 47; the two
    variants stored on the same alert differ by exactly 1.

    Design: Difficulty/dual_variant_calc/alert_score_tuned_vs_baseline_diverge
    """
    staff = create_staff()
    set_clock(staff, "2026-05-10T00:00:00Z")
    built = _divergence_scenario(staff)
    alert = validate_success(api.get_alert(built.alerts[0]["id"], staff.analyst), 200)
    assert alert["baseline_score"] == 47, (
        f"baseline score must be 47 under weights 0.5/0.3/0.2, got {alert['baseline_score']}"
    )
    assert alert["risk_score"] - alert["baseline_score"] == 1
    assert alert["aggregate_amount_cents"] == 1_000_000
    assert alert["txn_count"] == 3


def test_alert_score_component_prerounding(api):
    """PRD §2.7: "This order is normative: each component rounds to four decimal
    places first, only then are they summed and scaled; summing raw components
    and rounding once at the end produces different scores and is
    non-conformant."

    Aggregate 1,033,320 / count 3 / geo 1-of-3 under weights 0.5/0.3/0.2:
    round4(0.5*0.51666)=0.2583, round4(0.3*0.5)=0.1500, round4(0.2/3)=0.0667;
    sum 0.4750 -> 47.50 -> round half-up 48. The forbidden sum-then-round order
    (0.47499666... -> 47.49966...) would yield 47.

    Design: Difficulty/combinatorial_formula/alert_score_component_rounding_order
    """
    staff = create_staff()
    set_clock(staff, "2026-05-10T00:00:00Z")
    built = setup_alert_scenario(
        staff, deposits_per_account=ROUNDING_DEPOSITS, evaluated_at=None)
    alert = validate_success(api.get_alert(built.alerts[0]["id"], staff.analyst), 200)
    assert_alert(alert)
    assert alert["aggregate_amount_cents"] == 1_033_320
    assert alert["txn_count"] == 3
    assert alert["risk_score"] == 48, (
        "the 4dp pre-rounding of the geo component (0.0666... -> 0.0667) must "
        f"push 47.49966... up to 47.50 -> 48; got {alert['risk_score']}"
    )


def test_alert_score_rounding_order_shared_by_both_variants(api):
    """PRD §2.7: "Both variants share one pinned arithmetic procedure."
    PRD §2.7: "The `baseline_score` is the shadow variant: it uses the
    scenario's `baseline_weight_amount`, `baseline_weight_velocity`,
    `baseline_weight_geo` so tuning teams can compare a proposed model against
    the baseline on identical inputs."

    With the tuned weights equal to the baseline weights (0.5/0.3/0.2), both
    stored variants must read 48 — any deviation in either variant breaks the
    shared pinned order.

    Design: Difficulty/combinatorial_formula/alert_score_component_rounding_order
    """
    staff = create_staff()
    set_clock(staff, "2026-05-10T00:00:00Z")
    built = setup_alert_scenario(
        staff, deposits_per_account=ROUNDING_DEPOSITS, evaluated_at=None)
    alert = validate_success(api.get_alert(built.alerts[0]["id"], staff.analyst), 200)
    assert alert["risk_score"] == 48
    assert alert["baseline_score"] == 48, (
        "baseline weights equal the tuned weights here, so both variants must "
        f"agree at 48; got baseline {alert['baseline_score']}"
    )


class TestEvaluateTriggerBoundaries:
    """PRD §3.3: "An alert fires when both the aggregate amount in cents is at
    least `threshold_amount_cents` and the matched count is at least
    `min_transaction_count`; both comparisons are inclusive."
    """

    def _build(self, staff):
        """Build the three probe accounts without generating alerts, so each
        test drives its own evaluation."""
        set_clock(staff, "2026-05-10T00:00:00Z")
        customer = create_customer(staff)
        scenario, threshold = create_active_scenario(staff)
        acc_exact = create_account(staff, customer["id"], "ACC-6101")
        acc_below = create_account(staff, customer["id"], "ACC-6102")
        acc_count = create_account(staff, customer["id"], "ACC-6103")
        post_cash_deposits(staff, acc_exact["id"], [
            (400_000, "2026-05-04T10:00:00Z", "US", "BRANCH"),
            (400_000, "2026-05-05T10:00:00Z", "US", "BRANCH"),
            (200_000, "2026-05-06T10:00:00Z", "US", "ATM"),
        ])
        post_cash_deposits(staff, acc_below["id"], [
            (400_000, "2026-05-04T10:00:00Z", "US", "BRANCH"),
            (400_000, "2026-05-05T10:00:00Z", "US", "BRANCH"),
            (199_999, "2026-05-06T10:00:00Z", "US", "ATM"),
        ])
        post_cash_deposits(staff, acc_count["id"], [
            (600_000, "2026-05-04T10:00:00Z", "US", "BRANCH"),
            (500_000, "2026-05-05T10:00:00Z", "US", "BRANCH"),
        ])
        return scenario, threshold, acc_exact, acc_below, acc_count

    def test_aggregate_exactly_at_threshold_fires(self, api):
        """PRD §3.3: "An alert fires when both the aggregate amount in cents is
        at least `threshold_amount_cents` and the matched count is at least
        `min_transaction_count`; both comparisons are inclusive."

        Design: Difficulty/boundary_precision_check/evaluate_threshold_amount_exact_boundary
        """
        staff = create_staff()
        scenario, _th, acc_exact, _b, _c = self._build(staff)
        result = validate_success(api.evaluate_scenario(
            scenario["id"], evaluate_payload(acc_exact["id"]), staff.admin), 200)
        assert result["alert_created"] is True, (
            "aggregate == threshold exactly must fire (the >= boundary is inclusive)"
        )
        alert = validate_success(api.get_alert(result["alert_id"], staff.analyst), 200)
        assert alert["aggregate_amount_cents"] == 1_000_000
        assert alert["txn_count"] == 3

    def test_aggregate_one_cent_below_threshold_stays_silent(self, api):
        """PRD §3.3: "An alert fires when both the aggregate amount in cents is
        at least `threshold_amount_cents` and the matched count is at least
        `min_transaction_count`; both comparisons are inclusive."

        Design: Difficulty/boundary_precision_check/evaluate_threshold_amount_exact_boundary
        """
        staff = create_staff()
        scenario, _th, _a, acc_below, _c = self._build(staff)
        result = validate_success(api.evaluate_scenario(
            scenario["id"], evaluate_payload(acc_below["id"]), staff.admin), 200)
        assert result["alert_created"] is False, (
            "999,999 cents is one cent below the inclusive 1,000,000 boundary"
        )
        data, meta = validate_paginated(api.list_alerts(
            staff.analyst, params={"account_id": acc_below["id"]}))
        assert data == [] and meta["total_count"] == 0

    def test_count_below_minimum_stays_silent_despite_amount(self, api):
        """PRD §3.3: "An alert fires when both the aggregate amount in cents is
        at least `threshold_amount_cents` and the matched count is at least
        `min_transaction_count`; both comparisons are inclusive."

        Design: Difficulty/boundary_precision_check/evaluate_threshold_amount_exact_boundary
        """
        staff = create_staff()
        scenario, _th, _a, _b, acc_count = self._build(staff)
        result = validate_success(api.evaluate_scenario(
            scenario["id"], evaluate_payload(acc_count["id"]), staff.admin), 200)
        assert result["alert_created"] is False, (
            "aggregate 1,100,000 meets the amount threshold but the count 2 is "
            "below the inclusive count boundary 3"
        )
        data, meta = validate_paginated(api.list_alerts(
            staff.analyst, params={"account_id": acc_count["id"]}))
        assert data == [] and meta["total_count"] == 0


def test_evaluation_matches_only_type_direction_and_window(api):
    """PRD §3.3: "The matched set is every transaction of the target account
    whose `txn_type` appears in `applies_to_txn_types`, whose `direction`
    matches `direction_filter` (with `BOTH` matching everything), and whose
    `posted_at` falls inside the window."

    Design: Corner/calculations/alert_evaluation_input_set_filtering
    """
    staff = create_staff()
    set_clock(staff, "2026-05-10T00:00:00Z")
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-8301")
    scenario, _th = create_active_scenario(staff)
    post_cash_deposits(staff, account["id"], [
        (400_000, "2026-05-04T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-05-05T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-05-06T10:00:00Z", "US", "ATM"),
    ])
    # Distractors: wrong direction, wrong type, and exactly on the
    # window-exclusive start bound.
    post_transaction(staff, account["id"], amount_cents=900_000,
                     direction="DEBIT", posted_at="2026-05-05T11:00:00Z")
    post_transaction(staff, account["id"], amount_cents=900_000,
                     txn_type="WIRE_IN", posted_at="2026-05-05T12:00:00Z",
                     channel="WIRE_DESK")
    post_transaction(staff, account["id"], amount_cents=900_000,
                     posted_at="2026-05-03T00:00:00Z")

    alert = generate_alert(staff, scenario["id"], account["id"], None)
    assert alert["aggregate_amount_cents"] == 1_200_000, (
        "DEBIT, WIRE_IN, and window-start-boundary transactions are all excluded"
    )
    assert alert["txn_count"] == 3


def test_evaluation_window_excludes_start_includes_end(api):
    """PRD §3.3: "The window is the half-open interval from `evaluated_at` minus
    `lookback_days` (exclusive) up to and including `evaluated_at`."

    A 200,000-cent deposit posted exactly at the window end counts; a
    500,000-cent deposit posted exactly at the window start does not. Only the
    (start, end] reading yields aggregate 1,000,000 over 3 transactions.

    Design: Corner/calculations/evaluation_window_exclusive_start_inclusive_end
    """
    staff = create_staff()
    set_clock(staff, "2026-05-10T00:00:00Z")
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-8302")
    scenario, _th = create_active_scenario(staff)
    post_cash_deposits(staff, account["id"], [
        (400_000, "2026-05-05T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-05-06T10:00:00Z", "US", "BRANCH"),
        (200_000, "2026-05-10T00:00:00Z", "US", "ATM"),   # window_end: included
        (500_000, "2026-05-03T00:00:00Z", "US", "BRANCH"),  # window_start: excluded
    ])
    alert = generate_alert(staff, scenario["id"], account["id"], None)
    assert alert["aggregate_amount_cents"] == 1_000_000
    assert alert["txn_count"] == 3


def test_evaluation_idempotent_per_window(api):
    """PRD §3.3: "Evaluation is idempotent per (scenario, account, window-end)
    triple: a repeat evaluation of the same triple returns the existing alert
    with `alert_created` false rather than minting a duplicate."

    Design: Corner/endpoints/evaluate_idempotent_same_window
    """
    staff = create_staff()
    set_clock(staff, "2026-05-10T00:00:00Z")
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-8401")
    scenario, _th = create_active_scenario(staff)
    post_cash_deposits(staff, account["id"], [
        (400_000, "2026-05-04T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-05-05T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-05-06T10:00:00Z", "US", "ATM"),
    ])
    first = validate_success(api.evaluate_scenario(
        scenario["id"], evaluate_payload(account["id"]), staff.admin), 200)
    assert first["alert_created"] is True
    second = validate_success(api.evaluate_scenario(
        scenario["id"], evaluate_payload(account["id"]), staff.admin), 200)
    assert second["alert_created"] is False
    assert second["alert_id"] == first["alert_id"], (
        "the repeat evaluation must return the existing alert, not a duplicate"
    )
    data, meta = validate_paginated(api.list_alerts(
        staff.analyst, params={"account_id": account["id"]}))
    assert len(data) == 1 and meta["total_count"] == 1


def test_evaluate_without_active_threshold_rejected(api):
    """PRD §3.3: "The evaluation requires the scenario to be `ACTIVE` (else
    `ERR_SCENARIO_NOT_ACTIVE`) and to have a currently `ACTIVE` threshold
    version (else `ERR_NO_ACTIVE_THRESHOLD`)."

    Design: Corner/errors/evaluate_without_active_threshold_rejected
    """
    staff = create_staff()
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-8501")
    # Scenario ACTIVE with a threshold that is APPROVED but never activated.
    scenario, _threshold = create_active_scenario(staff, activate_threshold=False)
    post_cash_deposits(staff, account["id"], [
        (400_000, "2026-04-28T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-04-29T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-04-30T10:00:00Z", "US", "ATM"),
    ])
    res = api.evaluate_scenario(
        scenario["id"], evaluate_payload(account["id"], "2026-05-01T00:00:00Z"),
        staff.admin)
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_THRESHOLD)
    assert res.status_code == 409
    data, meta = validate_paginated(api.list_alerts(
        staff.analyst, params={"scenario_id": scenario["id"]}))
    assert data == [] and meta["total_count"] == 0


def test_evaluate_while_scenario_suspended_rejected(api):
    """PRD §3.3: "The evaluation requires the scenario to be `ACTIVE` (else
    `ERR_SCENARIO_NOT_ACTIVE`) and to have a currently `ACTIVE` threshold
    version (else `ERR_NO_ACTIVE_THRESHOLD`)."
    PRD §3.2: "An `ACTIVE` scenario may be suspended (which blocks evaluation
    while suspended, moving the scenario to `SUSPENDED`)".

    Design: Corner/errors/evaluate_while_suspended_rejected
    """
    staff = create_staff()
    customer = create_customer(staff)
    account = create_account(staff, customer["id"], "ACC-8502")
    scenario, _threshold = create_active_scenario(staff)
    post_cash_deposits(staff, account["id"], [
        (400_000, "2026-04-28T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-04-29T10:00:00Z", "US", "BRANCH"),
        (400_000, "2026-04-30T10:00:00Z", "US", "ATM"),
    ])
    validate_success(api.suspend_scenario(scenario["id"], staff.manager), 200)
    res = api.evaluate_scenario(
        scenario["id"], evaluate_payload(account["id"], "2026-05-01T00:00:00Z"),
        staff.admin)
    validate_error(res, ApiErrorId.ERR_SCENARIO_NOT_ACTIVE)
    assert res.status_code == 409
    data, meta = validate_paginated(api.list_alerts(
        staff.analyst, params={"scenario_id": scenario["id"]}))
    assert data == [] and meta["total_count"] == 0

