"""Grade disputes and void compensation (PRD §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_delivery,
    assert_money,
    dispute_delivery,
    get_delivery,
    get_pool,
    get_quota_for,
    grade_delivery,
    override_quota,
    setup_accepted_delivery,
    setup_campaign_with_pool,
    setup_campaign_with_station,
    setup_graded_delivery,
    validate_success,
    void_delivery,
)

POOL_MGR = TEST_USERS["pool_manager_headers"]

A_SCORES = dict(color_score=9.0, firmness_score=8.5, foreign_matter_pct=1.5)
B_SCORES = dict(color_score=7.5, firmness_score=7.0, foreign_matter_pct=3.0)


def test_delivery_grade_dispute_regrade_cycle(api):
    """PRD §3.6: "the owning grower (delivery `member_id` matching `X-User-ID`,
    else `ERR_FORBIDDEN`) moves a `GRADED` delivery to `DISPUTED`, incrementing
    `dispute_count` by 1."
    PRD §3.6: "Re-grading from `DISPUTED` records a fresh set of scores through
    the same station-side grading action, replacing the prior `color_score`,
    `firmness_score`, and `foreign_matter_pct` and recomputing the grade,
    multiplier, and weighted barrels; the delivery lands on `GRADED` when the
    new result passes and on `REJECTED` when it does not."

    Design: Difficulty/non_linear_state_machine/delivery_grade_dispute_regrade_cycle
    """
    ctx = setup_campaign_with_station()
    delivery = setup_graded_delivery(ctx, 200, 10, color_score=9.0,
                                     firmness_score=9.0, foreign_matter_pct=1.0,
                                     expected_barrels=200)
    assert delivery["grade"] == "A"

    disputed = dispute_delivery(delivery["id"], ctx.member["id"])
    assert disputed["status"] == "DISPUTED"

    regraded = grade_delivery(delivery["id"], ctx.station["id"], **B_SCORES)
    assert regraded["status"] == "GRADED", "GRADED -> DISPUTED -> GRADED cycle"
    assert regraded["grade"] == "B", "the re-grade replaces the original A"
    assert regraded["dispute_count"] == 1
    assert_money(regraded["weighted_barrels"], 190.00)  # net 190 * 1.00


def test_delivery_second_dispute_increments_count(api):
    """PRD §3.6: "the owning grower (delivery `member_id` matching `X-User-ID`,
    else `ERR_FORBIDDEN`) moves a `GRADED` delivery to `DISPUTED`, incrementing
    `dispute_count` by 1."

    Design: Difficulty/non_linear_state_machine/delivery_grade_dispute_regrade_cycle
    """
    ctx = setup_campaign_with_station()
    delivery = setup_graded_delivery(ctx, 200, 10, color_score=9.0,
                                     firmness_score=9.0, foreign_matter_pct=1.0,
                                     expected_barrels=200)

    dispute_delivery(delivery["id"], ctx.member["id"])
    grade_delivery(delivery["id"], ctx.station["id"], **B_SCORES)

    disputed2 = dispute_delivery(delivery["id"], ctx.member["id"])
    assert disputed2["status"] == "DISPUTED"
    assert disputed2["dispute_count"] == 2, "each dispute adds exactly 1"

    regraded2 = grade_delivery(delivery["id"], ctx.station["id"],
                               color_score=9.0, firmness_score=9.0,
                               foreign_matter_pct=1.0)
    assert regraded2["grade"] == "A"
    assert regraded2["status"] == "GRADED"
    assert_money(regraded2["weighted_barrels"], 209.00)  # net 190 * 1.10


def test_accept_void_roundtrip_conserves_quota_barrels(api):
    """PRD §3.7: "The void subtracts precisely the contributions the acceptance
    recorded: the quota's `delivered_barrels` and `over_quota_barrels` are
    reduced by the delivery's `quota_applied_barrels` and `over_quota_barrels`
    with `posture` recomputed".
    PRD §3.7: "The delivery ends `VOIDED`, a terminal state, and its barrels no
    longer count anywhere."

    Design: Difficulty/compensating_invariant/accept_void_roundtrip_conserves_quota_barrels
    """
    ctx = setup_campaign_with_pool()
    delivery = setup_accepted_delivery(ctx, 1000, 50, expected_barrels=1000,
                                       **A_SCORES)  # net 950, grade A

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota["delivered_barrels"], 950)

    voided = void_delivery(delivery["id"])
    assert voided["status"] == "VOIDED"

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota["delivered_barrels"], 0)
    assert_money(quota["over_quota_barrels"], 0)
    assert quota["posture"] == "WITHIN_QUOTA"


def test_void_of_split_delivery_restores_quota_exactly(api):
    """PRD §3.7: "The void subtracts precisely the contributions the acceptance
    recorded: the quota's `delivered_barrels` and `over_quota_barrels` are
    reduced by the delivery's `quota_applied_barrels` and `over_quota_barrels`
    with `posture` recomputed".

    Design: Difficulty/compensating_invariant/accept_void_roundtrip_conserves_quota_barrels
    """
    ctx = setup_campaign_with_pool(over_quota_pool=True)
    override_quota(ctx.quota["id"], 1000)
    delivery = setup_accepted_delivery(ctx, 1250, 50, expected_barrels=1250,
                                       **B_SCORES)  # net 1200 -> 1000 + 200

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota["delivered_barrels"], 1000)
    assert_money(quota["over_quota_barrels"], 200)

    voided = void_delivery(delivery["id"])
    assert voided["status"] == "VOIDED"

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota["delivered_barrels"], 0)
    assert_money(quota["over_quota_barrels"], 0)
    assert quota["posture"] == "WITHIN_QUOTA"


def test_accept_void_roundtrip_conserves_pool_advances(api):
    """PRD §3.7: "each tagged pool's totals grow by its portion —
    `accepted_net_barrels` by the barrel portion, `weighted_barrels_total` by
    the weighted share, `advances_outstanding` by the advance term".
    PRD §3.7: "each tagged pool's `accepted_net_barrels`,
    `weighted_barrels_total`, and `advances_outstanding` are reduced by exactly
    this delivery's recorded portions".

    Design: Difficulty/compensating_invariant/accept_void_roundtrip_conserves_pool_advances
    """
    ctx = setup_campaign_with_pool()
    delivery = setup_accepted_delivery(ctx, 1000, 50, expected_barrels=1000,
                                       **A_SCORES)  # net 950, A, weighted 1045

    assert_money(delivery["advance_amount"], 522.50)  # round2(1045 * 0.50)
    pool = get_pool(ctx.main_pool["id"])
    assert_money(pool["advances_outstanding"], 522.50)
    assert_money(pool["weighted_barrels_total"], 1045)
    assert_money(pool["accepted_net_barrels"], 950)

    void_delivery(delivery["id"])

    pool = get_pool(ctx.main_pool["id"])
    assert_money(pool["advances_outstanding"], 0)
    assert_money(pool["weighted_barrels_total"], 0)
    assert_money(pool["accepted_net_barrels"], 0)


def test_void_one_of_two_deliveries_conserves_pool_money(api):
    """PRD §3.7: "each tagged pool's `accepted_net_barrels`,
    `weighted_barrels_total`, and `advances_outstanding` are reduced by exactly
    this delivery's recorded portions, each pool's `version` incrementing
    again."

    Design: Difficulty/compensating_invariant/accept_void_roundtrip_conserves_pool_advances
    """
    ctx = setup_campaign_with_pool()
    d1 = setup_accepted_delivery(ctx, 1000, 50, expected_barrels=1000,
                                 scheduled_date="2026-10-10",
                                 **A_SCORES)  # net 950, weighted 1045, adv 522.50
    d2 = setup_accepted_delivery(ctx, 840, 40, expected_barrels=840,
                                 scheduled_date="2026-10-11",
                                 **B_SCORES)  # net 800, weighted 800, adv 400.00

    pool = get_pool(ctx.main_pool["id"])
    assert_money(pool["advances_outstanding"], 922.50)
    assert_money(pool["weighted_barrels_total"], 1845)
    assert_money(pool["accepted_net_barrels"], 1750)

    void_delivery(d1["id"])

    pool = get_pool(ctx.main_pool["id"])
    assert_money(pool["advances_outstanding"], 400.00)
    assert_money(pool["weighted_barrels_total"], 800)
    assert_money(pool["accepted_net_barrels"], 800)
    assert get_delivery(d2["id"])["status"] == "ACCEPTED", (
        "voiding one delivery leaves the other's contribution intact")
