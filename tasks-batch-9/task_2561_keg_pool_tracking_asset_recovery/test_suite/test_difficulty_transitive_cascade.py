"""Cascades that run three or more links deep inside one request.

Each scenario stages a single write whose consequences propagate through an
accrual, a counter recomputation, a status gate and a float posture, and then
reads every link of the chain back to prove the ordering the contract pins.
"""

from test_helpers import (
    api_client,
    fixtures,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ANALYST_USER_ID,
    SECOND_ANALYST_USER_ID,
    TEST_USERS,
)

OPERATOR = TEST_USERS["pool_operator_headers"]

CLOCK = "2026-08-01T23:00:00Z"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
    "restrict_threshold_pct": 25,
    "freeze_threshold_pct": 10,
    "restricted_max_kegs_per_order": 2,
}

AGREEMENT = {
    "per_fill_rate_cents": 2200,
    "replenishment_threshold_pct": 20,
}


def _return_dwell_accruals_by_keg(distributor_id):
    """Every `RETURN_DWELL` accrual of one distributor, keyed by keg."""
    rows, _meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR,
            params={"distributor_id": distributor_id, "accrual_type": "RETURN_DWELL"},
        )
    )
    return {row["keg_id"]: row for row in rows}


def _four_returns_that_promote_the_distributor_midway():
    """Four kegs issued, filled and distributed together, then all four returned
    on the same instant after twelve days of distributor accountability.

    The third return is the one whose recomputed counters reach the `SILVER`
    thresholds, so the fourth is the first to be priced at the new tier.  Every
    intermediate read is captured so the ordering inside each request is
    observable afterwards.
    """
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=8,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    distributor = fixtures.create_distributor(return_incentive_rate_cents_per_keg=250)
    fixtures.sign_cooperation_agreement(distributor["id"], "BRONZE", "2026-08-01")

    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 4, "2026-08-01T01:00:00Z"
    )
    issued = order["allocated_keg_ids"]
    for keg_id in issued:
        fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")
    for keg_id in issued:
        fixtures.distribution_scan(keg_id, distributor["id"], "2026-08-01T03:00:00Z", "RDG")

    fixtures.pin_clock("2026-08-14T00:00:00Z")

    returns = []
    for keg_id in issued:
        scan = fixtures.return_scan(
            keg_id, distributor["id"], "2026-08-13T03:00:00Z", "RDG"
        )
        accruals = _return_dwell_accruals_by_keg(distributor["id"])
        returns.append(
            {
                "keg_id": keg_id,
                "scan": scan,
                "keg": fixtures.read_keg(keg_id),
                "accrual": accruals[keg_id],
                "distributor": fixtures.read_distributor(distributor["id"]),
            }
        )

    ctx["distributor"] = distributor
    ctx["order"] = order
    ctx["issued_keg_ids"] = issued
    ctx["returns"] = returns
    return ctx


def test_the_return_that_earns_the_promotion_is_still_paid_at_the_old_tier():
    """The first three returns are each valued at the `BRONZE` multiplier, and
    the third one is valued that way even though the very same request lifts the
    distributor to `SILVER` and dates the new tier at the logical day.

    PRD: "And because the promotion lands *after* the accrual has been valued,
    the very return that triggers `BRONZE → SILVER` is itself paid at the
    `BRONZE` multiplier; the `SILVER` multiplier first appears on the next
    return."

    Design: Difficulty/transitive_cascade/return_scan_promotes_cooperation_tier_which_reprices_the_next_accrual
    """
    ctx = _four_returns_that_promote_the_distributor_midway()
    returns = ctx["returns"]

    for leg in returns[:3]:
        assert leg["keg"]["custody_state"] == "IN_SERVICE"
        assert leg["accrual"]["accrual_type"] == "RETURN_DWELL"
        assert leg["accrual"]["dwell_days"] == 12
        assert leg["accrual"]["tier_pct_bp"] == 10000
        assert leg["accrual"]["cooperation_multiplier_bp"] == 10000
        assert leg["accrual"]["incentive_cents"] == 250

    assert returns[0]["distributor"]["cooperation_tier"] == "BRONZE"
    assert returns[0]["distributor"]["total_returns_count"] == 1
    assert returns[1]["distributor"]["cooperation_tier"] == "BRONZE"
    assert returns[1]["distributor"]["total_returns_count"] == 2

    promoting = returns[2]
    assert promoting["distributor"]["cooperation_tier"] == "SILVER"
    assert promoting["distributor"]["cooperation_effective_date"] == "2026-08-14"
    assert promoting["accrual"]["cooperation_multiplier_bp"] == 10000
    assert promoting["accrual"]["incentive_cents"] == 250


def test_the_next_return_after_the_promotion_is_repriced_at_the_new_tier():
    """The fourth return, identical in dwell to the first three, is the first one
    to read the `SILVER` multiplier and so is worth 288 cents instead of 250.

    PRD: "The cooperation factor is 0 basis points for a `NONE`-tier
    distributor, 10000 for `BRONZE`, 11500 for `SILVER` and 13000 for `GOLD`,
    taken from the tier as it stands *at the moment of this scan*."

    Design: Difficulty/transitive_cascade/return_scan_promotes_cooperation_tier_which_reprices_the_next_accrual
    """
    ctx = _four_returns_that_promote_the_distributor_midway()
    last = ctx["returns"][3]

    assert last["distributor"]["cooperation_tier"] == "SILVER"
    assert last["accrual"]["dwell_days"] == 12
    assert last["accrual"]["tier_pct_bp"] == 10000
    assert last["accrual"]["cooperation_multiplier_bp"] == 11500
    assert last["accrual"]["incentive_cents"] == 288
    assert last["accrual"]["incentive_cents"] != 250


def test_the_incentive_ledger_totals_three_bronze_rows_and_one_silver_row():
    """Because only the last of the four returns was repriced, the ledger is
    1038 cents rather than the 1076 it would hold if the promotion had also
    re-rated the return that earned it, and four returns is one short of the
    total `GOLD` needs so no second step is taken.

    PRD: "A distributor's `incentive_accrual_cents` is at all times the sum of
    `incentive_cents` over that distributor's accruals whose `status` is
    `ACCRUED` or `PAID`."

    PRD: "Third, at most **one** step up the ladder is applied and no step may
    be skipped: a `BRONZE` distributor becomes `SILVER` when its total is at
    least 3 returns and its on-time percentage is at least 90.00, and a `SILVER`
    distributor becomes `GOLD` when its total is at least 5 returns and its
    on-time percentage is at least 96.00, recording `cooperation_effective_date`
    as the current logical date in either case."

    Design: Difficulty/transitive_cascade/return_scan_promotes_cooperation_tier_which_reprices_the_next_accrual
    """
    ctx = _four_returns_that_promote_the_distributor_midway()
    accruals = _return_dwell_accruals_by_keg(ctx["distributor"]["id"])

    assert len(accruals) == 4
    minted = [accruals[keg_id]["incentive_cents"] for keg_id in ctx["issued_keg_ids"]]
    assert minted == [250, 250, 250, 288]
    for row in accruals.values():
        assert row["status"] == "ACCRUED"

    distributor = fixtures.read_distributor(ctx["distributor"]["id"])
    assert distributor["incentive_accrual_cents"] == 1038
    assert distributor["incentive_accrual_cents"] != 1076
    assert distributor["cooperation_tier"] == "SILVER"
    assert distributor["cooperation_effective_date"] == "2026-08-14"


def test_each_return_recomputes_the_counters_and_hands_the_keg_to_servicing():
    """After all four returns the distributor's service history counts four
    on-time returns at a twelve-day mean, and the pool has moved all four kegs
    out of circulation and into servicing.

    PRD: "Then the counters are recomputed *including* the accrual just minted:
    `total_returns_count` is the number of `RETURN_DWELL` accruals of this
    distributor in `ACCRUED`, `PAID` or `CLAWED_BACK`; `on_time_returns_count`
    is the subset of those whose `dwell_days` is 45 or fewer;
    `on_time_return_pct` is 0.00 when the total is zero and otherwise the
    on-time count divided by the total, multiplied by 100, rounded half up to
    two decimals; and `avg_dwell_days` is 0.00 when the set is empty and
    otherwise the mean of `dwell_days` across that set, rounded half up to two
    decimals."

    PRD: "Finally the pool's `kegs_circulating` falls by one and `kegs_servicing`
    rises by one, `posture` is recomputed, and every `ACTIVE` agreement on the
    pool recomputes `float_posture`."

    Design: Difficulty/transitive_cascade/return_scan_promotes_cooperation_tier_which_reprices_the_next_accrual
    """
    ctx = _four_returns_that_promote_the_distributor_midway()

    for index, leg in enumerate(ctx["returns"], start=1):
        assert leg["distributor"]["total_returns_count"] == index
        assert leg["distributor"]["on_time_returns_count"] == index
        assert leg["distributor"]["on_time_return_pct"] == 100.00
        assert leg["distributor"]["avg_dwell_days"] == 12.00

    for keg_id in ctx["issued_keg_ids"]:
        keg = fixtures.read_keg(keg_id)
        assert keg["custody_state"] == "IN_SERVICE"
        assert keg["distributor_custody_started_at"] is None
        assert keg["dwell_started_at"] == "2026-08-13T03:00:00Z"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_total"] == 8
    assert pool["kegs_available"] == 4
    assert pool["kegs_circulating"] == 0
    assert pool["kegs_servicing"] == 4
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"


def _upheld_loss_that_pushes_the_balance_past_the_probation_line():
    """Seven kegs filled at a 28200-cent pool, one of them written off for good,
    with a replenishment order already on the books when the loss is upheld.

    One uphold of a full replacement cost carries the brewer's chargeback ledger
    from zero to 28200 cents in a single request, which is past the 25000-cent
    probation line, which in turn suspends the float the order was placed
    against.
    """
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=10,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL, replacement_cost_cents=28200),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    agreement_id = ctx["agreement"]["id"]
    order = fixtures.order_allocated_and_dispatched(
        agreement_id, 7, "2026-08-01T01:00:00Z"
    )
    issued = order["allocated_keg_ids"]
    for keg_id in issued:
        fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")

    # The replenishment request is placed while the float is still healthy.
    replenishment = fixtures.create_order(agreement_id, 1)

    ctx["agreement_before_uphold"] = fixtures.read_agreement(agreement_id)
    ctx["brewer_before_uphold"] = fixtures.read_brewer(ctx["brewer"]["id"])
    ctx["pool_before_uphold"] = fixtures.read_pool(ctx["pool"]["id"])

    proposed = fixtures.open_loss_assessment(
        issued[0],
        "NOT_RETURNED_DWELL",
        analyst_id=ANALYST_USER_ID,
        assessment_basis="REPLACEMENT_COST",
    )
    ctx["assessment"] = fixtures.resolve_assessment(
        proposed["id"], "UPHELD", analyst_id=SECOND_ANALYST_USER_ID
    )
    ctx["order"] = order
    ctx["issued_keg_ids"] = issued
    ctx["lost_keg_id"] = issued[0]
    ctx["replenishment_order"] = replenishment
    return ctx


def _allocate(order_id, agreement_id):
    """Allocate against the agreement's version as it stands right now."""
    return api_client.allocate_issuance_order(
        order_id,
        {"expected_agreement_version": fixtures.agreement_version(agreement_id)},
        OPERATOR,
    )


def test_upholding_the_loss_issues_the_chargeback_and_rebuilds_the_balance():
    """The uphold is recorded by the second analyst, values the shell at the
    pool's full replacement cost with no scrap credit, and moves the brewer's
    ledger from zero to the whole net figure in the same request.

    PRD: "The assessment moves to `UPHELD` and, when `net_chargeback_cents` is
    greater than zero, `chargeback_status` flips from `NONE` to `ISSUED` in the
    same request."

    PRD: "`scrap_credit_cents` takes the keg's `stainless_scrap_value_cents`
    only when the `cause` is `DAMAGED_BEYOND_REPAIR`, because only then is the
    shell physically in hand; `LOST_IN_TRADE`, `NOT_RETURNED_DWELL` and
    `STOLEN_SUSPECTED` all credit 0 even though the keg has a scrap value on
    paper, since nobody can weigh in a keg they cannot find."

    PRD: "Because the chargeback became `ISSUED`, the brewer's
    `chargeback_balance_cents` is recomputed, `upheld_loss_count` increases by
    one, both `loss_rate_bp_trailing_90d` and `loss_rate_bp_lifetime` are
    recomputed, and the brewer's `version` advances."

    Design: Difficulty/transitive_cascade/upheld_chargeback_crosses_balance_threshold_and_suspends_the_float
    """
    ctx = _upheld_loss_that_pushes_the_balance_past_the_probation_line()

    before_agreement = ctx["agreement_before_uphold"]
    assert before_agreement["billed_amount_cents"] == 15136
    assert before_agreement["billed_fills_count"] == 7
    assert before_agreement["kegs_at_brewer_count"] == 7
    assert before_agreement["float_posture"] == "HEALTHY"

    before_brewer = ctx["brewer_before_uphold"]
    assert before_brewer["status"] == "ACTIVE"
    assert before_brewer["chargeback_balance_cents"] == 0
    assert before_brewer["lifetime_fill_count"] == 7
    assert before_brewer["upheld_loss_count"] == 0

    assessment = ctx["assessment"]
    assert assessment["assessment_status"] == "UPHELD"
    assert assessment["resolved_by_user_id"] == SECOND_ANALYST_USER_ID
    assert assessment["assessment_basis"] == "REPLACEMENT_COST"
    assert assessment["gross_value_cents"] == 28200
    assert assessment["scrap_credit_cents"] == 0
    assert assessment["assessed_value_cents"] == 28200
    assert assessment["brewer_liability_pct_bp"] == 10000
    assert assessment["net_chargeback_cents"] == 28200
    assert assessment["chargeback_status"] == "ISSUED"

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 28200
    assert brewer["upheld_loss_count"] == 1
    assert brewer["lifetime_fill_count"] == 7


def test_the_balance_threshold_is_the_gate_that_moves_the_brewer_to_probation():
    """The ledger crossing 25000 cents is what puts the brewer on probation: the
    trailing loss rate stands at 1429 basis points, below the 1500 the loss-rate
    gate needs, so the reason recorded names the balance and not the rate.

    PRD: "Because the balance was recomputed, the probation gate runs: when
    `chargeback_balance_cents` is at or above 25000 cents and the brewer's
    `status` is `ACTIVE`, the brewer moves to `PROBATION` with `status_reason`
    recorded as `CHARGEBACK_BALANCE_THRESHOLD`."

    PRD: "When the trailing rate reaches 1500 basis points and the brewer's
    `status` is `ACTIVE`, the brewer moves to `PROBATION` with `status_reason`
    `LOSS_RATE_THRESHOLD`."

    Design: Difficulty/transitive_cascade/upheld_chargeback_crosses_balance_threshold_and_suspends_the_float
    """
    ctx = _upheld_loss_that_pushes_the_balance_past_the_probation_line()
    brewer = fixtures.read_brewer(ctx["brewer"]["id"])

    assert brewer["chargeback_balance_cents"] == 28200
    assert brewer["chargeback_balance_cents"] >= 25000
    assert brewer["status"] == "PROBATION"
    assert brewer["status_reason"] == "CHARGEBACK_BALANCE_THRESHOLD"

    assert brewer["loss_rate_bp_trailing_90d"] == 1429
    assert brewer["loss_rate_bp_trailing_90d"] < 1500


def test_the_probation_suspends_the_float_and_refuses_the_pending_allocation():
    """The probation reaches the float agreement, which reads `SUSPENDED` even
    though its pool is still comfortably `OPEN` with three kegs on the floor, and
    the replenishment order raised before the uphold can no longer be allocated.

    PRD: "Because the brewer entered probation, every `ACTIVE` float agreement of
    that brewer recomputes `float_posture` to `SUSPENDED`, which blocks that
    brewer's later allocations and fill scans."

    PRD: "The agreement is `SUSPENDED` whenever the pool's `posture` is `FROZEN`
    **or** the brewer's `status` is `PROBATION` or `SUSPENDED`."

    Design: Difficulty/transitive_cascade/upheld_chargeback_crosses_balance_threshold_and_suspends_the_float
    """
    ctx = _upheld_loss_that_pushes_the_balance_past_the_probation_line()
    agreement_id = ctx["agreement"]["id"]

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_total"] == 10
    assert pool["kegs_available"] == 3
    assert pool["kegs_circulating"] == 6
    assert pool["kegs_written_off"] == 1
    assert pool["available_pct"] == 30.00
    assert pool["posture"] == "OPEN"

    agreement = fixtures.read_agreement(agreement_id)
    assert agreement["status"] == "ACTIVE"
    assert agreement["float_posture"] == "SUSPENDED"

    lost_keg = fixtures.read_keg(ctx["lost_keg_id"])
    assert lost_keg["custody_state"] == "LOST"
    assert lost_keg["assessment_open"] is False

    refused = _allocate(ctx["replenishment_order"]["id"], agreement_id)
    validate_error(refused, ApiErrorId.ERR_FLOAT_SUSPENDED.value, 409)

    order = fixtures.read_order(ctx["replenishment_order"]["id"])
    assert order["status"] == "REQUESTED"
    assert order["allocated_keg_count"] == 0

    unchanged_pool = fixtures.read_pool(ctx["pool"]["id"])
    assert unchanged_pool["kegs_available"] == 3
    assert fixtures.read_agreement(agreement_id)["kegs_at_brewer_count"] == 6
