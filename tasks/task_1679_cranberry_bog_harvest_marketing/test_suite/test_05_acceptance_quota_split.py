"""Delivery acceptance, the quota split, and pool tagging (PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_delivery,
    assert_money,
    close_pool,
    get_delivery,
    get_pool,
    get_quota_for,
    make_grower_headers,
    override_quota,
    receive_delivery,
    grade_delivery,
    setup_accepted_delivery,
    setup_campaign_with_pool,
    setup_graded_delivery,
    setup_received_delivery,
    setup_scheduled_delivery,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["coop_admin_headers"]
POOL_MGR = TEST_USERS["pool_manager_headers"]

B_SCORES = dict(color_score=7.5, firmness_score=7.0, foreign_matter_pct=3.0)


def test_accept_exactly_fills_quota_zero_over(api):
    """PRD §3.7: "The boundary is inclusive: when deliveries to date plus this
    load land exactly on the quota, the delivery is fully in-quota and no
    overage arises."
    PRD §3.3: "The quota's `posture` reads `WITHIN_QUOTA` while
    `delivered_barrels` is at most `base_quota_barrels`".

    Design: Difficulty/boundary_precision_check/accept_delivery_exactly_fills_quota_zero_over
    """
    ctx = setup_campaign_with_pool()  # MAIN only, no OVER_QUOTA pool
    override_quota(ctx.quota["id"], 1000)
    delivery = setup_graded_delivery(ctx, 1050, 50, expected_barrels=1050,
                                     **B_SCORES)  # net exactly 1000

    accepted = accept_and_check(api, delivery["id"])
    assert_money(accepted["quota_applied_barrels"], 1000)
    assert_money(accepted["over_quota_barrels"], 0)
    assert accepted["over_quota_pool_id"] is None, (
        "exact fill produces no overage, so no OVER_QUOTA pool tag")

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert quota["posture"] == "WITHIN_QUOTA", (
        "delivered 1000 == base 1000 is at most the quota, not over it")


def accept_and_check(api, delivery_id):
    accepted = validate_success(api.accept_delivery(delivery_id, POOL_MGR), 200)
    assert_delivery(accepted)
    assert accepted["status"] == "ACCEPTED"
    return accepted


def test_accept_one_barrel_over_quota_tags_over_quota_pool(api):
    """PRD §3.7: "`quota_applied_barrels` is the smaller of the delivery's
    `net_barrels` and that headroom, and the delivery's `over_quota_barrels` is
    whatever remains of the net."
    PRD §3.7: "The delivery's `main_pool_id` is set to the season's `OPEN`
    `MAIN` pool, and when overage exists its `over_quota_pool_id` is set to the
    season's `OPEN` `OVER_QUOTA` pool."

    Design: Difficulty/boundary_precision_check/accept_delivery_exactly_fills_quota_zero_over
    """
    ctx = setup_campaign_with_pool(over_quota_pool=True)
    override_quota(ctx.quota["id"], 1000)
    delivery = setup_graded_delivery(ctx, 1051, 50, expected_barrels=1051,
                                     **B_SCORES)  # net 1001, one barrel over

    accepted = accept_and_check(api, delivery["id"])
    assert_money(accepted["quota_applied_barrels"], 1000)
    assert_money(accepted["over_quota_barrels"], 1)
    assert accepted["main_pool_id"] == ctx.main_pool["id"]
    assert accepted["over_quota_pool_id"] == ctx.oq_pool["id"]

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota["delivered_barrels"], 1000)
    assert_money(quota["over_quota_barrels"], 1)
    # Per PRD §3.3 posture compares delivered_barrels to base_quota_barrels.
    assert quota["posture"] == "WITHIN_QUOTA"


def test_accept_blocked_when_main_pool_closed(api):
    """PRD §3.7: "A graded delivery is accepted only while its season is `OPEN`
    (`ERR_SEASON_NOT_OPEN` otherwise) and the season's `MAIN` pool is `OPEN`
    (`ERR_POOL_NOT_OPEN` otherwise)."
    PRD §2.9: the season stays OPEN while not every pool has reached CLOSED or
    SETTLED ("When every pool of an `OPEN` season has reached `CLOSED` or
    `SETTLED` — and at least one pool exists — the season automatically
    advances from `OPEN` to `HARVEST_CLOSED`").

    Design: Difficulty/cross_entity_state_dependency/delivery_accept_blocked_when_main_pool_closed
    """
    ctx = setup_campaign_with_pool(over_quota_pool=True)
    delivery = setup_scheduled_delivery(ctx, expected_barrels=150)
    # SCHEDULED does not block closing; the OVER_QUOTA pool keeps the season OPEN.
    close_pool(ctx.main_pool["id"])

    receive_delivery(delivery["id"], ctx.station["id"], 150, 50)
    grade_delivery(delivery["id"], ctx.station["id"], **B_SCORES)

    resp = api.accept_delivery(delivery["id"], POOL_MGR)
    validate_error(resp, ApiErrorId.ERR_POOL_NOT_OPEN)
    assert get_delivery(delivery["id"])["status"] == "GRADED"


def test_void_blocked_when_tagged_pool_closed(api):
    """PRD §3.7: "A `PoolManager` may void an `ACCEPTED` delivery only while
    every tagged pool is still `OPEN` (`ERR_POOL_NOT_OPEN` otherwise)."

    Design: Difficulty/cross_entity_state_dependency/delivery_accept_blocked_when_main_pool_closed
    """
    ctx = setup_campaign_with_pool(over_quota_pool=True)
    delivery = setup_accepted_delivery(ctx, 150, 50, expected_barrels=150,
                                       **B_SCORES)  # in-quota: tagged to MAIN only
    assert delivery["main_pool_id"] == ctx.main_pool["id"]
    assert delivery["over_quota_pool_id"] is None

    # ACCEPTED does not block closing; OVER_QUOTA pool keeps the season OPEN.
    close_pool(ctx.main_pool["id"])

    resp = api.void_delivery(delivery["id"], POOL_MGR)
    validate_error(resp, ApiErrorId.ERR_POOL_NOT_OPEN)
    assert get_delivery(delivery["id"])["status"] == "ACCEPTED"


def test_reaccept_state_error_beats_over_quota_pool_fiscal(api):
    """PRD §2.8: "A request that would fail several checks is always rejected by
    the earliest applicable band, and the bands are evaluated in this fixed
    order:" — state legality (band 6, `ERR_INVALID_STATE`) precedes fiscal pool
    and settlement rules (band 10, `ERR_OVER_QUOTA_POOL_UNAVAILABLE`).

    Design: Difficulty/priority_pair_validation_conflict/accept_replay_state_error_beats_over_quota_pool_fiscal
    """
    ctx = setup_campaign_with_pool()  # MAIN only; no OVER_QUOTA pool
    override_quota(ctx.quota["id"], 100)
    delivery = setup_accepted_delivery(ctx, 150, 50, expected_barrels=150,
                                       **B_SCORES)  # net 100 fills the quota exactly

    # Re-accepting violates the state machine AND would need a missing
    # OVER_QUOTA pool (remaining headroom is now 0); the state error wins.
    resp = api.accept_delivery(delivery["id"], POOL_MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert get_delivery(delivery["id"])["status"] == "ACCEPTED"
    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota["delivered_barrels"], 100)


def test_accept_ungraded_state_error_beats_fiscal(api):
    """PRD §2.8: "A request that would fail several checks is always rejected by
    the earliest applicable band, and the bands are evaluated in this fixed
    order:" — a RECEIVED delivery has no defined accept transition (band 6),
    ahead of the over-quota pool availability rule (band 10).
    PRD §3.7: "A graded delivery is accepted only while its season is `OPEN`".

    Design: Difficulty/priority_pair_validation_conflict/accept_replay_state_error_beats_over_quota_pool_fiscal
    """
    ctx = setup_campaign_with_pool()  # MAIN only; no OVER_QUOTA pool
    override_quota(ctx.quota["id"], 100)
    delivery = setup_received_delivery(ctx, 200, 50, expected_barrels=200)
    # net 150 > remaining 100: the fiscal over-quota check would also fail.
    resp = api.accept_delivery(delivery["id"], POOL_MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_delivery(delivery["id"])["status"] == "RECEIVED"


def test_over_quota_split_partial_crossing_tags_two_pools(api):
    """PRD §3.7: "The remaining headroom is the `base_quota_barrels` minus the
    `delivered_barrels`, floored at zero; `quota_applied_barrels` is the smaller
    of the delivery's `net_barrels` and that headroom, and the delivery's
    `over_quota_barrels` is whatever remains of the net."
    PRD §3.7: "the `advance_amount` booked on the delivery is the sum of two
    independently rounded terms: the in-quota weighted share times the `MAIN`
    pool's `provisional_advance_rate_per_barrel`, rounded half-up to two
    decimals, plus the over-quota weighted share times the `OVER_QUOTA` pool's
    rate, likewise rounded."

    Design: Corner/calculations/over_quota_split_partial_crossing_tags_two_pools
    """
    ctx = setup_campaign_with_pool(over_quota_pool=True)  # MAIN .50, OQ .25
    override_quota(ctx.quota["id"], 1000)
    delivery = setup_graded_delivery(ctx, 1250, 50, expected_barrels=1250,
                                     **B_SCORES)  # net 1200, grade B, weighted 1200

    accepted = accept_and_check(api, delivery["id"])
    assert_money(accepted["quota_applied_barrels"], 1000)
    assert_money(accepted["over_quota_barrels"], 200)
    assert accepted["main_pool_id"] == ctx.main_pool["id"]
    assert accepted["over_quota_pool_id"] == ctx.oq_pool["id"]
    # Weighted shares: 1000 in-quota + 200 over-quota (pro-rata by barrels).
    assert_money(accepted["advance_amount"], 550.00)  # round2(1000*.50)+round2(200*.25)

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota["delivered_barrels"], 1000)
    assert_money(quota["over_quota_barrels"], 200)
    # Per PRD §3.3: "posture reads WITHIN_QUOTA while delivered_barrels is at
    # most base_quota_barrels" — 1000 <= 1000 here.
    assert quota["posture"] == "WITHIN_QUOTA"

    oq_after = get_pool(ctx.oq_pool["id"])
    assert_money(oq_after["accepted_net_barrels"], 200)
    main_after = get_pool(ctx.main_pool["id"])
    assert_money(main_after["accepted_net_barrels"], 1000)


def test_accept_over_quota_without_over_quota_pool_rejected(api):
    """PRD §3.7: "Whenever `over_quota_barrels` is greater than zero, the
    season's `OPEN` `OVER_QUOTA` pool must exist — at most one pool of each code
    exists per season by the uniqueness rule — and its absence rejects the
    acceptance with `ERR_OVER_QUOTA_POOL_UNAVAILABLE`."

    Design: Corner/validations/accept_over_quota_without_over_quota_pool_rejected
    """
    ctx = setup_campaign_with_pool()  # MAIN only
    override_quota(ctx.quota["id"], 100)
    delivery = setup_graded_delivery(ctx, 200, 50, expected_barrels=200,
                                     **B_SCORES)  # net 150 > remaining 100

    resp = api.accept_delivery(delivery["id"], POOL_MGR)
    validate_error(resp, ApiErrorId.ERR_OVER_QUOTA_POOL_UNAVAILABLE)
    assert get_delivery(delivery["id"])["status"] == "GRADED"
