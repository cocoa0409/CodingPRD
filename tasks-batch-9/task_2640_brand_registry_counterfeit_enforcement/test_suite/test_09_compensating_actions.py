"""Compensating actions and the invariants they must preserve: the test-buy
ledger and the strike ledger behind a rebutted counter notice."""

from test_helpers import (
    ANALYST,
    SELLER_STATUS_UNDER_INVESTIGATION,
    ApiErrorId,
    assert_cents,
    assert_instant_equals,
    assert_metrics,
    assert_seller_strikes,
    authenticate_test_buy,
    create_counter_notice,
    read_brand,
    read_claim,
    read_metrics,
    read_seller,
    read_takedown,
    receive_test_buy,
    resolve_counter_notice,
    set_clock,
    setup_claim,
    setup_removed_takedown,
    setup_second_removal_on_same_seller,
    test_buy_payload,
    validate_error,
    validate_success,
)


def test_cancellation_restores_the_brand_ledger_to_the_cent(api):
    """PRD §3.6: "The brand's `enforcement_spend_cents` has exactly this row's `billable_total_cents` subtracted from it, restoring the ledger to its pre-order value to the cent, and both the test buy and the brand have their `version` incremented by 1."
    PRD §3.6: "Otherwise `billable_total_cents` is added to the brand's `enforcement_spend_cents` and the brand's `version` is incremented by 1."
    PRD §3.6: "Neither authentication branch refunds anything: the purchase genuinely happened, so the brand's `enforcement_spend_cents` is untouched by the verdict."
    PRD §3.6: "`AUTHENTICATED_AUTHENTIC`, `AUTHENTICATED_COUNTERFEIT` and `CANCELLED` are all terminal."

    Design: Difficulty/compensating_invariant/test_buy_cancellation_restores_the_brand_ledger_to_the_cent
    """
    ctx = setup_claim(api, clock="2026-08-05T08:00:00Z")
    baseline = read_brand(api, ctx["brand"]["id"])
    assert_cents(baseline["enforcement_spend_cents"], 0, "enforcement_spend_cents")

    first = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST), 201)
    assert_cents(first["billable_total_cents"], 5635, "billable_total_cents")
    after_first = read_brand(api, ctx["brand"]["id"])
    assert_cents(after_first["enforcement_spend_cents"], 5635, "enforcement_spend_cents")
    assert after_first["version"] == baseline["version"] + 1

    set_clock(api, "2026-08-20T08:00:00Z")
    second = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(20000, 0, 0), headers=ANALYST), 201)
    assert_cents(second["billable_total_cents"], 22400, "billable_total_cents")
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 28035,
                 "enforcement_spend_cents")

    cancelled = validate_success(
        api.cancel_test_buy(second["id"], "NEVER_SHIPPED", headers=ANALYST), 200)
    assert cancelled["status"] == "CANCELLED", f"got {cancelled['status']}"
    assert_cents(cancelled["billable_total_cents"], 22400,
                 "The cancelled row keeps its own pricing")

    restored = read_brand(api, ctx["brand"]["id"])
    assert_cents(restored["enforcement_spend_cents"], 5635,
                 "The ledger returns to its pre-order value to the cent")
    assert restored["version"] == after_first["version"] + 2, (
        f"Order and cancellation each bump the brand, got {restored['version']}")

    receive_test_buy(api, first["id"], "LOT-2026-A", "COC-1")
    authenticate_test_buy(api, first["id"], "COUNTERFEIT", "LAB-1")
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 5635,
                 "No authentication branch refunds anything")


def test_a_cancellation_releases_real_budget_headroom(api):
    """PRD §3.6: "Before the order is accepted, the brand's ledger is checked: the brand's current `enforcement_spend_cents` plus this order's `billable_total_cents` must not exceed the brand's `enforcement_budget_cents`."
    PRD §3.6: "The brand's `enforcement_spend_cents` has exactly this row's `billable_total_cents` subtracted from it, restoring the ledger to its pre-order value to the cent, and both the test buy and the brand have their `version` incremented by 1."
    PRD §3.6: "If it would, the order is refused with `ERR_TEST_BUY_BUDGET_EXCEEDED` (HTTP 402) and nothing is persisted."

    Design: Difficulty/compensating_invariant/test_buy_cancellation_restores_the_brand_ledger_to_the_cent
    """
    ctx = setup_claim(api, clock="2026-08-05T08:00:00Z",
                      brand={"enforcement_budget_cents": 6000})
    first = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4200, 700, 0), headers=ANALYST), 201)
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 5635,
                 "enforcement_spend_cents")

    set_clock(api, "2026-08-20T08:00:00Z")
    over_budget = api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4000, 0, 0), headers=ANALYST)
    validate_error(over_budget, ApiErrorId.TEST_BUY_BUDGET_EXCEEDED, 402)

    validate_success(api.cancel_test_buy(first["id"], "NEVER_SHIPPED", headers=ANALYST), 200)
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 0,
                 "enforcement_spend_cents")

    accepted = validate_success(api.create_test_buy(
        ctx["claim"]["id"], test_buy_payload(4000, 0, 0), headers=ANALYST), 201)
    assert_cents(accepted["billable_total_cents"], 4600, "billable_total_cents")
    assert_cents(read_brand(api, ctx["brand"]["id"])["enforcement_spend_cents"], 4600,
                 "enforcement_spend_cents")


def test_a_rebuttal_closes_the_cycle_without_re_attributing_the_strike(api):
    """PRD §3.8: "On the **rebutted** branch the counter notice moves `FILED → REBUTTED`, `resolved_at` is stamped from the logical clock, `rebuttal_ref` is persisted, and the parent notice returns `COUNTER_NOTICED → APPROVED_REMOVED`, closing the cycle."
    PRD §3.8: "Crucially, the strike attribution is **not** re-run: the original takedown-removal strike was never removed from the ledger while the notice sat in `COUNTER_NOTICED`, so returning to `APPROVED_REMOVED` must not add a second one."
    PRD §3.8: "`counter_notice_deadline_at` is not extended either."
    PRD §3.8: "Both rows have their `version` incremented by 1."

    Design: Difficulty/compensating_invariant/rebutted_counter_notice_closes_the_cycle_without_double_counting_the_strike
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z")
    ctx = setup_second_removal_on_same_seller(api, ctx, clock="2026-08-17T09:00:00Z", tag="2")
    escalated = read_seller(api, ctx["seller"]["id"])
    assert_seller_strikes(escalated, 25.10, 25.10, SELLER_STATUS_UNDER_INVESTIGATION)

    set_clock(api, "2026-08-19T09:00:00Z")
    counter = create_counter_notice(api, ctx["takedown_2"]["id"], ctx["seller"]["id"],
                                   sworn_statement_ref="CN-SWORN-1")
    contested = read_takedown(api, ctx["takedown_2"]["id"])
    assert contested["status"] == "COUNTER_NOTICED", f"got {contested['status']}"
    assert_seller_strikes(read_seller(api, ctx["seller"]["id"]), 25.10, 25.10,
                          SELLER_STATUS_UNDER_INVESTIGATION)

    resolved = resolve_counter_notice(api, counter["id"], "REBUTTED", "REB-1")

    assert resolved["status"] == "REBUTTED", f"got {resolved['status']}"
    assert_instant_equals(resolved["resolved_at"], "2026-08-19T09:00:00Z", "resolved_at")
    assert resolved["rebuttal_ref"] == "REB-1"
    reinstated_removal = read_takedown(api, ctx["takedown_2"]["id"])
    assert reinstated_removal["status"] == "APPROVED_REMOVED", (
        f"The rebuttal closes the cycle, got {reinstated_removal['status']}")
    assert_instant_equals(reinstated_removal["counter_notice_deadline_at"],
                          "2026-08-31T09:00:00Z",
                          "counter_notice_deadline_at (not extended by the rebuttal)")
    assert reinstated_removal["version"] == contested["version"] + 1

    after = read_seller(api, ctx["seller"]["id"])
    assert_seller_strikes(after, 25.10, 25.10, SELLER_STATUS_UNDER_INVESTIGATION)
    assert after["version"] == escalated["version"], (
        f"The seller row is not touched by the rebuttal, got version {after['version']}")
    assert read_claim(api, ctx["claim_2"]["id"])["status"] == "ENFORCED"


def test_the_rebutted_notice_returns_to_the_removed_metric_counts_once(api):
    """PRD §3.11: "A notice currently at `COUNTER_NOTICED` is excluded even though it was once `APPROVED_REMOVED` — only the current status matters."
    PRD §3.11: "`removed_takedown_count` counts those whose `status` is `APPROVED_REMOVED`."
    PRD §3.11: "`repeat_infringer_count` counts cluster roots — never alias rows — whose `cluster_strike_points` has reached 25.00 and that have at least one strike attributable to this brand somewhere in the cluster."
    PRD §3.8: "Crucially, the strike attribution is **not** re-run: the original takedown-removal strike was never removed from the ledger while the notice sat in `COUNTER_NOTICED`, so returning to `APPROVED_REMOVED` must not add a second one."

    Design: Difficulty/compensating_invariant/rebutted_counter_notice_closes_the_cycle_without_double_counting_the_strike
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z")
    ctx = setup_second_removal_on_same_seller(api, ctx, clock="2026-08-17T09:00:00Z", tag="2")
    before = read_metrics(api, ctx["brand"]["id"])
    assert_metrics(before, decided_takedown_count=2, removed_takedown_count=2,
                   listing_removal_rate=1.0000, repeat_infringer_count=1)

    set_clock(api, "2026-08-19T09:00:00Z")
    counter = create_counter_notice(api, ctx["takedown_2"]["id"], ctx["seller"]["id"])
    assert_metrics(read_metrics(api, ctx["brand"]["id"]),
                   decided_takedown_count=1, removed_takedown_count=1,
                   listing_removal_rate=1.0000, repeat_infringer_count=1)

    resolve_counter_notice(api, counter["id"], "REBUTTED", "REB-1")

    assert_metrics(read_metrics(api, ctx["brand"]["id"]),
                   decided_takedown_count=2, removed_takedown_count=2,
                   listing_removal_rate=1.0000, repeat_infringer_count=1)
    assert_seller_strikes(read_seller(api, ctx["seller"]["id"]), 25.10, 25.10,
                          SELLER_STATUS_UNDER_INVESTIGATION)
