"""Pool lifecycle, settlement pricing, and patronage distributions
(PRD §2.9, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_delivery,
    approve_estimate,
    assert_money,
    assert_patronage_distribution,
    assert_rate4,
    close_pool,
    create_active_member,
    create_bog_for,
    create_delivery,
    create_estimate,
    create_pool,
    create_pool_payload,
    create_season,
    create_station,
    get_delivery,
    get_pool,
    get_quota_for,
    get_season,
    grade_delivery,
    list_distributions,
    open_season,
    override_quota,
    patch_pool_payload,
    receive_delivery,
    setup_accepted_delivery,
    setup_campaign,
    setup_campaign_with_pool,
    setup_graded_delivery,
    setup_scheduled_delivery,
    setup_settled_main_pool,
    settle_pool,
    settle_pool_payload,
    transition_pool,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["coop_admin_headers"]
POOL_MGR = TEST_USERS["pool_manager_headers"]

A_SCORES = dict(color_score=9.0, firmness_score=8.5, foreign_matter_pct=1.5)
B_SCORES = dict(color_score=7.5, firmness_score=7.0, foreign_matter_pct=3.0)


def test_provisional_advance_vs_final_settlement(api):
    """PRD §3.7: "the `advance_amount` booked on the delivery is the sum of two
    independently rounded terms: the in-quota weighted share times the `MAIN`
    pool's `provisional_advance_rate_per_barrel`, rounded half-up to two
    decimals".
    PRD §3.8: "Settlement then evaluates in a pinned order: first the net pool
    value, `realized_revenue` minus `operating_costs` rounded half-up to two
    decimals; then the `final_rate_per_weighted_barrel`, the net pool value
    divided by `weighted_barrels_total` and rounded half-up to four decimals".
    PRD §3.8: "`gross_amount`, the member's weighted barrels times the final
    rate rounded half-up to two decimals; `retain_amount`, the gross times the
    pool's `retain_pct` rounded half-up to two decimals".
    PRD §3.8: "The `cash_amount` owed is the `gross_amount` minus the
    `retain_amount` minus the `advance_paid`".
    PRD §3.8: "Whatever remains of the net pool value after the sum of all
    created distributions' gross amounts is the `coop_equity_residual`".

    Design: Difficulty/dual_variant_calc/delivery_provisional_advance_vs_final_settlement
    """
    ctx = setup_settled_main_pool(realized_revenue=2000, operating_costs=200)

    # Provisional variant: round2(1045 * 0.50) recorded at acceptance.
    assert_money(ctx.delivery["advance_amount"], 522.50)

    # Final settlement variant: round4(1800 / 1045), then per-member rounding.
    pool = ctx.pool_after
    assert pool["status"] == "SETTLED"
    assert_rate4(pool["final_rate_per_weighted_barrel"], 1.7225)
    assert_money(pool["coop_equity_residual"], -0.01)

    dists, meta = list_distributions(pool_id=ctx.main_pool["id"])
    assert len(dists) == 1
    dist = dists[0]
    assert_patronage_distribution(dist)
    assert_money(dist["gross_amount"], 1800.01)  # round2(1045 * 1.7225)
    assert_money(dist["retain_amount"], 360.00)  # round2(1800.01 * 0.20)
    assert_money(dist["cash_amount"], 917.51)    # 1800.01 - 360.00 - 522.50
    # The two variants value identical delivery data differently.
    assert dist["gross_amount"] != ctx.delivery["advance_amount"]


def test_rate_change_not_retroactive_and_settlement_records(api):
    """PRD §3.8: "Rate changes never apply retroactively: `advance_amount`
    values already recorded on accepted deliveries stand at the rate that was in
    force at their acceptance."
    PRD §3.8: "a **PatronageDistribution** is created in `COMPUTED` status
    recording the member's `pool_id` and `member_id`, their `weighted_barrels`
    in the pool at settle, and three amounts".
    PRD §3.8: "and `advance_paid`, the sum of `advance_amount` over the member's
    `ACCEPTED`, non-`VOIDED` deliveries tagged to this pool."
    PRD §3.8: "The pool lands in its terminal `SETTLED` status, and when every
    pool of the season has settled, the season itself advances to `SETTLED`."

    Design: Difficulty/dual_variant_calc/delivery_provisional_advance_vs_final_settlement
    """
    ctx = setup_campaign_with_pool()
    delivery = setup_accepted_delivery(ctx, 1000, 50, expected_barrels=1000,
                                       **A_SCORES)  # advance 522.50 at rate 0.50
    assert_money(delivery["advance_amount"], 522.50)

    # Rate revision while OPEN must not touch the recorded advance.
    pool_now = get_pool(ctx.main_pool["id"])
    resp = api.patch_pool(ctx.main_pool["id"],
                          patch_pool_payload(0.60, pool_now["version"]), POOL_MGR)
    updated = validate_success(resp, 200)
    assert_money(updated["provisional_advance_rate_per_barrel"], 0.60)
    assert_money(get_delivery(delivery["id"])["advance_amount"], 522.50)

    close_pool(ctx.main_pool["id"])
    settle_pool(ctx.main_pool["id"], 2000, 200)

    dists, _ = list_distributions(pool_id=ctx.main_pool["id"])
    assert len(dists) == 1
    assert dists[0]["status"] == "COMPUTED"
    assert_money(dists[0]["advance_paid"], 522.50)
    assert_money(dists[0]["weighted_barrels"], 1045)

    assert get_pool(ctx.main_pool["id"])["status"] == "SETTLED"
    assert get_season(ctx.season["id"])["status"] == "SETTLED"


def _setup_two_member_settled(api):
    """Two members with approved estimates, one ACCEPTED delivery each
    (M1: net 950 / A / weighted 1045 / advance 522.50; M2: net 800 / B /
    weighted 800 / advance 400.00), MAIN pool closed and settled 2000/200."""
    m1 = create_active_member("M100", "Alice Grower")
    m2 = create_active_member("M200", "Bob Grower")
    b1 = create_bog_for(m1["id"], name="North Bog", acres=10)
    b2 = create_bog_for(m2["id"], name="South Bog", acres=8, variety="BEN_LEAR",
                        sprinkler_demand_gpm=400)
    season = create_season()
    approve_estimate(create_estimate(b1["id"], season["id"], m1["id"],
                                     2300)["id"])
    approve_estimate(create_estimate(b2["id"], season["id"], m2["id"],
                                     1500)["id"])
    open_season(season["id"])
    station = create_station(daily_capacity_barrels=10000)
    pool = create_pool(season["id"], code="MAIN", rate=0.50, retain_pct=0.20)

    d1 = create_delivery(season["id"], b1["id"], station["id"], m1["id"],
                         scheduled_date="2026-10-10", expected_barrels=1000)
    receive_delivery(d1["id"], station["id"], 1000, 50)
    grade_delivery(d1["id"], station["id"], **A_SCORES)
    accept_delivery(d1["id"])

    d2 = create_delivery(season["id"], b2["id"], station["id"], m2["id"],
                         scheduled_date="2026-10-11", expected_barrels=900)
    receive_delivery(d2["id"], station["id"], 840, 40)
    grade_delivery(d2["id"], station["id"], **B_SCORES)
    accept_delivery(d2["id"])

    close_pool(pool["id"])
    pool_after = settle_pool(pool["id"], 2000, 200)
    return m1, m2, season, pool, pool_after


def test_settlement_rounds_per_member_then_residual(api):
    """PRD §3.8: "Settlement then evaluates in a pinned order: first the net
    pool value, `realized_revenue` minus `operating_costs` rounded half-up to
    two decimals; then the `final_rate_per_weighted_barrel`, the net pool value
    divided by `weighted_barrels_total` and rounded half-up to four decimals".
    PRD §3.8: "`gross_amount`, the member's weighted barrels times the final
    rate rounded half-up to two decimals; `retain_amount`, the gross times the
    pool's `retain_pct` rounded half-up to two decimals".
    PRD §3.8: "Whatever remains of the net pool value after the sum of all
    created distributions' gross amounts is the `coop_equity_residual`; it may
    be negative, it is retained by the co-op, and it is never reallocated to
    members."

    Design: Difficulty/combinatorial_formula/pool_settlement_round_per_member_then_residual
    """
    m1, m2, season, pool, pool_after = _setup_two_member_settled(api)

    # net pool value 1800; weighted total 1045 + 800 = 1845.
    assert_rate4(pool_after["final_rate_per_weighted_barrel"], 0.9756)

    d1, _ = list_distributions(pool_id=pool["id"], member_id=m1["id"])
    assert len(d1) == 1
    assert_money(d1[0]["gross_amount"], 1019.50)   # round2(1045 * 0.9756)
    assert_money(d1[0]["retain_amount"], 203.90)   # round2(1019.50 * 0.20)
    assert_money(d1[0]["cash_amount"], 293.10)     # 1019.50 - 203.90 - 522.50

    d2, _ = list_distributions(pool_id=pool["id"], member_id=m2["id"])
    assert len(d2) == 1
    assert_money(d2[0]["gross_amount"], 780.48)    # round2(800 * 0.9756)
    assert_money(d2[0]["retain_amount"], 156.10)   # round2(780.48 * 0.20)
    assert_money(d2[0]["cash_amount"], 224.38)     # 780.48 - 156.10 - 400.00

    # Per-member rounding first, residual last: 1019.50 + 780.48 + 0.02 == 1800.
    assert_money(pool_after["coop_equity_residual"], 0.02)


def test_distributions_created_in_member_creation_order(api):
    """PRD §3.8: "For each member with weighted barrels greater than zero in
    this pool, taken in member creation order (each member's `created_at`,
    ascending), a **PatronageDistribution** is created in `COMPUTED` status".

    Design: Difficulty/combinatorial_formula/pool_settlement_round_per_member_then_residual
    """
    m1, m2, season, pool, pool_after = _setup_two_member_settled(api)

    dists, meta = list_distributions(pool_id=pool["id"])
    assert len(dists) == 2
    assert [d["member_id"] for d in dists] == [m1["id"], m2["id"]], (
        "distributions are created in member creation order")
    assert all(d["status"] == "COMPUTED" for d in dists)
    assert get_season(season["id"])["status"] == "SETTLED", (
        "every pool settled -> the season advances to SETTLED")


def test_pool_close_reopen_cycle_restores_acceptance(api):
    """PRD §2.9: "When every pool of an `OPEN` season has reached `CLOSED` or
    `SETTLED` — and at least one pool exists — the season automatically advances
    from `OPEN` to `HARVEST_CLOSED`".
    PRD §2.9: "Reopening is symmetric: when a pool of a `HARVEST_CLOSED` season
    cycles back to `OPEN`, the season automatically reverts from
    `HARVEST_CLOSED` to `OPEN` and the quota locks are cleared".
    PRD §3.8: "A closed pool may be reopened for late adjustments while the
    season is `OPEN` or `HARVEST_CLOSED`".

    Design: Difficulty/non_linear_state_machine/pool_close_reopen_cycle
    """
    ctx = setup_campaign_with_pool()
    delivery = setup_scheduled_delivery(ctx, expected_barrels=200)

    close_pool(ctx.main_pool["id"])
    assert get_season(ctx.season["id"])["status"] == "HARVEST_CLOSED", (
        "closing the season's last OPEN pool auto-closes the season")

    reopened = transition_pool(ctx.main_pool["id"], "OPEN")
    assert reopened["status"] == "OPEN", "the pool cycles CLOSED -> OPEN"
    assert get_season(ctx.season["id"])["status"] == "OPEN", (
        "reopening reverts the season HARVEST_CLOSED -> OPEN")

    receive_delivery(delivery["id"], ctx.station["id"], 200, 10)
    grade_delivery(delivery["id"], ctx.station["id"], color_score=9.0,
                   firmness_score=9.0, foreign_matter_pct=1.0)
    accepted = accept_delivery(delivery["id"])
    assert accepted["status"] == "ACCEPTED", "the pool is usable after the cycle"


def test_pool_reopen_unlocks_quotas(api):
    """PRD §2.9: "when a pool of a `HARVEST_CLOSED` season cycles back to
    `OPEN`, the season automatically reverts from `HARVEST_CLOSED` to `OPEN`
    and the quota locks are cleared, again incrementing each affected quota's
    `version` by 1."
    PRD §3.3: "A `CoopAdmin` may pin a quota manually: the override request
    carries the desired `base_quota_barrels` together with
    `expected_quota_version`".

    Design: Difficulty/non_linear_state_machine/pool_close_reopen_cycle
    """
    ctx = setup_campaign_with_pool()
    v0 = ctx.quota["version"]

    close_pool(ctx.main_pool["id"])
    locked = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert locked["quota_locked"] is True
    assert locked["version"] == v0 + 1, "the lock cascade bumps the quota version"

    transition_pool(ctx.main_pool["id"], "OPEN")
    unlocked = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert unlocked["quota_locked"] is False, "reopen clears the quota locks"
    assert unlocked["version"] == v0 + 2

    # A well-formed override succeeds again after the unlock.
    patched = override_quota(ctx.quota["id"], 2500)
    assert_money(patched["base_quota_barrels"], 2500)


def test_pool_close_closes_season_and_locks_quotas(api):
    """PRD §2.9: "as part of that transition every member quota of the season is
    locked (`quota_locked` becomes `true`)".
    PRD §3.3: "An override attempted on a locked quota — one whose season has
    reached `HARVEST_CLOSED` — is rejected with `ERR_QUOTA_LOCKED`".

    Design: Difficulty/transitive_cascade/pool_close_closes_season_and_locks_quotas
    """
    ctx = setup_campaign_with_pool()

    close_pool(ctx.main_pool["id"])
    assert get_season(ctx.season["id"])["status"] == "HARVEST_CLOSED"

    quota = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert quota["quota_locked"] is True

    # Even with the CURRENT post-lock version, the override is refused.
    resp = api.patch_quota(
        ctx.quota["id"],
        {"base_quota_barrels": 2500, "expected_quota_version": quota["version"]},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_QUOTA_LOCKED)


def test_quota_lock_cascade_bumps_version_and_blocks_patch(api):
    """PRD §2.9: "each such locking mutation increments the affected quota's
    `version` by 1".
    PRD §2.6: "If the supplied value does not match the entity's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.3: "An override attempted on a locked quota — one whose season has
    reached `HARVEST_CLOSED` — is rejected with `ERR_QUOTA_LOCKED`".

    Design: Difficulty/transitive_cascade/pool_close_closes_season_and_locks_quotas
    """
    ctx = setup_campaign_with_pool()
    v0 = ctx.quota["version"]

    close_pool(ctx.main_pool["id"])
    locked = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert locked["version"] == v0 + 1, (
        "the lock cascade is a mutation and increments version by exactly 1")

    # The pre-lock observed version is now stale.
    resp = api.patch_quota(
        ctx.quota["id"],
        {"base_quota_barrels": 2500, "expected_quota_version": v0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # The current version matches, but the lock still refuses the override.
    resp = api.patch_quota(
        ctx.quota["id"],
        {"base_quota_barrels": 2500,
         "expected_quota_version": locked["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_QUOTA_LOCKED)


def test_duplicate_pool_code_per_season_rejected(api, pool_manager_headers):
    """PRD §3.8: "the pool `code` (`MAIN` or `OVER_QUOTA` — unique per season,
    duplicates rejected with `ERR_DUPLICATE_POOL_CODE`)".

    Design: Corner/validations/duplicate_pool_code_per_season_rejected
    """
    season = create_season()
    validate_success(api.create_pool(create_pool_payload(season["id"]),
                                     pool_manager_headers), 201)
    resp = api.create_pool(
        create_pool_payload(season["id"],
                            provisional_advance_rate_per_barrel=0.60,
                            retain_pct=0.10),
        pool_manager_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_POOL_CODE)


def test_pool_close_blocked_by_graded_pipeline_delivery(api):
    """PRD §3.8: "Closing a pool — the `PoolManager` moving it `OPEN → CLOSED` —
    is allowed only when the pool's season has no delivery still in `RECEIVED`,
    `GRADED`, or `DISPUTED` status (`ERR_POOL_HAS_OPEN_DELIVERIES` otherwise)".

    Design: Corner/validations/pool_close_blocked_by_graded_pipeline_delivery
    """
    ctx = setup_campaign_with_pool()
    delivery = setup_graded_delivery(ctx, 150, 50, expected_barrels=150,
                                     **B_SCORES)
    assert delivery["status"] == "GRADED"

    resp = api.transition_pool(ctx.main_pool["id"], {"to": "CLOSED"}, POOL_MGR)
    validate_error(resp, ApiErrorId.ERR_POOL_HAS_OPEN_DELIVERIES)
    assert get_pool(ctx.main_pool["id"])["status"] == "OPEN"


def test_settle_costs_exceed_revenue_rejected(api):
    """PRD §3.8: "the money must be sane — `operating_costs` non-negative and
    `realized_revenue` at least `operating_costs`, and when the pool's
    `weighted_barrels_total` is zero both figures must be exactly zero — with
    violations rejected as `ERR_SETTLEMENT_INPUT_INVALID`."

    Design: Corner/validations/settle_costs_exceed_revenue_rejected
    """
    ctx = setup_campaign_with_pool()
    close_pool(ctx.main_pool["id"])
    pool = get_pool(ctx.main_pool["id"])

    resp = api.settle_pool(ctx.main_pool["id"],
                           settle_pool_payload(100, 200, pool["version"]),
                           POOL_MGR)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_INPUT_INVALID)
    assert get_pool(ctx.main_pool["id"])["status"] == "CLOSED"


def test_pool_settle_terminal_lockdown_and_season_settled(api):
    """PRD §3.8: "then the `final_rate_per_weighted_barrel`, the net pool value
    divided by `weighted_barrels_total` and rounded half-up to four decimals —
    or zero when the pool holds no weighted barrels, in which case no
    distributions are created at all."
    PRD §3.8: "The pool lands in its terminal `SETTLED` status, and when every
    pool of the season has settled, the season itself advances to `SETTLED`."
    PRD §3.8: "Any transition requested out of order — settling an `OPEN` pool,
    paying a `COMPUTED` distribution, reopening a `SETTLED` pool — is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pool_settle_terminal_lockdown_and_season_settled
    """
    ctx = setup_campaign_with_pool()
    close_pool(ctx.main_pool["id"])

    settled = settle_pool(ctx.main_pool["id"], 0, 0)
    assert settled["status"] == "SETTLED"
    assert_rate4(settled["final_rate_per_weighted_barrel"], 0)

    dists, meta = list_distributions(pool_id=ctx.main_pool["id"])
    assert len(dists) == 0, "no weighted barrels -> no distributions"
    assert get_season(ctx.season["id"])["status"] == "SETTLED"

    resp = api.transition_pool(ctx.main_pool["id"], {"to": "OPEN"}, POOL_MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_distribution_pay_before_approve_invalid_and_fk_reverse_list(api):
    """PRD §3.8: "the `PoolManager` first approves a distribution (`COMPUTED →
    APPROVED`) and only then marks it paid (`APPROVED → PAID`), the terminal
    state."
    PRD §3.8: "Any transition requested out of order — settling an `OPEN` pool,
    paying a `COMPUTED` distribution, reopening a `SETTLED` pool — is rejected
    with `ERR_INVALID_STATE`."
    PRD §3.8: "Distribution listings accept `pool_id`, `member_id`, and `status`
    filters."

    Design: Corner/state_machines/distribution_pay_before_approve_invalid_and_fk_reverse_list
    """
    ctx = setup_settled_main_pool(realized_revenue=2000, operating_costs=200)

    dists, meta = list_distributions(pool_id=ctx.main_pool["id"])
    assert len(dists) == 1, "exactly one distribution is reverse-reachable from the pool"
    dist = dists[0]
    assert dist["member_id"] == ctx.member["id"]
    assert dist["status"] == "COMPUTED"

    resp = api.transition_distribution(dist["id"], {"to": "PAID"}, POOL_MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    # The defined path COMPUTED -> APPROVED -> PAID works in order.
    approved = validate_success(
        api.transition_distribution(dist["id"], {"to": "APPROVED"}, POOL_MGR), 200)
    assert approved["status"] == "APPROVED"
    paid = validate_success(
        api.transition_distribution(dist["id"], {"to": "PAID"}, POOL_MGR), 200)
    assert paid["status"] == "PAID"
