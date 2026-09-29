"""Policy self-loops, the bounded claim reopening cycle, and the program's
multi-aggregate cascades.

Renewing an in-force earthquake policy never moves the coverage dimension out of
ACTIVE, yet the same request walks the mitigation dimension backwards out of
DISCOUNT_APPLIED, closes the mid-term discount channel and re-derives the premium
through the renewal retrofit factor instead. Reopening a finalized catastrophe
claim is the other non-linear walk: the adjustment dimension may cycle back from
FINAL_ADJUSTED to PROVISIONAL_ADJUSTED twice and no more, and every traversal
must re-post the same settlement figures and leave the event's loss aggregate
exactly where the arithmetic says it belongs. Three further requests fan out
across whole chains of aggregates in one shot: a passing verification visit
carries an inspection through the project, the dwelling, the funding grant, the
cycle ledger and on into the policy's premium; withdrawing a reserved grant
releases that same chain back again; and finalizing a claim adjustment walks the
claim, the event's loss aggregate, the whole reinsurance tower and the event's
own status.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import validate_success, validate_error

from test_helpers import (
    ApiErrorId,
    CLAIM_ADJUSTER_ALT_HEADERS,
    CLAIM_ADJUSTER_HEADERS,
    FIELD_INSPECTOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    assertions,
    constants,
    factories,
    fixtures,
)
from test_helpers.test_users import make_insurer_headers, make_policyholder_headers

# ─── The cripple-wall household ────────────────────────────────────────────────
# TIER_2 base rate 320 per thousand, SOFT soil 1.25, cripple wall 1.30, built
# 1955 so pre-code 1.20, 15 per cent deductible 0.86, limit below the high-limit
# threshold: 320 x 500 x 1.25 x 1.30 x 1.20 x 1.00 x 0.86 x 1.00 = 268320.
CRIPPLE_WALL_DWELLING = {
    "county_hazard_tier": "TIER_2",
    "soil_class": "SOFT",
    "structure_type": "WOOD_FRAME_CRIPPLE_WALL",
    "year_built": 1955,
    "dwelling_limit_cents": 50000000,
}
CRIPPLE_WALL_POLICY = {
    "deductible_pct": 15,
    "contents_sublimit_cents": 15000000,
    "loss_of_use_sublimit_cents": 5000000,
}
CRIPPLE_WALL_QUOTE_PREMIUM_CENTS = 268320
# The same dwelling re-rated once the retrofit is inspection-verified: the
# retrofit factor becomes 0.75 in place of 1.00.
CRIPPLE_WALL_RENEWAL_PREMIUM_CENTS = 201240
# Scope 25 per cent for cripple-wall bracing on a cripple-wall structure, less
# the 5 point grant offset: 268320 x 0.20.
CRIPPLE_WALL_DISCOUNT_CENTS = 53664

# ─── The mobile-home household ─────────────────────────────────────────────────
# TIER_1 base rate 180 per thousand, STIFF soil 1.00, mobile home 1.45, built
# 1985 so 1.00, 10 per cent deductible 1.00: 180 x 200 x 1.45 = 52200.
MOBILE_HOME_DWELLING = {
    "county_hazard_tier": "TIER_1",
    "soil_class": "STIFF",
    "structure_type": "MOBILE_HOME",
    "year_built": 1985,
    "dwelling_limit_cents": 20000000,
}
MOBILE_HOME_POLICY = {
    "deductible_pct": 10,
    "contents_sublimit_cents": 4000000,
    "loss_of_use_sublimit_cents": 2000000,
}
MOBILE_HOME_QUOTE_PREMIUM_CENTS = 52200
# Scope 20 per cent for a bracing system on a mobile home, less the 5 point
# grant offset: 52200 x 0.15.
MOBILE_HOME_DISCOUNT_CENTS = 7830

# ─── Retrofit funding ──────────────────────────────────────────────────────────
BRACE_AND_BOLT_CYCLE = {"program_track": "BRACE_AND_BOLT", "total_pool_cents": 1000000}
MOBILE_HOME_CYCLE = {"program_track": "MOBILE_HOME", "total_pool_cents": 1000000}
# Cripple-wall cap 1,000,000, estimate 400,000, TIER_MID match three quarters.
CRIPPLE_WALL_AWARD_CENTS = 300000
# Mobile-home cap 600,000, estimate 250,000, TIER_LOW match in full.
MOBILE_HOME_AWARD_CENTS = 250000

# ─── The catastrophe side ──────────────────────────────────────────────────────
EVENT_CLOCK = "2026-09-11T00:00:00Z"
EVENT_OCCURRED_AT = "2026-09-10T00:00:00Z"
RETENTION_CENTS = 100000000

# A claim on the cripple-wall household: structural 20,000,000 with cosmetic
# 5,000,000 that only the final pass admits, contents and loss of use at their
# sublimits. Deductible 50,000,000 x 15 / 100 = 7,500,000.
REOPEN_POLICY = {
    "deductible_pct": 15,
    "contents_sublimit_cents": 2500000,
    "loss_of_use_sublimit_cents": 1200000,
}
REOPEN_CLAIM = {
    "structural_damage_cents": 20000000,
    "cosmetic_damage_cents": 5000000,
    "contents_damage_cents": 2500000,
    "loss_of_use_cents": 1200000,
}
# Coverage A 20,000,000 less the deductible, plus both sublimits in full.
REOPEN_PROVISIONAL_PAYABLE_CENTS = 16200000
# Cosmetic allowed at 2,000,000, combined basis 24,500,000 less the deductible
# leaves 17,000,000, plus loss of use 1,200,000.
REOPEN_FINAL_PAYABLE_CENTS = 18200000
# A tower that attaches far above this loss, so retention absorbs all of it.
HIGH_LAYER = {
    "layer_index": 1,
    "attachment_point_cents": 100000000,
    "limit_cents": 50000000,
    "ceded_pct": 0.90,
}

# The two-layer 2026 tower and the large loss that runs through all of it.
TOWER_DWELLING = {
    "county_hazard_tier": "TIER_1",
    "soil_class": "ROCK",
    "structure_type": "WOOD_FRAME_SLAB",
    "year_built": 2000,
    "dwelling_limit_cents": 300000000,
}
TOWER_POLICY = {
    "deductible_pct": 5,
    "contents_sublimit_cents": 1000000,
    "loss_of_use_sublimit_cents": 500000,
}
TOWER_CLAIM = {
    "structural_damage_cents": 250000000,
    "cosmetic_damage_cents": 0,
    "contents_damage_cents": 0,
    "loss_of_use_cents": 0,
}
TOWER_LAYER_ONE = {
    "layer_index": 1,
    "attachment_point_cents": 100000000,
    "limit_cents": 50000000,
    "ceded_pct": 0.90,
}
TOWER_LAYER_TWO = {
    "layer_index": 2,
    "attachment_point_cents": 150000000,
    "limit_cents": 60000000,
    "ceded_pct": 0.75,
}
# 250,000,000 less the 15,000,000 deductible, no cosmetic and no other coverage.
TOWER_SETTLEMENT_CENTS = 235000000


def _instant(value):
    """Read one of the API's ISO 8601 UTC instants to whole seconds."""
    return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")


def _reserved_cripple_wall_grant(api):
    """A bound cripple-wall policy whose 300,000 cent award is reserved."""
    ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides=CRIPPLE_WALL_DWELLING, **CRIPPLE_WALL_POLICY
    )
    return fixtures.setup_reserved_grant(
        api,
        ctx=ctx,
        cycle_overrides=BRACE_AND_BOLT_CYCLE,
        income_tier="TIER_MID",
        project_cost_estimate_cents=400000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )


def _booked_cripple_wall_inspection(api, window_start, window_end):
    """The cripple-wall retrofit taken all the way to a booked verification visit."""
    ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides=CRIPPLE_WALL_DWELLING, **CRIPPLE_WALL_POLICY
    )
    return fixtures.setup_scheduled_inspection(
        api,
        ctx=ctx,
        window_start=window_start,
        window_end=window_end,
        contractor_scopes=["CRIPPLE_WALL_BRACING"],
        cycle_overrides=BRACE_AND_BOLT_CYCLE,
        income_tier="TIER_MID",
        project_cost_estimate_cents=400000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )


def _booked_mobile_home_inspection(api, window_start, window_end):
    """The mobile-home bracing retrofit taken to a booked verification visit."""
    ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides=MOBILE_HOME_DWELLING, **MOBILE_HOME_POLICY
    )
    return fixtures.setup_scheduled_inspection(
        api,
        ctx=ctx,
        window_start=window_start,
        window_end=window_end,
        contractor_scopes=["EARTHQUAKE_BRACING_SYSTEM"],
        cycle_overrides=MOBILE_HOME_CYCLE,
        income_tier="TIER_LOW",
        project_cost_estimate_cents=250000,
        requested_scope="EARTHQUAKE_BRACING_SYSTEM",
    )


def _provisionally_adjusted_cripple_wall_claim(api):
    """A provisionally adjusted claim on an event whose tower never responds."""
    ctx = fixtures.setup_event_with_policy(
        api,
        clock=EVENT_CLOCK,
        dwelling_overrides=CRIPPLE_WALL_DWELLING,
        policy_overrides=REOPEN_POLICY,
        event_overrides={
            "magnitude": 6.4,
            "occurred_at": EVENT_OCCURRED_AT,
            "retention_cents": RETENTION_CENTS,
        },
        layer_overrides=HIGH_LAYER,
    )
    return fixtures.setup_provisionally_adjusted_claim(api, ctx=ctx, **REOPEN_CLAIM)


def _provisionally_adjusted_tower_claim(api):
    """A provisionally adjusted 235,000,000 cent loss under a two-layer tower."""
    ctx = fixtures.setup_event_with_policy(
        api,
        clock=EVENT_CLOCK,
        dwelling_overrides=TOWER_DWELLING,
        policy_overrides=TOWER_POLICY,
        event_overrides={
            "magnitude": 7.1,
            "occurred_at": EVENT_OCCURRED_AT,
            "retention_cents": RETENTION_CENTS,
        },
        layer_overrides=TOWER_LAYER_ONE,
    )
    ctx["layer_two"] = fixtures.create_reinsurance_layer(api, **TOWER_LAYER_TWO)
    return fixtures.setup_provisionally_adjusted_claim(api, ctx=ctx, **TOWER_CLAIM)


def test_01_renewing_swaps_the_mid_term_discount_for_the_renewal_retrofit_factor(api):
    """A renewal re-derives the premium through the retrofit factor and closes the
    mid-term discount channel, without the coverage dimension moving at all.

    PRD: "A renewal does a great deal at once: `term_number` rises by one; the old `expires_at` becomes the new `effective_at` and the new `expires_at` is three hundred and sixty-five days after that, so terms abut without gap or overlap; `rated_dwelling_limit_cents` is re-snapshotted from the dwelling's current limit; `base_premium_cents` is recomputed under the `RENEWAL_TIME` variant and `rating_variant` is set to `RENEWAL_TIME`; both `mitigation_discount_cents` and `prorated_credit_cents` are reset to zero, and `annual_premium_cents` becomes equal to the freshly computed `base_premium_cents`."
    PRD: "If `mitigation_status` was `DISCOUNT_APPLIED`, it steps back to `RETROFIT_VERIFIED` as part of the same renewal."
    PRD: "Both variants begin from the dwelling's stored `retrofit_status`, but the renewal variant first downgrades a `SELF_DECLARED` posture to `NONE`, so that only an inspection-verified retrofit survives into a renewal rating; the quote variant takes `retrofit_status` exactly as stored."

    Design: Difficulty/non_linear_state_machine/policy_active_self_loop_swaps_discount_channel_without_leaving_active
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _booked_cripple_wall_inspection(
        api, "2026-10-01T00:00:00Z", "2026-10-01T02:00:00Z"
    )
    assert ctx["policy"]["base_premium_cents"] == CRIPPLE_WALL_QUOTE_PREMIUM_CENTS
    assert ctx["grant"]["approved_amount_cents"] == CRIPPLE_WALL_AWARD_CENTS

    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    ctx = fixtures.record_inspection(api, ctx, "PASS")
    mid_term = ctx["policy"]
    assert mid_term["lifecycle_status"] == "ACTIVE"
    assert mid_term["mitigation_status"] == "DISCOUNT_APPLIED"
    assert mid_term["mitigation_discount_cents"] == CRIPPLE_WALL_DISCOUNT_CENTS
    assert (
        mid_term["annual_premium_cents"]
        == CRIPPLE_WALL_QUOTE_PREMIUM_CENTS - CRIPPLE_WALL_DISCOUNT_CENTS
    )
    # 304 whole days remain of a term expiring 2027-08-01: 53664 x 304 / 365.
    assert mid_term["prorated_credit_cents"] == 44695

    # Inside the 45-day renewal window ahead of the 2027-08-01 expiry.
    fixtures.set_clock(api, "2027-07-01T00:00:00Z")
    renewed = validate_success(
        api.renew_policy(
            ctx["policy"]["id"], None, make_insurer_headers(ctx["insurer"]["id"])
        )
    )

    assert renewed["lifecycle_status"] == "ACTIVE"
    assert renewed["mitigation_status"] == "RETROFIT_VERIFIED"
    assert renewed["rating_variant"] == "RENEWAL_TIME"
    assert renewed["base_premium_cents"] == CRIPPLE_WALL_RENEWAL_PREMIUM_CENTS
    assert renewed["mitigation_discount_cents"] == 0
    assert renewed["prorated_credit_cents"] == 0
    assert renewed["annual_premium_cents"] == CRIPPLE_WALL_RENEWAL_PREMIUM_CENTS
    assert renewed["annual_premium_cents"] < mid_term["annual_premium_cents"]
    assertions.assert_premium_ledger_consistent(renewed)


def test_02_renewing_abuts_the_next_term_while_the_coverage_dimension_stays_active(api):
    """The renewal self-loop hands the old expiry to the new term and re-snapshots
    the rated limit, while lifecycle_status never leaves ACTIVE.

    PRD: "Renewal is the cycle in the coverage dimension — `ACTIVE → ACTIVE` — and it may be exercised only inside the renewal window, which opens forty-five days before `expires_at` and closes at `expires_at` itself: the clock must be at or after forty-five days before expiry and strictly before expiry, or the request is refused with `ERR_RENEWAL_WINDOW_NOT_OPEN`."
    PRD: "A renewal does a great deal at once: `term_number` rises by one; the old `expires_at` becomes the new `effective_at` and the new `expires_at` is three hundred and sixty-five days after that, so terms abut without gap or overlap; `rated_dwelling_limit_cents` is re-snapshotted from the dwelling's current limit; `base_premium_cents` is recomputed under the `RENEWAL_TIME` variant and `rating_variant` is set to `RENEWAL_TIME`; both `mitigation_discount_cents` and `prorated_credit_cents` are reset to zero, and `annual_premium_cents` becomes equal to the freshly computed `base_premium_cents`."
    PRD: "If `mitigation_status` was `DISCOUNT_APPLIED`, it steps back to `RETROFIT_VERIFIED` as part of the same renewal."

    Design: Difficulty/non_linear_state_machine/policy_active_self_loop_swaps_discount_channel_without_leaving_active
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _booked_cripple_wall_inspection(
        api, "2026-10-01T00:00:00Z", "2026-10-01T02:00:00Z"
    )
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    ctx = fixtures.record_inspection(api, ctx, "PASS")
    first_term = ctx["policy"]
    assert first_term["term_number"] == 1
    assert first_term["mitigation_status"] == "DISCOUNT_APPLIED"

    fixtures.set_clock(api, "2027-07-01T00:00:00Z")
    renewed = validate_success(
        api.renew_policy(
            first_term["id"], None, make_insurer_headers(ctx["insurer"]["id"])
        )
    )

    assert renewed["lifecycle_status"] == first_term["lifecycle_status"] == "ACTIVE"
    assert renewed["term_number"] == 2
    assert renewed["effective_at"] == first_term["expires_at"]
    assert _instant(renewed["expires_at"]) - _instant(renewed["effective_at"]) == timedelta(
        days=constants.TERM_DAYS
    )
    assert (
        renewed["rated_dwelling_limit_cents"]
        == CRIPPLE_WALL_DWELLING["dwelling_limit_cents"]
    )
    assert renewed["version"] > first_term["version"]
    assert renewed["mitigation_status"] == "RETROFIT_VERIFIED"


def test_03_a_renewed_policy_no_longer_carries_a_revocable_mitigation_discount(api):
    """Because the self-loop zeroes the discount and steps the mitigation dimension
    back, the mid-term revocation channel has nothing left to withdraw.

    PRD: "If `mitigation_status` was `DISCOUNT_APPLIED`, it steps back to `RETROFIT_VERIFIED` as part of the same renewal."
    PRD: "The policy must be `ACTIVE`, its `mitigation_status` must currently be `DISCOUNT_APPLIED` and its `mitigation_discount_cents` must be strictly greater than zero, or the request is refused with `ERR_NO_MITIGATION_DISCOUNT`."

    Design: Difficulty/non_linear_state_machine/policy_active_self_loop_swaps_discount_channel_without_leaving_active
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _booked_cripple_wall_inspection(
        api, "2026-10-01T00:00:00Z", "2026-10-01T02:00:00Z"
    )
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    ctx = fixtures.record_inspection(api, ctx, "PASS")
    policy_id = ctx["policy"]["id"]
    assert ctx["policy"]["mitigation_status"] == "DISCOUNT_APPLIED"

    fixtures.set_clock(api, "2027-07-01T00:00:00Z")
    renewed = validate_success(
        api.renew_policy(policy_id, None, make_insurer_headers(ctx["insurer"]["id"]))
    )
    assert renewed["lifecycle_status"] == "ACTIVE"
    assert renewed["mitigation_discount_cents"] == 0

    refused = api.revoke_mitigation_discount(
        policy_id, factories.reason_payload("retrofit later found deficient"), PROGRAM_ADMIN_HEADERS
    )
    validate_error(refused, ApiErrorId.NO_MITIGATION_DISCOUNT)

    unchanged = validate_success(api.get_policy(policy_id, PROGRAM_ADMIN_HEADERS))
    assert unchanged["mitigation_status"] == "RETROFIT_VERIFIED"
    assert unchanged["annual_premium_cents"] == CRIPPLE_WALL_RENEWAL_PREMIUM_CENTS


def test_04_a_finalized_claim_traverses_the_reopening_cycle_twice_without_drift(api):
    """Each traversal of FINAL_ADJUSTED -> PROVISIONAL_ADJUSTED -> FINAL_ADJUSTED
    re-posts the same two settlement figures and returns the event's aggregate to
    exactly where it started.

    PRD: "It requires `reopen_count` to be strictly less than two — a claim may be reopened twice and no more — the event to be neither `ASSESSMENT_LEVIED` nor `CLOSED`, since the published allocations may not be disturbed, and the claim's `payment_status` to be `UNPAID` or `PARTIALLY_PAID`, because a fully settled claim is refused outright with `ERR_CLAIM_ALREADY_SETTLED`."
    PRD: "First, the event's `aggregate_incurred_cents` falls by exactly the claim's `final_payable_cents` and the event's `version` rises."
    PRD: "On the claim itself, `final_payable_cents` returns to zero, `payable_cents` returns to `provisional_payable_cents`, `final_adjuster_user_id` is cleared to null, and `reopen_count` rises by one."

    Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_permitted_exactly_twice_then_refused
    """
    ctx = _provisionally_adjusted_cripple_wall_claim(api)
    claim_id = ctx["claim"]["id"]
    event_id = ctx["event"]["id"]
    assert ctx["claim"]["provisional_payable_cents"] == REOPEN_PROVISIONAL_PAYABLE_CENTS
    assert ctx["claim"]["payable_cents"] == REOPEN_PROVISIONAL_PAYABLE_CENTS

    for reopens_so_far in (0, 1):
        finalized = validate_success(
            api.finalize_claim_adjustment(claim_id, None, CLAIM_ADJUSTER_ALT_HEADERS)
        )
        assert finalized["adjustment_status"] == "FINAL_ADJUSTED"
        assert finalized["final_payable_cents"] == REOPEN_FINAL_PAYABLE_CENTS
        assert finalized["payable_cents"] == REOPEN_FINAL_PAYABLE_CENTS
        assert finalized["reopen_count"] == reopens_so_far

        reopened = validate_success(
            api.reopen_claim(
                claim_id,
                factories.reason_payload("supplemental engineer report"),
                CLAIM_ADJUSTER_HEADERS,
            )
        )
        assert reopened["adjustment_status"] == "PROVISIONAL_ADJUSTED"
        assert reopened["payable_cents"] == REOPEN_PROVISIONAL_PAYABLE_CENTS
        assert reopened["final_payable_cents"] == 0
        assert reopened["reopen_count"] == reopens_so_far + 1

        unwound = validate_success(api.get_catastrophe_event(event_id, PROGRAM_ADMIN_HEADERS))
        assert unwound["aggregate_incurred_cents"] == 0
        assert unwound["uncovered_cents"] == 0
        assert unwound["status"] == "LOSS_AGGREGATION"

    settled = validate_success(
        api.finalize_claim_adjustment(claim_id, None, CLAIM_ADJUSTER_ALT_HEADERS)
    )
    assert settled["adjustment_status"] == "FINAL_ADJUSTED"
    assert settled["payable_cents"] == REOPEN_FINAL_PAYABLE_CENTS
    assert settled["reopen_count"] == 2

    event = validate_success(api.get_catastrophe_event(event_id, PROGRAM_ADMIN_HEADERS))
    assert event["aggregate_incurred_cents"] == REOPEN_FINAL_PAYABLE_CENTS
    assert event["status"] == "LOSS_AGGREGATION"
    assertions.assert_event_loss_conserved(event)


def test_05_a_third_reopening_of_the_same_claim_is_refused(api):
    """The cycle is bounded: two reopenings are legal and the third is rejected with
    the claim and the event's aggregate left untouched.

    PRD: "Rung 33: a claim's `reopen_count` must be strictly less than two to reopen it, otherwise `ERR_CLAIM_REOPEN_LIMIT` (409)."
    PRD: "It requires `reopen_count` to be strictly less than two — a claim may be reopened twice and no more — the event to be neither `ASSESSMENT_LEVIED` nor `CLOSED`, since the published allocations may not be disturbed, and the claim's `payment_status` to be `UNPAID` or `PARTIALLY_PAID`, because a fully settled claim is refused outright with `ERR_CLAIM_ALREADY_SETTLED`."

    Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_permitted_exactly_twice_then_refused
    """
    ctx = _provisionally_adjusted_cripple_wall_claim(api)
    claim_id = ctx["claim"]["id"]
    event_id = ctx["event"]["id"]

    for _ in range(2):
        validate_success(
            api.finalize_claim_adjustment(claim_id, None, CLAIM_ADJUSTER_ALT_HEADERS)
        )
        validate_success(
            api.reopen_claim(
                claim_id, factories.reason_payload("supplemental"), CLAIM_ADJUSTER_HEADERS
            )
        )
    exhausted = validate_success(
        api.finalize_claim_adjustment(claim_id, None, CLAIM_ADJUSTER_ALT_HEADERS)
    )
    assert exhausted["reopen_count"] == constants.MAX_REOPENS

    refused = api.reopen_claim(
        claim_id, factories.reason_payload("third supplemental"), CLAIM_ADJUSTER_HEADERS
    )
    validate_error(refused, ApiErrorId.CLAIM_REOPEN_LIMIT)

    claim = validate_success(api.get_claim(claim_id, PROGRAM_ADMIN_HEADERS))
    assert claim["adjustment_status"] == "FINAL_ADJUSTED"
    assert claim["reopen_count"] == constants.MAX_REOPENS
    assert claim["payable_cents"] == REOPEN_FINAL_PAYABLE_CENTS
    assert claim["final_payable_cents"] == REOPEN_FINAL_PAYABLE_CENTS

    event = validate_success(api.get_catastrophe_event(event_id, PROGRAM_ADMIN_HEADERS))
    assert event["aggregate_incurred_cents"] == REOPEN_FINAL_PAYABLE_CENTS
    assert event["status"] == "LOSS_AGGREGATION"


def test_06_reopening_restores_the_provisional_payable_and_keeps_every_cent_paid(api):
    """Walking the adjustment dimension backwards clears the final figures and the
    final adjuster's identity, but the payment dimension is untouched.

    PRD: "On the claim itself, `final_payable_cents` returns to zero, `payable_cents` returns to `provisional_payable_cents`, `final_adjuster_user_id` is cleared to null, and `reopen_count` rises by one."
    PRD: "Neither `payment_status` nor `paid_cents` is touched: a partially paid claim keeps every cent it has been paid."

    Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_permitted_exactly_twice_then_refused
    """
    ctx = _provisionally_adjusted_cripple_wall_claim(api)
    claim_id = ctx["claim"]["id"]

    finalized = validate_success(
        api.finalize_claim_adjustment(claim_id, None, CLAIM_ADJUSTER_ALT_HEADERS)
    )
    assert finalized["payable_cents"] == REOPEN_FINAL_PAYABLE_CENTS
    assert finalized["final_adjuster_user_id"] is not None

    part_paid = validate_success(
        api.record_claim_payment(
            claim_id, factories.record_payment_payload(1000000), PROGRAM_ADMIN_HEADERS
        )
    )
    assert part_paid["paid_cents"] == 1000000
    assert part_paid["payment_status"] == "PARTIALLY_PAID"

    reopened = validate_success(
        api.reopen_claim(
            claim_id, factories.reason_payload("supplemental"), CLAIM_ADJUSTER_HEADERS
        )
    )
    assert reopened["adjustment_status"] == "PROVISIONAL_ADJUSTED"
    assert reopened["final_payable_cents"] == 0
    assert reopened["payable_cents"] == REOPEN_PROVISIONAL_PAYABLE_CENTS
    assert reopened["final_adjuster_user_id"] is None
    assert reopened["reopen_count"] == 1
    assert reopened["paid_cents"] == 1000000
    assert reopened["payment_status"] == "PARTIALLY_PAID"


def test_07_a_passing_visit_verifies_the_project_and_the_dwelling_retrofit(api):
    """The first two hops of the verification cascade: the visit passes, the project
    reaches VERIFIED, and the dwelling records the inspected scope.

    PRD: "Hop one, on the inspection and the project: `result` becomes `PASS`, and the project advances `AWAITING_INSPECTION → VERIFIED` with `verified_at` stamped from the clock."
    PRD: "Hop two, caused by the project reaching `VERIFIED`: the dwelling's `retrofit_status` becomes `VERIFIED` and its `verified_retrofit_scope` is overwritten with the project's `scope_code`, and the funding grant advances `FUNDS_RESERVED → VERIFIED_COMPLETE`."
    PRD: "Every recorded outcome writes `inspector_user_id` from the acting header and `recorded_at` from the clock, and raises the project's `inspection_attempts` by one."
    PRD: "First, each row the cascade touches has its own `updated_at` refreshed and its own `version` incremented — a request that moves a project, a dwelling, a grant, a funding cycle and a policy increments five `version` counters, not one."

    Design: Difficulty/transitive_cascade/inspection_pass_cascades_four_hops_from_inspection_to_policy_premium
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _booked_mobile_home_inspection(
        api, "2026-11-01T00:00:00Z", "2026-11-01T02:00:00Z"
    )
    project_before = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    dwelling_before = validate_success(
        api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert project_before["status"] == "AWAITING_INSPECTION"
    assert project_before["scope_code"] == "EARTHQUAKE_BRACING_SYSTEM"
    assert dwelling_before["retrofit_status"] == "NONE"

    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    inspection = validate_success(
        api.record_inspection_result(
            ctx["inspection"]["id"],
            factories.record_result_payload("PASS"),
            FIELD_INSPECTOR_HEADERS,
        )
    )
    assert inspection["result"] == "PASS"
    assert inspection["inspector_user_id"] == FIELD_INSPECTOR_HEADERS["X-User-ID"]
    assert inspection["recorded_at"] is not None

    project = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert project["status"] == "VERIFIED"
    assert project["verified_at"] is not None
    assert project["inspection_attempts"] == 1
    assert project["version"] > project_before["version"]

    dwelling = validate_success(
        api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert dwelling["retrofit_status"] == "VERIFIED"
    assert dwelling["verified_retrofit_scope"] == "EARTHQUAKE_BRACING_SYSTEM"
    assert dwelling["grant_lifetime_count"] == 1
    assert dwelling["version"] > dwelling_before["version"]


def test_08_a_passing_visit_transfers_the_award_from_reserved_to_disbursed(api):
    """The third hop: the grant completes and the funding cycle moves the award
    across its ledger rather than releasing it.

    PRD: "Hop two, caused by the project reaching `VERIFIED`: the dwelling's `retrofit_status` becomes `VERIFIED` and its `verified_retrofit_scope` is overwritten with the project's `scope_code`, and the funding grant advances `FUNDS_RESERVED → VERIFIED_COMPLETE`."
    PRD: "Hop three, caused by the grant reaching `VERIFIED_COMPLETE`: the funding cycle transfers the award from reserved to disbursed, lowering `reserved_cents` and raising `disbursed_cents` by the award while `uncommitted_cents` stays where it was, and the cycle's `version` rises."

    Design: Difficulty/transitive_cascade/inspection_pass_cascades_four_hops_from_inspection_to_policy_premium
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _booked_mobile_home_inspection(
        api, "2026-11-01T00:00:00Z", "2026-11-01T02:00:00Z"
    )
    cycle_before = validate_success(
        api.get_grant_cycle(ctx["cycle"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert ctx["grant"]["approved_amount_cents"] == MOBILE_HOME_AWARD_CENTS
    assert ctx["grant"]["funded_from_bucket"] == "TIER_LOW"
    assert cycle_before["reserved_cents"] == MOBILE_HOME_AWARD_CENTS
    assert cycle_before["disbursed_cents"] == 0
    assert cycle_before["uncommitted_cents"] == 750000

    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    validate_success(
        api.record_inspection_result(
            ctx["inspection"]["id"],
            factories.record_result_payload("PASS"),
            FIELD_INSPECTOR_HEADERS,
        )
    )

    grant = validate_success(
        api.get_retrofit_grant(ctx["grant"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert grant["status"] == "VERIFIED_COMPLETE"
    assert grant["approved_amount_cents"] == MOBILE_HOME_AWARD_CENTS

    cycle = validate_success(api.get_grant_cycle(ctx["cycle"]["id"], PROGRAM_ADMIN_HEADERS))
    assert cycle["reserved_cents"] == 0
    assert cycle["disbursed_cents"] == MOBILE_HOME_AWARD_CENTS
    assert cycle["uncommitted_cents"] == cycle_before["uncommitted_cents"]
    assert cycle["version"] > cycle_before["version"]
    assertions.assert_grant_pool_conserved(cycle)


def test_09_a_passing_visit_applies_the_mitigation_discount_to_the_in_force_policy(api):
    """The fourth hop runs the money calculation: the bracing scope earns twenty per
    cent less the five point grant offset, and the unearned portion is credited back.

    PRD: "Hop three-b, caused by the dwelling's `retrofit_status` reaching `VERIFIED`: the policy's `mitigation_status` advances `RETROFIT_PENDING → RETROFIT_VERIFIED`."
    PRD: "Hop four, caused by the policy reaching `RETROFIT_VERIFIED` and firing **only** when that policy's `lifecycle_status` is `ACTIVE`: the mitigation discount is computed and applied, and `mitigation_status` advances `RETROFIT_VERIFIED → DISCOUNT_APPLIED`."
    PRD: "Then subtract the grant offset: because public money has already paid for part of the work, a grant whose `approved_amount_cents` is strictly greater than zero costs the household five percentage points of discount, while a verified retrofit with no award behind it loses nothing."
    PRD: "`mitigation_discount_cents` is `base_premium_cents` multiplied by the effective percentage, rounded half up to whole cents, and `annual_premium_cents` becomes `base_premium_cents` less that discount."
    PRD: "`prorated_credit_cents` is the already-rounded `mitigation_discount_cents` multiplied by the smaller of that day count and three hundred and sixty-five, divided by three hundred and sixty-five, rounded half up to whole cents."

    Design: Difficulty/transitive_cascade/inspection_pass_cascades_four_hops_from_inspection_to_policy_premium
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _booked_mobile_home_inspection(
        api, "2026-11-01T00:00:00Z", "2026-11-01T02:00:00Z"
    )
    policy_before = validate_success(api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS))
    assert policy_before["lifecycle_status"] == "ACTIVE"
    assert policy_before["mitigation_status"] == "RETROFIT_PENDING"
    assert policy_before["base_premium_cents"] == MOBILE_HOME_QUOTE_PREMIUM_CENTS
    assert policy_before["mitigation_discount_cents"] == 0

    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    validate_success(
        api.record_inspection_result(
            ctx["inspection"]["id"],
            factories.record_result_payload("PASS"),
            FIELD_INSPECTOR_HEADERS,
        )
    )

    policy = validate_success(api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS))
    assert policy["mitigation_status"] == "DISCOUNT_APPLIED"
    assert policy["base_premium_cents"] == MOBILE_HOME_QUOTE_PREMIUM_CENTS
    assert policy["mitigation_discount_cents"] == MOBILE_HOME_DISCOUNT_CENTS
    assert (
        policy["annual_premium_cents"]
        == MOBILE_HOME_QUOTE_PREMIUM_CENTS - MOBILE_HOME_DISCOUNT_CENTS
    )
    # 273 whole days remain of a term expiring 2027-08-01: 7830 x 273 / 365.
    assert policy["prorated_credit_cents"] == 5856
    assert policy["version"] > policy_before["version"]
    assertions.assert_premium_ledger_consistent(policy)


def test_10_a_passing_visit_on_a_cancelled_policy_stops_at_retrofit_verified(api):
    """The fourth hop is conditional on cover being in force: a cancelled policy
    keeps the physical verification and receives no discount, while the hops that
    did fire stand.

    PRD: "Hop four, caused by the policy reaching `RETROFIT_VERIFIED` and firing **only** when that policy's `lifecycle_status` is `ACTIVE`: the mitigation discount is computed and applied, and `mitigation_status` advances `RETROFIT_VERIFIED → DISCOUNT_APPLIED`."
    PRD: "A policy that has lapsed or been cancelled stops at `RETROFIT_VERIFIED` and receives no discount — the physical verification stands even though the pricing incentive has nowhere to land."
    PRD: "Second, cascades are conditional at each hop rather than unconditional: a hop whose own precondition does not hold simply does not fire, and the hops after it that depended on it do not fire either, while the hops that did fire stand."

    Design: Difficulty/transitive_cascade/inspection_pass_cascades_four_hops_from_inspection_to_policy_premium
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _booked_mobile_home_inspection(
        api, "2026-11-01T00:00:00Z", "2026-11-01T02:00:00Z"
    )
    cancelled = validate_success(
        api.cancel_policy(
            ctx["policy"]["id"],
            factories.reason_payload("household moved away"),
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
    )
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["mitigation_status"] == "RETROFIT_PENDING"

    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    validate_success(
        api.record_inspection_result(
            ctx["inspection"]["id"],
            factories.record_result_payload("PASS"),
            FIELD_INSPECTOR_HEADERS,
        )
    )

    project = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    dwelling = validate_success(api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS))
    grant = validate_success(api.get_retrofit_grant(ctx["grant"]["id"], PROGRAM_ADMIN_HEADERS))
    assert project["status"] == "VERIFIED"
    assert dwelling["retrofit_status"] == "VERIFIED"
    assert grant["status"] == "VERIFIED_COMPLETE"

    policy = validate_success(api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS))
    assert policy["lifecycle_status"] == "CANCELLED"
    assert policy["mitigation_status"] == "RETROFIT_VERIFIED"
    assert policy["mitigation_discount_cents"] == 0
    assert policy["prorated_credit_cents"] == 0
    assert policy["annual_premium_cents"] == MOBILE_HOME_QUOTE_PREMIUM_CENTS


def test_11_withdrawing_a_reserved_grant_releases_the_award_back_to_the_pool(api):
    """The first hop of the compensating cascade: the cycle ledger gives the award
    back and the bucket that funded it is released.

    PRD: "Withdrawing from `FUNDS_RESERVED` reverses the reservation exactly: `reserved_cents` falls by the award, `uncommitted_cents` is recomputed, the cycle's `version` rises by one, `funded_from_bucket` is set back to `NONE` — which is what releases the bucket usage for the next applicant — every retrofit project on the grant that is in `SCHEDULED`, `IN_PROGRESS`, `AWAITING_INSPECTION` or `REWORK_REQUIRED` is moved to the terminal `ABANDONED`, and the policy's `mitigation_status` steps back `RETROFIT_PENDING → UNMITIGATED`."

    Design: Difficulty/transitive_cascade/grant_withdraw_releases_commitment_across_three_hops
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _reserved_cripple_wall_grant(api)
    cycle_before = validate_success(
        api.get_grant_cycle(ctx["cycle"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert ctx["grant"]["status"] == "FUNDS_RESERVED"
    assert ctx["grant"]["approved_amount_cents"] == CRIPPLE_WALL_AWARD_CENTS
    assert ctx["grant"]["funded_from_bucket"] == "TIER_MID"
    assert cycle_before["reserved_cents"] == CRIPPLE_WALL_AWARD_CENTS
    assert cycle_before["uncommitted_cents"] == 1000000 - CRIPPLE_WALL_AWARD_CENTS

    grant = validate_success(
        api.withdraw_grant(
            ctx["grant"]["id"],
            factories.reason_payload("household withdrew from the programme"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert grant["status"] == "WITHDRAWN"
    assert grant["funded_from_bucket"] == "NONE"
    assert grant["approved_amount_cents"] == CRIPPLE_WALL_AWARD_CENTS

    cycle = validate_success(api.get_grant_cycle(ctx["cycle"]["id"], PROGRAM_ADMIN_HEADERS))
    assert cycle["reserved_cents"] == 0
    assert cycle["disbursed_cents"] == 0
    assert cycle["uncommitted_cents"] == 1000000
    assert cycle["version"] == cycle_before["version"] + 1
    assertions.assert_grant_pool_conserved(cycle)


def test_12_withdrawing_a_reserved_grant_abandons_the_live_retrofit_project(api):
    """The hop into the delivery side: work already under way on the withdrawn
    grant is terminated.

    PRD: "Withdrawing from `FUNDS_RESERVED` reverses the reservation exactly: `reserved_cents` falls by the award, `uncommitted_cents` is recomputed, the cycle's `version` rises by one, `funded_from_bucket` is set back to `NONE` — which is what releases the bucket usage for the next applicant — every retrofit project on the grant that is in `SCHEDULED`, `IN_PROGRESS`, `AWAITING_INSPECTION` or `REWORK_REQUIRED` is moved to the terminal `ABANDONED`, and the policy's `mitigation_status` steps back `RETROFIT_PENDING → UNMITIGATED`."
    PRD: "First, each row the cascade touches has its own `updated_at` refreshed and its own `version` incremented — a request that moves a project, a dwelling, a grant, a funding cycle and a policy increments five `version` counters, not one."

    Design: Difficulty/transitive_cascade/grant_withdraw_releases_commitment_across_three_hops
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides=CRIPPLE_WALL_DWELLING, **CRIPPLE_WALL_POLICY
    )
    ctx = fixtures.setup_project_in_progress(
        api,
        ctx=ctx,
        contractor_scopes=["CRIPPLE_WALL_BRACING"],
        cycle_overrides=BRACE_AND_BOLT_CYCLE,
        income_tier="TIER_MID",
        project_cost_estimate_cents=400000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )
    project_before = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert project_before["status"] == "IN_PROGRESS"

    validate_success(
        api.withdraw_grant(
            ctx["grant"]["id"],
            factories.reason_payload("funding released"),
            PROGRAM_ADMIN_HEADERS,
        )
    )

    project = validate_success(
        api.get_retrofit_project(ctx["project"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert project["status"] == "ABANDONED"
    assert project["version"] > project_before["version"]


def test_13_withdrawing_a_reserved_grant_returns_the_policy_to_unmitigated(api):
    """The hop into the coverage side, and the historical tally that is deliberately
    left alone.

    PRD: "Withdrawing from `FUNDS_RESERVED` reverses the reservation exactly: `reserved_cents` falls by the award, `uncommitted_cents` is recomputed, the cycle's `version` rises by one, `funded_from_bucket` is set back to `NONE` — which is what releases the bucket usage for the next applicant — every retrofit project on the grant that is in `SCHEDULED`, `IN_PROGRESS`, `AWAITING_INSPECTION` or `REWORK_REQUIRED` is moved to the terminal `ABANDONED`, and the policy's `mitigation_status` steps back `RETROFIT_PENDING → UNMITIGATED`."
    PRD: "It rises by one at the moment cycle money is actually committed to an award for the dwelling, not when an application is filed, and it is never decremented — a withdrawn reservation releases the money but not the historical fact that the dwelling drew on the pool."

    Design: Difficulty/transitive_cascade/grant_withdraw_releases_commitment_across_three_hops
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = _reserved_cripple_wall_grant(api)
    policy_before = validate_success(api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS))
    dwelling_before = validate_success(
        api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert policy_before["mitigation_status"] == "RETROFIT_PENDING"
    assert dwelling_before["grant_lifetime_count"] == 1

    validate_success(
        api.withdraw_grant(
            ctx["grant"]["id"],
            factories.reason_payload("household withdrew from the programme"),
            make_policyholder_headers(ctx["policyholder"]["id"]),
        )
    )

    policy = validate_success(api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS))
    assert policy["lifecycle_status"] == "ACTIVE"
    assert policy["mitigation_status"] == "UNMITIGATED"
    assert policy["mitigation_discount_cents"] == 0
    assert policy["prorated_credit_cents"] == 0
    assert policy["annual_premium_cents"] == CRIPPLE_WALL_QUOTE_PREMIUM_CENTS
    assert policy["version"] > policy_before["version"]
    assertions.assert_premium_ledger_consistent(policy)

    dwelling = validate_success(api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS))
    assert dwelling["grant_lifetime_count"] == 1
    assert dwelling["retrofit_status"] == "NONE"


def test_14_withdrawing_an_approved_grant_touches_no_ledger_at_all(api):
    """Before money is committed there is nothing to release, so none of the hops
    fire: the cycle, the policy and the dwelling stand untouched.

    PRD: "Withdrawing from any of the four pre-reservation statuses touches no ledger at all, because nothing was reserved."
    PRD: "Second, cascades are conditional at each hop rather than unconditional: a hop whose own precondition does not hold simply does not fire, and the hops after it that depended on it do not fire either, while the hops that did fire stand."

    Design: Difficulty/transitive_cascade/grant_withdraw_releases_commitment_across_three_hops
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(
        api, dwelling_overrides=CRIPPLE_WALL_DWELLING, **CRIPPLE_WALL_POLICY
    )
    ctx = fixtures.setup_approved_grant(
        api,
        ctx=ctx,
        cycle_overrides=BRACE_AND_BOLT_CYCLE,
        income_tier="TIER_MID",
        project_cost_estimate_cents=400000,
        requested_scope="CRIPPLE_WALL_BRACING",
    )
    cycle_before = validate_success(
        api.get_grant_cycle(ctx["cycle"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert ctx["grant"]["status"] == "APPROVED"
    assert cycle_before["reserved_cents"] == 0
    assert cycle_before["uncommitted_cents"] == 1000000

    grant = validate_success(
        api.withdraw_grant(
            ctx["grant"]["id"],
            factories.reason_payload("household withdrew before reservation"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert grant["status"] == "WITHDRAWN"

    cycle = validate_success(api.get_grant_cycle(ctx["cycle"]["id"], PROGRAM_ADMIN_HEADERS))
    assert cycle["reserved_cents"] == 0
    assert cycle["disbursed_cents"] == 0
    assert cycle["uncommitted_cents"] == 1000000
    assert cycle["version"] == cycle_before["version"]

    policy = validate_success(api.get_policy(ctx["policy"]["id"], PROGRAM_ADMIN_HEADERS))
    assert policy["mitigation_status"] == "UNMITIGATED"
    dwelling = validate_success(api.get_dwelling(ctx["dwelling"]["id"], PROGRAM_ADMIN_HEADERS))
    assert dwelling["grant_lifetime_count"] == 0


def test_15_finalizing_an_adjustment_posts_the_settlement_into_the_loss_aggregate(api):
    """The first two hops: the final settlement supersedes the provisional figure and
    the event's gross incurred loss takes it up.

    PRD: "`final_payable_cents` is the sum of the three parts, `payable_cents` is set equal to it — the final figure supersedes the provisional one — and the acting `X-User-ID` is recorded as `final_adjuster_user_id`."
    PRD: "Hop two, caused by the claim reaching `FINAL_ADJUSTED`: the event's `aggregate_incurred_cents` rises by the claim's `final_payable_cents` and the event's `version` rises by one, and if the event was `DECLARED` it advances `DECLARED → LOSS_AGGREGATION`."

    Design: Difficulty/transitive_cascade/finalize_adjustment_cascades_four_hops_to_capacity_exhausted
    """
    ctx = _provisionally_adjusted_tower_claim(api)
    event_before = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert event_before["status"] == "DECLARED"
    assert event_before["aggregate_incurred_cents"] == 0
    assert ctx["claim"]["adjustment_status"] == "PROVISIONAL_ADJUSTED"

    claim = validate_success(
        api.finalize_claim_adjustment(ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS)
    )
    assert claim["adjustment_status"] == "FINAL_ADJUSTED"
    assert claim["deductible_applied_cents"] == 15000000
    assert claim["final_payable_cents"] == TOWER_SETTLEMENT_CENTS
    assert claim["payable_cents"] == TOWER_SETTLEMENT_CENTS
    assert claim["final_adjuster_user_id"] == CLAIM_ADJUSTER_ALT_HEADERS["X-User-ID"]
    assertions.assert_settlement_parts_sum(claim, TOWER_SETTLEMENT_CENTS)

    event = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert event["aggregate_incurred_cents"] == TOWER_SETTLEMENT_CENTS
    assert event["version"] == event_before["version"] + 1


def test_16_finalizing_an_adjustment_re_runs_the_waterfall_across_the_whole_tower(api):
    """The third hop: the retention fills, both active layers cede their own exposure,
    and what is left over is the residual.

    PRD: "Hop three, caused by the gross changing: the loss waterfall of section 3.7 re-runs, rewriting the event's `retained_cents`, every participating layer's `ceded_cents`, the event's `ceded_total_cents` and its `uncovered_cents`."
    PRD: "First, `retained_cents` becomes the smaller of the gross and the event's `retention_cents`."
    PRD: "For each such layer, the exposure is the gross capped at the top of the layer — that is, the smaller of the gross and the sum of `attachment_point_cents` and `limit_cents` — less the layer's `attachment_point_cents`, with any negative result treated as zero; the layer's `ceded_cents` is that exposure multiplied by its `ceded_pct`, rounded half up to whole cents, one rounding per layer."
    PRD: "`ceded_total_cents` is the sum of the `ceded_cents` of the participating layers, and `uncovered_cents` is the gross less `retained_cents` less `ceded_total_cents`, floored at zero — it is a residual and is never independently rounded."

    Design: Difficulty/transitive_cascade/finalize_adjustment_cascades_four_hops_to_capacity_exhausted
    """
    ctx = _provisionally_adjusted_tower_claim(api)
    validate_success(
        api.finalize_claim_adjustment(ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS)
    )

    layer_one = validate_success(
        api.get_reinsurance_layer(ctx["layer"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    layer_two = validate_success(
        api.get_reinsurance_layer(ctx["layer_two"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    # Layer one is exposed for its full 50,000,000 width at ninety per cent.
    assert layer_one["ceded_cents"] == 45000000
    # Layer two is exposed for its full 60,000,000 width at seventy-five per cent.
    assert layer_two["ceded_cents"] == 45000000

    event = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert event["aggregate_incurred_cents"] == TOWER_SETTLEMENT_CENTS
    assert event["retained_cents"] == RETENTION_CENTS
    assert event["ceded_total_cents"] == 90000000
    assert event["uncovered_cents"] == TOWER_SETTLEMENT_CENTS - RETENTION_CENTS - 90000000
    assertions.assert_event_loss_conserved(event)


def test_17_a_loss_that_outruns_the_tower_drives_the_event_to_capacity_exhausted(api):
    """The fourth hop: an uncovered residual strictly above zero exhausts the
    programme's capacity for the event.

    PRD: "Hop four, caused by `uncovered_cents` becoming strictly greater than zero: the event advances `LOSS_AGGREGATION → CAPACITY_EXHAUSTED`."
    PRD: "Finally, if the recomputed `uncovered_cents` is strictly greater than zero and the event is currently `LOSS_AGGREGATION`, the event advances `LOSS_AGGREGATION → CAPACITY_EXHAUSTED`."

    Design: Difficulty/transitive_cascade/finalize_adjustment_cascades_four_hops_to_capacity_exhausted
    """
    ctx = _provisionally_adjusted_tower_claim(api)
    validate_success(
        api.finalize_claim_adjustment(ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS)
    )

    event = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert event["uncovered_cents"] > 0
    assert event["status"] == "CAPACITY_EXHAUSTED"


def test_18_a_loss_covered_to_the_cent_stays_in_loss_aggregation(api):
    """The fourth hop does not fire on an exactly covered loss: the same settlement
    under a wide single layer leaves no residual, so the event stops at the third hop.

    PRD: "Hop four, caused by `uncovered_cents` becoming strictly greater than zero: the event advances `LOSS_AGGREGATION → CAPACITY_EXHAUSTED`."
    PRD: "Finally, if the recomputed `uncovered_cents` is strictly greater than zero and the event is currently `LOSS_AGGREGATION`, the event advances `LOSS_AGGREGATION → CAPACITY_EXHAUSTED`. Strictly greater is meant literally: a loss that is exactly covered to the cent stays in `LOSS_AGGREGATION`."

    Design: Difficulty/transitive_cascade/finalize_adjustment_cascades_four_hops_to_capacity_exhausted
    """
    ctx = fixtures.setup_event_with_policy(
        api,
        clock=EVENT_CLOCK,
        dwelling_overrides=TOWER_DWELLING,
        policy_overrides=TOWER_POLICY,
        event_overrides={
            "magnitude": 7.1,
            "occurred_at": EVENT_OCCURRED_AT,
            "retention_cents": RETENTION_CENTS,
        },
    )
    ctx = fixtures.setup_provisionally_adjusted_claim(api, ctx=ctx, **TOWER_CLAIM)
    validate_success(
        api.finalize_claim_adjustment(ctx["claim"]["id"], None, CLAIM_ADJUSTER_ALT_HEADERS)
    )

    layer = validate_success(
        api.get_reinsurance_layer(ctx["layer"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    # The single layer runs from 100,000,000 to 500,000,000 and cedes in full, so
    # it absorbs everything above the retention: 235,000,000 - 100,000,000.
    assert layer["ceded_cents"] == 135000000

    event = validate_success(
        api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS)
    )
    assert event["aggregate_incurred_cents"] == TOWER_SETTLEMENT_CENTS
    assert event["retained_cents"] == RETENTION_CENTS
    assert event["ceded_total_cents"] == 135000000
    assert event["uncovered_cents"] == 0
    assert event["status"] == "LOSS_AGGREGATION"
    assertions.assert_event_loss_conserved(event)
