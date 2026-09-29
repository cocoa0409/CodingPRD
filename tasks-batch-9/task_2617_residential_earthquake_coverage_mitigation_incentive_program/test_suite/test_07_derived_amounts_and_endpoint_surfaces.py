"""Derived money and the endpoint surfaces that publish it.

This module exercises the arithmetic the programme performs on top of the
records a caller creates: the gross incurred loss an earthquake accumulates from
the claims that have actually been finally adjusted, the hazard base premium a
dwelling's soil class and structure type produce out of the rating table, the
retrofit award that is capped by scope cost, matched by income tier and then
clamped to the programme maximum, the way a reserved award fills its own income
tier's bucket before spilling into the shared fallback bucket, and the way a
post-event shortfall is spread across the assessable carriers in market-share
order with the last rank absorbing the rounding drift. It then exercises the
endpoint surfaces that expose the same domain: the reinsurance tower's create,
read, status change and filtered list; the regulator's compliance ladder over a
participating insurer; the three-way link a mandatory offer draws between
insurer, policyholder and dwelling; the derived counters an insurer read returns
from its offer history; and the forty-five day window inside which an in-force
term may be renewed.
"""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    GRANT_REVIEWER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    assertions,
    constants,
    factories,
    fixtures,
)
from test_helpers.test_users import make_insurer_headers, make_policyholder_headers


def _dec(value):
    """Exact decimal arithmetic, so a rating factor never drifts in binary float."""
    return Decimal(str(value))


def _half_up(value):
    """Round a decimal amount half up to whole cents, exactly once."""
    return int(_dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _instant(value):
    """Parse a UTC instant so two instants compare by value, not by spelling."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _clock_string(moment):
    """Render an instant in the form the logical clock accepts."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_01_event_gross_counts_only_the_finally_adjusted_claim(api):
    """A provisionally adjusted claim contributes nothing to the event's gross.

    "The gross is the event's `aggregate_incurred_cents`, which is the sum of
    `final_payable_cents` over exactly those of its claims whose
    `adjustment_status` is `FINAL_ADJUSTED` or `CLOSED`; claims still at
    `FNOL_RECEIVED` or `PROVISIONAL_ADJUSTED`, and claims that were `DENIED`,
    contribute nothing."

    "Both adjustment passes begin from the same deductible, and it is computed
    from the term snapshot rather than the live dwelling: `deductible_applied_cents`
    is the policy's `rated_dwelling_limit_cents` multiplied by its `deductible_pct`
    and divided by one hundred, rounded half up to whole cents."

    "First, `retained_cents` becomes the smaller of the gross and the event's
    `retention_cents`."

    "The event's `claim_count` rises by one and its `version` rises by one."

    Design: Corner/calculations/event_gross_counts_only_finalized_claims
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    settled = fixtures.setup_bound_policy(api)
    pending = fixtures.setup_bound_policy(api)

    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    tower = fixtures.setup_declared_event(
        api,
        layer_overrides={"limit_cents": 50000000, "ceded_pct": 0.9},
    )
    event_id = tower["event"]["id"]
    layer_id = tower["layer"]["id"]

    settled["event"] = tower["event"]
    settled = fixtures.setup_finally_adjusted_claim(
        api, ctx=settled, structural_damage_cents=10000000
    )

    pending["event"] = validate_success(
        api.get_catastrophe_event(event_id, PROGRAM_ADMIN_HEADERS)
    )
    pending = fixtures.setup_provisionally_adjusted_claim(
        api, ctx=pending, structural_damage_cents=5000000
    )

    snapshot = settled["policy"]["rated_dwelling_limit_cents"]
    deductible = _half_up(_dec(snapshot) * _dec(settled["policy"]["deductible_pct"]) / _dec(100))
    finalized = settled["claim"]
    assert finalized["adjustment_status"] == "FINAL_ADJUSTED"
    assert finalized["deductible_applied_cents"] == deductible
    assert finalized["final_payable_cents"] == 10000000 - deductible
    assertions.assert_settlement_parts_sum(finalized, 10000000 - deductible)

    unfinished = pending["claim"]
    assert unfinished["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assert unfinished["provisional_payable_cents"] == 5000000 - deductible
    assert unfinished["final_payable_cents"] == 0

    event = validate_success(api.get_catastrophe_event(event_id, PROGRAM_ADMIN_HEADERS))
    assert event["aggregate_incurred_cents"] == 10000000 - deductible
    assert event["retained_cents"] == min(
        event["aggregate_incurred_cents"], event["retention_cents"]
    )
    assert event["ceded_total_cents"] == 0
    assert event["uncovered_cents"] == 0
    assert event["status"] == "LOSS_AGGREGATION"
    assert event["claim_count"] == 2
    assertions.assert_event_loss_conserved(event)

    layer = validate_success(api.get_reinsurance_layer(layer_id, PROGRAM_ADMIN_HEADERS))
    assert layer["ceded_cents"] == 0


def test_02_soil_and_structure_factors_come_from_the_rating_table(api):
    """Two dwellings identical but for soil class and structure type rate apart.

    "First, the exposure is expressed in units of one thousand dollars of Coverage A
    limit: divide `dwelling_limit_cents` by one hundred thousand, which is the number of
    cents in one thousand dollars."

    "Second, take the county's base rate per thousand dollars of limit, which is
    180 cents for `TIER_1`, 320 cents for `TIER_2` and 520 cents for `TIER_3`."

    "the **soil factor** — 0.85 for `ROCK`, 1.00 for `STIFF`, 1.25 for `SOFT` and
    1.55 for `LIQUEFACTION`;"

    "the **structure factor** — 1.00 for `WOOD_FRAME_SLAB`, 1.30 for
    `WOOD_FRAME_CRIPPLE_WALL`, 1.85 for `MASONRY_URM` and 1.45 for `MOBILE_HOME`;"

    "the **age factor** — 1.20 when `year_built` is 1979 or earlier, and 1.00 for
    anything built in 1980 or later;"

    "the **deductible factor** — 1.35 at a 5 percent deductible, 1.00 at 10 percent,
    0.86 at 15 percent, 0.75 at 20 percent and 0.66 at 25 percent;"

    "the **high-limit load** — 1.15 when `dwelling_limit_cents` is at least 75,000,000
    cents, which is a Coverage A limit of seven hundred and fifty thousand dollars or
    more, and 1.00 below that."

    "From that effective posture, the factor is 0.75 when the posture is `VERIFIED`
    *and* the `structure_type` is `WOOD_FRAME_CRIPPLE_WALL` *and* the
    `verified_retrofit_scope` is `CRIPPLE_WALL_BRACING` — the deepest discount in the
    program, reserved for the one retrofit that addresses the one failure mode; 0.90
    when the posture is `VERIFIED` for any other combination of structure and scope;
    0.95 when the effective posture is `SELF_DECLARED`, which can only ever happen under
    the quote variant; and 1.00 when the effective posture is `NONE`."

    "Multiply the base rate per thousand by the exposure units and then by all six
    factors, in that order, keeping exact decimal arithmetic throughout."

    "Clamp the unrounded product upward to a floor of 18,000 cents and downward to a
    ceiling of 4,000,000 cents — that is, no annual base premium is ever less than one
    hundred and eighty dollars or more than forty thousand dollars."

    "Only after the clamp is the value rounded, half up, exactly once, to whole cents,
    and that integer becomes `base_premium_cents`."

    "Finally, `annual_premium_cents` — the amount actually billed — is
    `base_premium_cents` less whatever `mitigation_discount_cents` currently stands at,
    which at quote time is zero."

    "The result is written to `base_premium_cents`, and `rating_variant` records which
    of the two variants produced it, taking the value `QUOTE_TIME` or `RENEWAL_TIME`."

    Design: Corner/calculations/soil_and_structure_constants_are_applied_from_the_table
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    limit_cents = 30000000
    deductible_pct = 20
    hazard_tier = "TIER_3"
    year_built = 1960

    def expected_base_premium(soil_class, structure_type):
        exposure_units = _dec(limit_cents) / _dec(constants.EXPOSURE_UNIT_CENTS)
        product = (
            _dec(constants.BASE_RATE_PER_1000[hazard_tier])
            * exposure_units
            * _dec(constants.SOIL_FACTOR[soil_class])
            * _dec(constants.STRUCTURE_FACTOR[structure_type])
            * _dec(constants.AGE_FACTOR_PRE_CODE)
            * _dec(constants.RETROFIT_FACTOR_NONE)
            * _dec(constants.DEDUCTIBLE_FACTOR[deductible_pct])
        )
        assert limit_cents < constants.HIGH_LIMIT_THRESHOLD_CENTS
        floor = _dec(constants.MIN_PREMIUM_CENTS)
        ceiling = _dec(constants.MAX_PREMIUM_CENTS)
        return _half_up(min(max(product, floor), ceiling))

    def quote_for(soil_class, structure_type):
        return fixtures.setup_quoted_policy(
            api,
            dwelling_overrides={
                "county_hazard_tier": hazard_tier,
                "soil_class": soil_class,
                "structure_type": structure_type,
                "year_built": year_built,
                "dwelling_limit_cents": limit_cents,
            },
            deductible_pct=deductible_pct,
        )["policy"]

    worst = quote_for("LIQUEFACTION", "MASONRY_URM")
    best = quote_for("ROCK", "WOOD_FRAME_SLAB")

    assert worst["base_premium_cents"] == expected_base_premium(
        "LIQUEFACTION", "MASONRY_URM"
    )
    assert best["base_premium_cents"] == expected_base_premium("ROCK", "WOOD_FRAME_SLAB")
    assert worst["base_premium_cents"] > best["base_premium_cents"]

    for quote in (worst, best):
        assert quote["rating_variant"] == "QUOTE_TIME"
        assert quote["mitigation_discount_cents"] == 0
        assert quote["annual_premium_cents"] == quote["base_premium_cents"]
        assert constants.MIN_PREMIUM_CENTS <= quote["base_premium_cents"]
        assert quote["base_premium_cents"] <= constants.MAX_PREMIUM_CENTS
        assertions.assert_premium_ledger_consistent(quote)


def test_03_mobile_home_award_is_capped_then_matched_then_clamped(api):
    """A mobile home's award is trimmed by its scope cap and then by the maximum.

    "A new application opens in `SUBMITTED` with `review_round` at zero,
    `approved_amount_cents` at zero, `funded_from_bucket` at `NONE` and
    `denial_reason` an empty string."

    "Each structure type carries a scope cost cap: 1,000,000 cents — ten thousand
    dollars — for `WOOD_FRAME_CRIPPLE_WALL`, and 600,000 cents — six thousand
    dollars — for `MOBILE_HOME`."

    "The eligible cost is the smaller of the applicant's
    `project_cost_estimate_cents` and that cap."

    "Multiply the eligible cost by the match percentage for the applicant's
    `income_tier` — the whole eligible cost for `TIER_LOW`, three quarters of it
    for `TIER_MID`, and one half of it for `TIER_ANY` — round the product half up
    to whole cents, and then clamp the result down to a programme maximum of
    300,000 cents, three thousand dollars."

    Design: Corner/calculations/grant_award_is_capped_by_scope_then_matched_then_clamped
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    estimate_cents = 900000
    ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides={"structure_type": "MOBILE_HOME"}
    )
    ctx = fixtures.setup_submitted_grant(
        api,
        ctx=ctx,
        cycle_overrides={"program_track": "BRACE_AND_BOLT"},
        income_tier="TIER_LOW",
        project_cost_estimate_cents=estimate_cents,
    )
    submitted = ctx["grant"]
    assert submitted["status"] == "SUBMITTED"
    assert submitted["review_round"] == 0
    assert submitted["approved_amount_cents"] == 0
    assert submitted["funded_from_bucket"] == "NONE"
    assert submitted["denial_reason"] == ""

    under_review = validate_success(
        api.begin_grant_review(submitted["id"], None, GRANT_REVIEWER_HEADERS)
    )
    assert under_review["status"] == "UNDER_REVIEW"

    approved = validate_success(
        api.review_grant(
            submitted["id"],
            factories.review_grant_payload("APPROVE"),
            GRANT_REVIEWER_HEADERS,
        )
    )
    eligible_cost = min(estimate_cents, constants.SCOPE_COST_CAP["MOBILE_HOME"])
    matched = _half_up(_dec(eligible_cost) * _dec(constants.MATCH_PCT["TIER_LOW"]))
    expected_award = min(matched, constants.MAX_GRANT_CENTS)

    assert eligible_cost == constants.SCOPE_COST_CAP["MOBILE_HOME"]
    assert matched > constants.MAX_GRANT_CENTS
    assert approved["status"] == "APPROVED"
    assert approved["approved_amount_cents"] == expected_award
    assert approved["funded_from_bucket"] == "NONE"
    assertions.assert_retrofit_grant_shape(approved)


def test_04_cripple_wall_award_rounds_the_match_half_up(api):
    """A three-quarter match on an odd estimate rounds half up to whole cents.

    "The eligible cost is the smaller of the applicant's
    `project_cost_estimate_cents` and that cap."

    "Multiply the eligible cost by the match percentage for the applicant's
    `income_tier` — the whole eligible cost for `TIER_LOW`, three quarters of it
    for `TIER_MID`, and one half of it for `TIER_ANY` — round the product half up
    to whole cents, and then clamp the result down to a programme maximum of
    300,000 cents, three thousand dollars."

    Design: Corner/calculations/grant_award_is_capped_by_scope_then_matched_then_clamped
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    estimate_cents = 333333
    ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides={"structure_type": "WOOD_FRAME_CRIPPLE_WALL"}
    )
    ctx = fixtures.setup_approved_grant(
        api,
        ctx=ctx,
        cycle_overrides={"program_track": "BRACE_AND_BOLT"},
        income_tier="TIER_MID",
        project_cost_estimate_cents=estimate_cents,
    )

    eligible_cost = min(
        estimate_cents, constants.SCOPE_COST_CAP["WOOD_FRAME_CRIPPLE_WALL"]
    )
    matched = _half_up(_dec(eligible_cost) * _dec(constants.MATCH_PCT["TIER_MID"]))
    expected_award = min(matched, constants.MAX_GRANT_CENTS)

    assert eligible_cost == estimate_cents
    assert matched < constants.MAX_GRANT_CENTS
    assert ctx["grant"]["status"] == "APPROVED"
    assert ctx["grant"]["approved_amount_cents"] == expected_award


def test_05_slab_structure_is_outside_the_retrofit_scheme(api):
    """A slab dwelling carries a zero cap, so approval is refused outright.

    "`WOOD_FRAME_SLAB` and `MASONRY_URM` carry a cap of zero, which is the
    programme's way of saying they are outside the retrofit scheme entirely; an
    approval attempt on either is refused with `ERR_STRUCTURE_NOT_GRANT_ELIGIBLE`."

    Design: Corner/calculations/grant_award_is_capped_by_scope_then_matched_then_clamped
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides={"structure_type": "WOOD_FRAME_SLAB"}
    )
    ctx = fixtures.setup_grant_under_review(
        api,
        ctx=ctx,
        cycle_overrides={"program_track": "BRACE_AND_BOLT"},
        income_tier="TIER_LOW",
        project_cost_estimate_cents=900000,
    )
    assert constants.SCOPE_COST_CAP["WOOD_FRAME_SLAB"] == 0

    validate_error(
        api.review_grant(
            ctx["grant"]["id"],
            factories.review_grant_payload("APPROVE"),
            GRANT_REVIEWER_HEADERS,
        ),
        ApiErrorId.STRUCTURE_NOT_GRANT_ELIGIBLE,
    )

    unchanged = validate_success(
        api.get_retrofit_grant(ctx["grant"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["approved_amount_cents"] == 0
    assert unchanged["funded_from_bucket"] == "NONE"


def test_06_reservation_fills_the_income_tier_bucket_then_spills_into_the_fallback(api):
    """Two awards exhaust the low-income bucket and a third draws on the fallback.

    "The `TIER_LOW` bucket's cap is sixty percent of `total_pool_cents`, the
    `TIER_MID` bucket's cap is forty percent, and the shared `TIER_ANY` bucket's cap
    is twenty-five percent — one hundred and twenty-five percent of the pool in
    total — each cap computed by multiplying `total_pool_cents` by its percentage and
    rounding half up to whole cents."

    "Step one: if the applicant's own income tier's usage plus this award is no
    greater than that tier's cap, the award draws from the applicant's own tier and
    `funded_from_bucket` records it."

    "Step two: otherwise, provided the applicant's tier is not already `TIER_ANY`,
    if the `TIER_ANY` bucket's usage plus this award is no greater than the
    `TIER_ANY` cap, the award draws from `TIER_ANY` — that shared bucket is the
    single fallback, and there is no further cascade."

    "On success the ledger moves as a pair — `reserved_cents` rises by the award and
    `uncommitted_cents` is recomputed as `total_pool_cents` less `reserved_cents`
    less `disbursed_cents` — the cycle's `version` rises by one, and the dwelling's
    `grant_lifetime_count` rises by one."

    Design: Corner/calculations/grant_pool_fills_the_tier_bucket_then_overflows_into_tier_any
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    pool_cents = 1000000
    cycle = fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=pool_cents
    )
    low_cap = _half_up(_dec(pool_cents) * _dec(constants.TIER_POOL_PCT["TIER_LOW"]))
    any_cap = _half_up(_dec(pool_cents) * _dec(constants.TIER_POOL_PCT["TIER_ANY"]))
    assert low_cap == 600000
    assert any_cap == 250000

    def reserve(estimate_cents):
        ctx = fixtures.setup_bound_policy(
            api, dwelling_overrides={"structure_type": "WOOD_FRAME_CRIPPLE_WALL"}
        )
        return fixtures.setup_reserved_grant(
            api,
            ctx=ctx,
            cycle=cycle,
            income_tier="TIER_LOW",
            project_cost_estimate_cents=estimate_cents,
        )

    first = reserve(300000)
    second = reserve(300000)
    third = reserve(200000)

    awards = [ctx["grant"]["approved_amount_cents"] for ctx in (first, second, third)]
    assert awards == [300000, 300000, 200000]
    for award in awards:
        assert award <= constants.MAX_GRANT_CENTS

    assert first["grant"]["status"] == "FUNDS_RESERVED"
    assert first["grant"]["funded_from_bucket"] == "TIER_LOW"
    assert second["grant"]["funded_from_bucket"] == "TIER_LOW"
    assert awards[0] + awards[1] == low_cap
    assert second["grant"]["status"] == "FUNDS_RESERVED"

    assert awards[0] + awards[1] + awards[2] > low_cap
    assert awards[2] <= any_cap
    assert third["grant"]["funded_from_bucket"] == "TIER_ANY"
    assert third["grant"]["status"] == "FUNDS_RESERVED"

    final_cycle = validate_success(
        api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert final_cycle["reserved_cents"] == sum(awards)
    assert final_cycle["disbursed_cents"] == 0
    assert final_cycle["uncommitted_cents"] == pool_cents - sum(awards)
    assert final_cycle["version"] == cycle["version"] + len(awards)
    assertions.assert_grant_pool_conserved(final_cycle)

    spilled_dwelling = validate_success(
        api.get_dwelling(third["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert spilled_dwelling["grant_lifetime_count"] == 1


def test_07_assessment_ranks_by_market_share_and_the_last_rank_absorbs_the_drift(api):
    """The shortfall spreads by share, ties break on enrolment order, drift lands last.

    "The shortfall is the event's current `uncovered_cents`, pinned into
    `assessment_shortfall_cents` at levy time."

    "`admin_loading_cents` is the shortfall multiplied by that rate, rounded half up
    to whole cents, and `assessment_total_cents` is the shortfall plus the loading."

    "An insurer is assessable when its `compliance_status` is `COMPLIANT` or
    `UNDER_REVIEW` and its `market_share_pct` is strictly greater than zero."

    "The denominator is the sum of `market_share_pct` over the **assessable**
    insurers only, which is emphatically not one hundred: excluding a sanctioned
    carrier re-spreads its share across the remainder rather than leaving the
    assessment short."

    "The assessable insurers are then ordered by `market_share_pct` descending and,
    where two shares tie, by `created_at` ascending, and each is given an
    `allocation_rank` starting at 1."

    "For every rank except the last, `assessed_cents` is `assessment_total_cents`
    multiplied by that insurer's `market_share_pct` and divided by the denominator,
    rounded half up to whole cents, with `absorbs_remainder` false."

    "For the last rank, `assessed_cents` is `assessment_total_cents` less the sum of
    all the earlier ranks' `assessed_cents`, and `absorbs_remainder` is true — so the
    allocations sum to `assessment_total_cents` exactly, to the cent, with the
    rounding drift of every earlier rank absorbed by the last."

    "Each assessed insurer's `assessment_balance_cents` rises by its own
    `assessed_cents`, and the event's `version` rises by one."

    Design: Corner/calculations/assessment_allocations_rank_by_share_and_the_last_rank_absorbs_the_remainder
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    alpha = fixtures.create_insurer(api, market_share_pct=3.0)
    bravo = fixtures.create_insurer(api, market_share_pct=2.0)
    charlie = fixtures.create_insurer(api, market_share_pct=2.0)
    zulu = fixtures.create_insurer(api, market_share_pct=0.0)

    holder = fixtures.create_policyholder(api)
    dwelling = fixtures.create_dwelling(
        api, holder["id"], dwelling_limit_cents=300000000
    )
    ctx = fixtures.setup_bound_policy(
        api,
        parties={"insurer": alpha, "policyholder": holder, "dwelling": dwelling},
        deductible_pct=5,
    )

    fixtures.set_clock(api, "2026-09-06T00:00:00Z")
    ctx.update(
        fixtures.setup_declared_event(
            api,
            layer_overrides={"limit_cents": 50000000, "ceded_pct": 0.9},
        )
    )
    ctx = fixtures.setup_finally_adjusted_claim(
        api, ctx=ctx, structural_damage_cents=250000000
    )

    exhausted = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert exhausted["status"] == "CAPACITY_EXHAUSTED"
    shortfall = exhausted["uncovered_cents"]
    assert shortfall > 0
    assert shortfall < constants.BAND_1_CENTS

    levied = validate_success(
        api.levy_assessment(ctx["event"]["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    expected_loading = _half_up(_dec(shortfall) * _dec(constants.LOADING_RATE_SMALL))
    expected_total = shortfall + expected_loading
    assert levied["status"] == "ASSESSMENT_LEVIED"
    assert levied["assessment_shortfall_cents"] == shortfall
    assert levied["admin_loading_cents"] == expected_loading
    assert levied["assessment_total_cents"] == expected_total
    assert levied["version"] == exhausted["version"] + 1

    denominator = _dec(3.0) + _dec(2.0) + _dec(2.0)
    first_share = _half_up(_dec(expected_total) * _dec(3.0) / denominator)
    second_share = _half_up(_dec(expected_total) * _dec(2.0) / denominator)
    third_share = expected_total - first_share - second_share

    allocations = fixtures.get_allocations_for_event(api, ctx["event"]["id"])
    assert len(allocations) == 3
    for row in allocations:
        assertions.assert_assessment_allocation_shape(row)
        assert row["event_id"] == ctx["event"]["id"]

    assert [row["allocation_rank"] for row in allocations] == [1, 2, 3]
    assert [row["insurer_id"] for row in allocations] == [
        alpha["id"],
        bravo["id"],
        charlie["id"],
    ]
    assert [row["assessed_cents"] for row in allocations] == [
        first_share,
        second_share,
        third_share,
    ]
    assert [row["absorbs_remainder"] for row in allocations] == [False, False, True]
    assert third_share != second_share
    assertions.assert_assessment_allocations_sum(allocations, expected_total)

    assert zulu["id"] not in [row["insurer_id"] for row in allocations]
    for insurer, expected_balance in (
        (alpha, first_share),
        (bravo, second_share),
        (charlie, third_share),
        (zulu, 0),
    ):
        current = validate_success(api.get_insurer(insurer["id"], PROGRAM_ADMIN_HEADERS))
        assertions.assert_insurer_assessment_balance(current, expected_balance)


def _build_tower(api):
    """Register a 2025 layer plus a two-layer 2026 tower that tiles without a gap."""
    other_year = validate_success(
        api.create_reinsurance_layer(
            factories.create_reinsurance_layer_payload(
                treaty_year=2025,
                layer_index=1,
                attachment_point_cents=100000000,
                limit_cents=100000000,
                ceded_pct=0.5,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        expected_status=201,
    )
    lower = validate_success(
        api.create_reinsurance_layer(
            factories.create_reinsurance_layer_payload(
                treaty_year=2026,
                layer_index=1,
                attachment_point_cents=100000000,
                limit_cents=50000000,
                ceded_pct=0.8,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        expected_status=201,
    )
    upper = validate_success(
        api.create_reinsurance_layer(
            factories.create_reinsurance_layer_payload(
                treaty_year=2026,
                layer_index=2,
                attachment_point_cents=150000000,
                limit_cents=200000000,
                ceded_pct=0.6,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        expected_status=201,
    )
    return other_year, lower, upper


def test_08_reinsurance_layer_is_created_read_back_and_listed_by_treaty_year(api):
    """A layer opens active with nothing ceded and lists inside its own treaty year.

    "Each layer of a treaty year's reinsurance tower is its own row, carrying the
    `treaty_year` it belongs to, its `layer_index` — the waterfall position,
    ascending from 1 and unique within the year — its `attachment_point_cents`, the
    gross incurred loss at which the layer begins to respond, its `limit_cents`, the
    width of the layer, and its `ceded_pct`, the fraction of the layer's exposure
    ceded to reinsurers, which must be strictly greater than zero and no more than
    one."

    "A new layer opens `ACTIVE` with `ceded_cents` at zero."

    "Collections are always returned sorted by `created_at` in ascending order, so
    that a stable offset walk sees each row exactly once; where a domain section
    describes a different presentation order (the reinsurance tower in layer order,
    assessment allocations in levy-rank order), that order is a property of the data
    the caller reads back, not a change to the default sort."

    Design: Corner/endpoints/reinsurance_layer_create_read_update_status_and_filtered_list
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    other_year, lower, upper = _build_tower(api)

    assertions.assert_reinsurance_layer_shape(lower)
    assert lower["treaty_year"] == 2026
    assert lower["layer_index"] == 1
    assert lower["attachment_point_cents"] == 100000000
    assert lower["limit_cents"] == 50000000
    assert lower["status"] == "ACTIVE"
    assert lower["ceded_cents"] == 0
    assert lower["version"] == 1

    assert upper["attachment_point_cents"] == (
        lower["attachment_point_cents"] + lower["limit_cents"]
    )

    read_back = validate_success(
        api.get_reinsurance_layer(lower["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert read_back["id"] == lower["id"]
    assert read_back["status"] == "ACTIVE"
    assert read_back["ceded_cents"] == 0

    rows, meta = validate_paginated(
        api.list_reinsurance_layers({"treaty_year": 2026}, PROGRAM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2
    assert [row["layer_index"] for row in rows] == [1, 2]
    assert [row["id"] for row in rows] == [lower["id"], upper["id"]]
    assert other_year["id"] not in [row["id"] for row in rows]


def test_09_lapsing_a_layer_bumps_its_version_and_narrows_the_filtered_tower(api):
    """A lapsed layer leaves the tower list when treaty year and status are combined.

    "Program staff may lapse or reinstate a layer by supplying a `status` of `LAPSED`
    or `ACTIVE`; the change takes effect on the next run of the loss waterfall, which
    excludes or re-includes that layer accordingly."

    "Any operation that changes a row refreshes that row's `updated_at` and
    increments its `version`, including the cascaded mutations that a single request
    performs on rows other than its direct target."

    "Filter parameters on list endpoints are all optional and are combined
    conjunctively: supplying both `insurer_id` and `status` on the offer list returns
    only that insurer's offers in that status."

    Design: Corner/endpoints/reinsurance_layer_create_read_update_status_and_filtered_list
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    _other_year, lower, upper = _build_tower(api)

    lapsed = validate_success(
        api.set_reinsurance_layer_status(
            lower["id"], factories.layer_status_payload("LAPSED"), PROGRAM_ADMIN_HEADERS
        )
    )
    assert lapsed["status"] == "LAPSED"
    assert lapsed["version"] == lower["version"] + 1
    assert _instant(lapsed["updated_at"]) >= _instant(lower["updated_at"])

    rows, meta = validate_paginated(
        api.list_reinsurance_layers(
            {"treaty_year": 2026, "status": "ACTIVE"}, PROGRAM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [upper["id"]]

    reinstated = validate_success(
        api.set_reinsurance_layer_status(
            lower["id"], factories.layer_status_payload("ACTIVE"), PROGRAM_ADMIN_HEADERS
        )
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == lapsed["version"] + 1

    rows, meta = validate_paginated(
        api.list_reinsurance_layers(
            {"treaty_year": 2026, "status": "ACTIVE"}, PROGRAM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [lower["id"], upper["id"]]


def test_10_compliance_action_walks_the_regulator_ladder_end_to_end(api):
    """A carrier goes under review, is sanctioned, reinstated and finally withdrawn.

    "A freshly enrolled insurer starts with `status` set to `ACTIVE` and
    `compliance_status` set to `COMPLIANT`, and with all five of its running counters
    at zero: `offers_recorded_count`, `undocumented_decline_count`,
    `last_take_up_rate_bp`, `assessment_balance_cents` and `policies_bound_count`."

    "A decline additionally carries `decline_documented`, a boolean that defaults to
    false when the field is omitted."

    "Within that set, the numerator is the count in `ACCEPTED` and the denominator is
    the count of all considered offers; the take-up rate in basis points is ten
    thousand multiplied by the accepted count divided by the considered count,
    rounded half up to a whole basis point, and is reported as zero when nothing was
    considered at all."

    "The evaluation writes the result to `last_take_up_rate_bp`, writes the considered
    count to `offers_recorded_count`, and rewrites `undocumented_decline_count` as the
    count of considered offers that are `DECLINED` with `decline_documented` false."

    "If the recomputed `undocumented_decline_count` is at least three, the insurer's
    `compliance_status` becomes `SANCTIONED`; this path may jump straight from
    `COMPLIANT` without passing through `UNDER_REVIEW`."

    "Otherwise, if at least four offers were considered *and* the computed rate is
    strictly below 2500 basis points — that is, below a twenty-five percent take-up —
    *and* the insurer is currently `COMPLIANT`, then `compliance_status` moves
    `COMPLIANT → UNDER_REVIEW`."

    "`SANCTION` moves `UNDER_REVIEW → SANCTIONED` and is refused with
    `ERR_INSURER_NOT_SANCTIONED` when the carrier is not currently under review; a
    sanctioned insurer can neither bind nor renew policies and is excluded from the
    assessable pool."

    "`REINSTATE` moves `SANCTIONED → COMPLIANT` and is likewise refused with
    `ERR_INSURER_NOT_SANCTIONED` when the carrier is not sanctioned; reinstatement
    deliberately does **not** reset `undocumented_decline_count`, because that counter
    is the audit trail of the original failure."

    "`WITHDRAW` moves the participation dimension `ACTIVE → WITHDRAWN` and is refused
    with `ERR_INSURER_ALREADY_WITHDRAWN` if the carrier has already withdrawn; a
    withdrawn insurer writes no new business but its existing in-force policies are
    untouched, it may still renew them, and — importantly for the assessment
    machinery — it remains assessable for events that occurred before its
    withdrawal."

    Design: Corner/endpoints/insurer_compliance_action_walks_the_whole_compliance_ladder
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    assertions.assert_insurer_shape(insurer)
    assert insurer["status"] == "ACTIVE"
    assert insurer["compliance_status"] == "COMPLIANT"
    assert insurer["offers_recorded_count"] == 0
    assert insurer["undocumented_decline_count"] == 0
    assert insurer["last_take_up_rate_bp"] == 0

    households = [
        fixtures.setup_pending_offer(
            api, parties=fixtures.setup_parties(api, insurer=insurer)
        )
        for _ in range(5)
    ]

    def answer(household, payload):
        return validate_success(
            api.respond_to_offer(
                household["offer"]["id"],
                payload,
                make_policyholder_headers(household["policyholder"]["id"]),
            )
        )

    answer(households[0], factories.respond_to_offer_payload("ACCEPT"))
    answer(households[1], factories.respond_to_offer_payload("DECLINE"))
    answer(households[2], factories.respond_to_offer_payload("DECLINE"))
    for household in households[3:]:
        answer(
            household,
            factories.respond_to_offer_payload("DECLINE", decline_documented=True),
        )

    validate_error(
        api.insurer_compliance_action(
            insurer["id"],
            factories.compliance_action_payload("SANCTION"),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INSURER_NOT_SANCTIONED,
    )

    scored = validate_success(
        api.insurer_take_up_evaluation(
            insurer["id"],
            factories.take_up_evaluation_payload(
                constants.CLOCK_EPOCH, "2026-08-02T00:00:00Z"
            ),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    expected_rate_bp = _half_up(_dec(10000) * _dec(1) / _dec(5))
    assert scored["offers_recorded_count"] == 5
    assert scored["undocumented_decline_count"] == 2
    assert scored["undocumented_decline_count"] < constants.UNDOCUMENTED_DECLINE_LIMIT
    assert scored["last_take_up_rate_bp"] == expected_rate_bp
    assert scored["offers_recorded_count"] >= constants.MIN_OFFER_SAMPLE
    assert expected_rate_bp < constants.TAKE_UP_FLOOR_BP
    assert scored["compliance_status"] == "UNDER_REVIEW"
    assert scored["status"] == "ACTIVE"

    sanctioned = validate_success(
        api.insurer_compliance_action(
            insurer["id"],
            factories.compliance_action_payload("SANCTION"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert sanctioned["compliance_status"] == "SANCTIONED"
    assert sanctioned["status"] == "ACTIVE"

    reinstated = validate_success(
        api.insurer_compliance_action(
            insurer["id"],
            factories.compliance_action_payload("REINSTATE"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert reinstated["compliance_status"] == "COMPLIANT"
    assert reinstated["undocumented_decline_count"] == 2

    validate_error(
        api.insurer_compliance_action(
            insurer["id"],
            factories.compliance_action_payload("REINSTATE"),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INSURER_NOT_SANCTIONED,
    )

    withdrawn = validate_success(
        api.insurer_compliance_action(
            insurer["id"],
            factories.compliance_action_payload("WITHDRAW"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["compliance_status"] == "COMPLIANT"

    validate_error(
        api.insurer_compliance_action(
            insurer["id"],
            factories.compliance_action_payload("WITHDRAW"),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INSURER_ALREADY_WITHDRAWN,
    )


def test_11_offer_is_refused_when_the_dwelling_is_absent_or_another_household_s(api):
    """The three-way link is checked before anything is recorded.

    "The same catalogue governs identifiers supplied in a request body: `insurer_id`,
    `policyholder_id`, `dwelling_id`, `policy_id`, `accepted_offer_id`,
    `grant_cycle_id`, `grant_id`, `contractor_id`, `project_id` and `event_id` must
    each resolve to an existing row of their kind, and the failure carries that kind's
    not-found code."

    "An offer may not be recorded through an insurer whose `compliance_status` is
    `SANCTIONED`, nor through one whose `status` is `WITHDRAWN`, and the named
    policyholder must be the same party as the dwelling's own `policyholder_id` or the
    request is refused with `ERR_DWELLING_OWNER_MISMATCH`."

    "The recorded offer opens in `PENDING` with `offer_round` set to 1, `offered_at`
    set to the current logical clock and `expires_at` set to sixty days after
    `offered_at`; `responded_at` stays null while the offer is unanswered, and the
    insurer's `offers_recorded_count` rises by one."

    Design: Corner/endpoints/mandatory_offer_links_insurer_policyholder_and_dwelling
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    insurer_headers = make_insurer_headers(insurer["id"])
    owner = fixtures.create_policyholder(api)
    stranger = fixtures.create_policyholder(api)
    dwelling = fixtures.create_dwelling(api, owner["id"])

    validate_error(
        api.create_mandatory_offer(
            factories.create_mandatory_offer_payload(
                insurer["id"], owner["id"], constants.NON_EXISTENT_ID
            ),
            insurer_headers,
        ),
        ApiErrorId.DWELLING_NOT_FOUND,
    )

    validate_error(
        api.create_mandatory_offer(
            factories.create_mandatory_offer_payload(
                insurer["id"], stranger["id"], dwelling["id"]
            ),
            insurer_headers,
        ),
        ApiErrorId.DWELLING_OWNER_MISMATCH,
    )

    unchanged = validate_success(api.get_insurer(insurer["id"], PROGRAM_ADMIN_HEADERS))
    assert unchanged["offers_recorded_count"] == 0

    _rows, meta = validate_paginated(
        api.list_mandatory_offers({"insurer_id": insurer["id"]}, PROGRAM_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_12_recorded_offer_opens_pending_for_sixty_days_and_is_discoverable(api):
    """A recorded offer names all three parties and runs a sixty-day window.

    "Recording an offer requires the payload to name the discharging insurer through
    `insurer_id`, the recipient through `policyholder_id` and the covered structure
    through `dwelling_id`, and it may carry a `campaign_code` attributing the offer to
    a public-education campaign, which defaults to `NONE`."

    "The recorded offer opens in `PENDING` with `offer_round` set to 1, `offered_at`
    set to the current logical clock and `expires_at` set to sixty days after
    `offered_at`; `responded_at` stays null while the offer is unanswered, and the
    insurer's `offers_recorded_count` rises by one."

    "Filter parameters on list endpoints are all optional and are combined
    conjunctively: supplying both `insurer_id` and `status` on the offer list returns
    only that insurer's offers in that status."

    Design: Corner/endpoints/mandatory_offer_links_insurer_policyholder_and_dwelling
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    owner = fixtures.create_policyholder(api)
    dwelling = fixtures.create_dwelling(api, owner["id"])

    offer = validate_success(
        api.create_mandatory_offer(
            factories.create_mandatory_offer_payload(
                insurer["id"],
                owner["id"],
                dwelling["id"],
                campaign_code="SHAKEOUT26",
            ),
            make_insurer_headers(insurer["id"]),
        ),
        expected_status=201,
    )
    assertions.assert_mandatory_offer_shape(offer)
    assert offer["insurer_id"] == insurer["id"]
    assert offer["policyholder_id"] == owner["id"]
    assert offer["dwelling_id"] == dwelling["id"]
    assert offer["campaign_code"] == "SHAKEOUT26"
    assert offer["status"] == "PENDING"
    assert offer["offer_round"] == 1
    assert offer["responded_at"] is None
    assert _instant(offer["offered_at"]) == _instant(constants.CLOCK_EPOCH)
    assert _instant(offer["expires_at"]) == _instant(offer["offered_at"]) + timedelta(
        days=constants.OFFER_VALID_DAYS
    )

    rows, meta = validate_paginated(
        api.list_mandatory_offers(
            {"insurer_id": insurer["id"], "status": "PENDING"}, PROGRAM_ADMIN_HEADERS
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [offer["id"]]

    counted = validate_success(api.get_insurer(insurer["id"], PROGRAM_ADMIN_HEADERS))
    assert counted["offers_recorded_count"] == 1


def test_13_insurer_read_returns_the_counters_its_offer_history_implies(api):
    """Binding, an undocumented decline and a re-extension each move a counter.

    "A freshly enrolled insurer starts with `status` set to `ACTIVE` and
    `compliance_status` set to `COMPLIANT`, and with all five of its running counters
    at zero: `offers_recorded_count`, `undocumented_decline_count`,
    `last_take_up_rate_bp`, `assessment_balance_cents` and `policies_bound_count`."

    "The recorded offer opens in `PENDING` with `offer_round` set to 1, `offered_at`
    set to the current logical clock and `expires_at` set to sixty days after
    `offered_at`; `responded_at` stays null while the offer is unanswered, and the
    insurer's `offers_recorded_count` rises by one."

    "This default is the enforcement hook of the whole compliance regime: **an
    undocumented decline is one where the program has no written record that the
    household actually refused**, and every such decline raises the insurer's
    `undocumented_decline_count` by one. A documented decline raises nothing."

    "On success, `effective_at` is set to the current clock, `expires_at` to three
    hundred and sixty-five days later, `rated_dwelling_limit_cents` is re-snapshotted
    from the dwelling's live limit, and the insurer's `policies_bound_count` rises by
    one."

    "Insurers, meanwhile, carry an annual duty to repeat the offer, and re-extending an
    offer is the mechanism: an offer in `DECLINED` or `ACCEPTED` returns to `PENDING`,
    its `offer_round` rises by one, `offered_at` is reset to the current clock,
    `expires_at` is recomputed as sixty days after that new instant, `responded_at` is
    cleared back to null and `decline_documented` is reset to false."

    "Where the offer being re-extended was a `DECLINED` one whose `decline_documented`
    was false, the insurer's `undocumented_decline_count` is *decremented* by one,
    because the new round supersedes the old refusal."

    Design: Corner/endpoints/insurer_read_returns_derived_counters_from_its_offer_history
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    insurer_headers = make_insurer_headers(insurer["id"])

    fresh = validate_success(api.get_insurer(insurer["id"], PROGRAM_ADMIN_HEADERS))
    assert fresh["offers_recorded_count"] == 0
    assert fresh["undocumented_decline_count"] == 0
    assert fresh["policies_bound_count"] == 0
    assert fresh["last_take_up_rate_bp"] == 0
    assert fresh["assessment_balance_cents"] == 0

    fixtures.setup_bound_policy(
        api, parties=fixtures.setup_parties(api, insurer=insurer)
    )

    silent = fixtures.setup_pending_offer(
        api, parties=fixtures.setup_parties(api, insurer=insurer)
    )
    validate_success(
        api.respond_to_offer(
            silent["offer"]["id"],
            factories.respond_to_offer_payload("DECLINE"),
            make_policyholder_headers(silent["policyholder"]["id"]),
        )
    )

    papered = fixtures.setup_pending_offer(
        api, parties=fixtures.setup_parties(api, insurer=insurer)
    )
    validate_success(
        api.respond_to_offer(
            papered["offer"]["id"],
            factories.respond_to_offer_payload("DECLINE", decline_documented=True),
            make_policyholder_headers(papered["policyholder"]["id"]),
        )
    )

    after_history = validate_success(
        api.get_insurer(insurer["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert after_history["offers_recorded_count"] == 3
    assert after_history["undocumented_decline_count"] == 1
    assert after_history["policies_bound_count"] == 1

    reoffered = validate_success(
        api.reoffer(silent["offer"]["id"], None, insurer_headers)
    )
    assert reoffered["status"] == "PENDING"
    assert reoffered["offer_round"] == 2
    assert reoffered["responded_at"] is None
    assert reoffered["decline_documented"] is False
    assert _instant(reoffered["offered_at"]) == _instant(constants.CLOCK_EPOCH)
    assert _instant(reoffered["expires_at"]) == _instant(
        reoffered["offered_at"]
    ) + timedelta(days=constants.OFFER_VALID_DAYS)

    after_reoffer = validate_success(
        api.get_insurer(insurer["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert after_reoffer["undocumented_decline_count"] == 0
    assert after_reoffer["offers_recorded_count"] == 3
    assert after_reoffer["policies_bound_count"] == 1


def test_14_renewal_is_refused_before_the_window_opens(api):
    """A term cannot roll over on the day it is bound, nor the day before the window.

    "On success, `effective_at` is set to the current clock, `expires_at` to three
    hundred and sixty-five days later, `rated_dwelling_limit_cents` is re-snapshotted
    from the dwelling's live limit, and the insurer's `policies_bound_count` rises by
    one."

    "Renewal is the cycle in the coverage dimension — `ACTIVE → ACTIVE` — and it may be
    exercised only inside the renewal window, which opens forty-five days before
    `expires_at` and closes at `expires_at` itself: the clock must be at or after
    forty-five days before expiry and strictly before expiry, or the request is refused
    with `ERR_RENEWAL_WINDOW_NOT_OPEN`."

    Design: Corner/endpoints/renew_is_permitted_only_inside_the_forty_five_day_window
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api)
    policy = ctx["policy"]
    insurer_headers = make_insurer_headers(ctx["insurer"]["id"])

    assert policy["lifecycle_status"] == "ACTIVE"
    assert policy["term_number"] == 1
    assert _instant(policy["effective_at"]) == _instant(constants.CLOCK_EPOCH)
    assert _instant(policy["expires_at"]) == _instant(
        policy["effective_at"]
    ) + timedelta(days=constants.TERM_DAYS)

    window_opens = _instant(policy["expires_at"]) - timedelta(
        days=constants.RENEWAL_WINDOW_DAYS
    )

    validate_error(
        api.renew_policy(policy["id"], None, insurer_headers),
        ApiErrorId.RENEWAL_WINDOW_NOT_OPEN,
    )

    fixtures.set_clock(api, _clock_string(window_opens - timedelta(days=1)))
    validate_error(
        api.renew_policy(policy["id"], None, insurer_headers),
        ApiErrorId.RENEWAL_WINDOW_NOT_OPEN,
    )

    untouched = validate_success(api.get_policy(policy["id"], PROGRAM_ADMIN_HEADERS))
    assert untouched["term_number"] == 1
    assert untouched["lifecycle_status"] == "ACTIVE"
    assert untouched["rating_variant"] == "QUOTE_TIME"
    assert _instant(untouched["expires_at"]) == _instant(policy["expires_at"])


def test_15_renewal_on_the_day_the_window_opens_rolls_the_term_forward(api):
    """At exactly forty-five days before expiry the term rolls and is re-rated.

    "Renewal is the cycle in the coverage dimension — `ACTIVE → ACTIVE` — and it may be
    exercised only inside the renewal window, which opens forty-five days before
    `expires_at` and closes at `expires_at` itself: the clock must be at or after
    forty-five days before expiry and strictly before expiry, or the request is refused
    with `ERR_RENEWAL_WINDOW_NOT_OPEN`."

    "A renewal does a great deal at once: `term_number` rises by one; the old
    `expires_at` becomes the new `effective_at` and the new `expires_at` is three
    hundred and sixty-five days after that, so terms abut without gap or overlap;
    `rated_dwelling_limit_cents` is re-snapshotted from the dwelling's current limit;
    `base_premium_cents` is recomputed under the `RENEWAL_TIME` variant and
    `rating_variant` is set to `RENEWAL_TIME`; both `mitigation_discount_cents` and
    `prorated_credit_cents` are reset to zero, and `annual_premium_cents` becomes equal
    to the freshly computed `base_premium_cents`."

    "Second, take the county's base rate per thousand dollars of limit, which is 180
    cents for `TIER_1`, 320 cents for `TIER_2` and 520 cents for `TIER_3`."

    "Multiply the base rate per thousand by the exposure units and then by all six
    factors, in that order, keeping exact decimal arithmetic throughout."

    "First, the exposure is expressed in units of one thousand dollars of Coverage A
    limit: divide `dwelling_limit_cents` by one hundred thousand, which is the number of
    cents in one thousand dollars."

    "From that effective posture, the factor is 0.75 when the posture is `VERIFIED`
    *and* the `structure_type` is `WOOD_FRAME_CRIPPLE_WALL` *and* the
    `verified_retrofit_scope` is `CRIPPLE_WALL_BRACING` — the deepest discount in the
    program, reserved for the one retrofit that addresses the one failure mode; 0.90
    when the posture is `VERIFIED` for any other combination of structure and scope;
    0.95 when the effective posture is `SELF_DECLARED`, which can only ever happen under
    the quote variant; and 1.00 when the effective posture is `NONE`."

    "Only after the clamp is the value rounded, half up, exactly once, to whole cents,
    and that integer becomes `base_premium_cents`."

    Design: Corner/endpoints/renew_is_permitted_only_inside_the_forty_five_day_window
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api)
    policy = ctx["policy"]
    dwelling = ctx["dwelling"]
    window_opens = _instant(policy["expires_at"]) - timedelta(
        days=constants.RENEWAL_WINDOW_DAYS
    )

    fixtures.set_clock(api, _clock_string(window_opens))
    renewed = validate_success(
        api.renew_policy(policy["id"], None, make_insurer_headers(ctx["insurer"]["id"]))
    )

    assert renewed["lifecycle_status"] == "ACTIVE"
    assert renewed["term_number"] == policy["term_number"] + 1
    assert _instant(renewed["effective_at"]) == _instant(policy["expires_at"])
    assert _instant(renewed["expires_at"]) == _instant(
        renewed["effective_at"]
    ) + timedelta(days=constants.TERM_DAYS)
    assert renewed["rated_dwelling_limit_cents"] == dwelling["dwelling_limit_cents"]
    assert renewed["rating_variant"] == "RENEWAL_TIME"
    assert renewed["mitigation_discount_cents"] == 0
    assert renewed["prorated_credit_cents"] == 0
    assert renewed["annual_premium_cents"] == renewed["base_premium_cents"]
    assertions.assert_premium_ledger_consistent(renewed)

    # The dwelling was never retrofitted, so the renewal posture is NONE, and it was
    # built after the pre-code cut-off, so the age factor is 1.00. Its limit sits below
    # the high-limit threshold and its deductible is the neutral one.
    assert dwelling["retrofit_status"] == "NONE"
    assert dwelling["year_built"] > constants.PRE_CODE_YEAR
    assert dwelling["dwelling_limit_cents"] < constants.HIGH_LIMIT_THRESHOLD_CENTS
    exposure_units = _dec(dwelling["dwelling_limit_cents"]) / _dec(
        constants.EXPOSURE_UNIT_CENTS
    )
    product = (
        _dec(constants.BASE_RATE_PER_1000[dwelling["county_hazard_tier"]])
        * exposure_units
        * _dec(constants.SOIL_FACTOR[dwelling["soil_class"]])
        * _dec(constants.STRUCTURE_FACTOR[dwelling["structure_type"]])
        * _dec(1.00)
        * _dec(constants.RETROFIT_FACTOR_NONE)
        * _dec(constants.DEDUCTIBLE_FACTOR[renewed["deductible_pct"]])
        * _dec(1.00)
    )
    clamped = min(
        max(product, _dec(constants.MIN_PREMIUM_CENTS)),
        _dec(constants.MAX_PREMIUM_CENTS),
    )
    assert renewed["base_premium_cents"] == _half_up(clamped)
