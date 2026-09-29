"""Values landing exactly on a declared threshold, and the neighbour one step away.

Every expected number here was computed against the PRD formulas with half-up
rounding and pasted in as a literal, so a test failure means the implementation
disagrees with the contract rather than with a re-derivation.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    build_rating_spine,
    create_enrolled_provider,
    create_coaching_allocation_payload,
    credential_specs,
    make_admin_headers,
    make_observer_headers,
    make_provider_headers,
    set_clock,
    setup_open_grant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

#: Unequal point ceilings so a weighted total can be steered onto an exact cutoff.
#: Weights sum to exactly 1.00 and LEARNING_ENVIRONMENT is the observation-linked domain.
STEP_DOMAINS = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 40,
        "block_min_points": 20,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 4.00,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 30,
        "block_min_points": 15,
        "weight": 0.25,
        "observation_linked": False,
    },
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 10,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 6,
        "weight": 0.15,
        "observation_linked": False,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 10,
        "block_min_points": 5,
        "weight": 0.10,
        "observation_linked": False,
    },
]

# --- 1. the inclusive reliability threshold ---------------------------------

POINTS_G = {
    "LEARNING_ENVIRONMENT": 22,
    "STAFF_QUALIFICATIONS": 16,
    "FAMILY_PARTNERSHIP": 10,
    "ADMINISTRATION": 6,
    "CHILD_ASSESSMENT": 5,
}

#: Lead sits flat at 5.0; the secondary misses ACTIVITIES and INTERACTION by 1.5,
#: leaving four of six subscales matched.
SECONDARY_FOUR_MATCHED = {
    "SPACE_FURNISHINGS": 5.0,
    "PERSONAL_CARE": 6.0,
    "LANGUAGE_REASONING": 4.0,
    "ACTIVITIES": 6.5,
    "INTERACTION": 3.5,
    "PROGRAM_STRUCTURE": 5.0,
}


def test_reliability_of_66_67_is_refused_and_exactly_83_33_is_admitted(api):
    """PRD §3.4: "The reliability percentage is one hundred multiplied by the matched count,
    divided by six, and rounded half up to two decimal places."
    PRD §3.4: "Scores are admissible when that percentage is at least 83.33 — the comparison
    is inclusive."
    PRD §3.4: "Five matched subscales produce exactly 83.33 and therefore pass; four matched
    subscales produce 66.67 and fail."
    PRD §3.4: "From `RELIABILITY_CHECK`, either observer may replace a subscale score; that
    submission returns the visit `RELIABILITY_CHECK → SCORES_ENTERED`, appends the new attempt
    row, demotes the prior row, increments `rescore_count` by 1, and recomputes both the
    composite and the reliability percentage."

    Design: Difficulty/boundary_precision_check/reliability_pct_inclusive_at_exactly_83_33
    """
    ctx = build_rating_spine(
        stop_at="RELIABILITY_CHECK",
        domains=STEP_DOMAINS,
        provider_overrides={
            "legal_name": "Greenfield Child Development",
            "county_code": "LWS",
            "region_code": "URBAN",
            "licensed_capacity": 40,
            "active_staff_fte": 8.00,
            "weekly_onsite_cap_hours": 16,
        },
        credentials=[],
        claimed=POINTS_G,
        verified=POINTS_G,
        raw_score=5.0,
        with_secondary=True,
        secondary_per_subscale=SECONDARY_FOUR_MATCHED,
    )
    visit = ctx["visit"]
    assert visit["status"] == "RELIABILITY_CHECK", (
        f"six lead and six secondary rows must reach RELIABILITY_CHECK, got {visit['status']}"
    )
    assert visit["reliability_pct"] == pytest.approx(66.67, abs=0.005), (
        f"four matched subscales must give 66.67, got {visit['reliability_pct']}"
    )
    assert visit["rescore_count"] == 0

    refused = api.finalize_visit(visit["id"], ADMIN)
    validate_error(refused, "ERR_RELIABILITY_BELOW_THRESHOLD", 422)
    still_open = validate_success(api.get_observation_visit(visit["id"], ADMIN))
    assert still_open["status"] == "RELIABILITY_CHECK"
    assert still_open["finalized_on"] is None

    # One rescore moves ACTIVITIES from 6.5 to 6.0, a 1.0 gap that now counts as matched.
    replacement = validate_success(
        api.submit_score(
            visit["id"],
            {"subscale_code": "ACTIVITIES", "raw_score": 6.0},
            make_observer_headers(ctx["secondary"]["id"]),
        ),
        201,
    )
    assert replacement["attempt_no"] == 2, (
        f"the replacement row must carry attempt_no 2, got {replacement['attempt_no']}"
    )
    assert replacement["is_current"] is True

    finalized = validate_success(api.finalize_visit(visit["id"], ADMIN))
    assert finalized["status"] == "FINALIZED"
    assert finalized["rescore_count"] == 1, (
        f"exactly one rescore was submitted, got {finalized['rescore_count']}"
    )
    assert finalized["composite"] == pytest.approx(5.00, abs=0.005), (
        "the composite is the lead observer's flat 5.0 average and the secondary rescore "
        f"cannot move it, got {finalized['composite']}"
    )
    assert finalized["reliability_pct"] == pytest.approx(83.33, abs=0.005), (
        f"five matched subscales must give exactly 83.33, got {finalized['reliability_pct']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_FINALIZED"
    assert cycle["observation_composite"] == pytest.approx(5.00, abs=0.005)
    assert cycle["reliability_pct"] == pytest.approx(83.33, abs=0.005)


# --- 2. the inclusive tier-4 cutoff and the inclusive compliance floor -------

POINTS_H = {
    "LEARNING_ENVIRONMENT": 30,
    "STAFF_QUALIFICATIONS": 26,
    "FAMILY_PARTNERSHIP": 14,
    "ADMINISTRATION": 8,
    "CHILD_ASSESSMENT": 6,
}


def _spine_at_tier_four_cutoff(qualifying_fte):
    """Observation-finalized cycle whose final run lands on weighted_total 70.00.

    ``qualifying_fte`` against a declared `active_staff_fte` of 10.00 sets
    `credential_compliance_pct`, which is what moves across the tier-4 floor.
    """
    return build_rating_spine(
        stop_at="OBSERVATION_FINALIZED",
        domains=STEP_DOMAINS,
        provider_overrides={
            "legal_name": "Harborview Early Learning",
            "county_code": "CLK",
            "region_code": "URBAN",
            "licensed_capacity": 90,
            "active_staff_fte": 10.00,
            "weekly_onsite_cap_hours": 20,
        },
        credentials=credential_specs(qualifying_fte),
        claimed=POINTS_H,
        verified=POINTS_H,
        raw_score=5.0,
        with_secondary=True,
        window_start="2026-08-12T09:00:00Z",
        window_end="2026-08-12T12:00:00Z",
    )


def test_weighted_total_of_exactly_70_00_with_compliance_exactly_90_00_awards_tier_4(api):
    """PRD §3.5: "From that total alone comes `points_tier`: 5 when the weighted total is at
    least 85.00, 4 when it is at least 70.00, 3 when it is at least 55.00, 2 when it is at
    least 40.00, and 1 otherwise. Every one of those comparisons is inclusive, so a weighted
    total of exactly 70.00 is tier 4 while 69.99 is tier 3."
    PRD §3.5: "Third, the compliance floor: the provider's `credential_compliance_pct` must
    reach the minimum for the tier the determination just produced — measured against
    `awarded_tier`, not against `points_tier` — where tier 1 requires 0.00, tier 2 requires
    60.00, tier 3 requires 80.00, tier 4 requires 90.00, and tier 5 requires 95.00."
    PRD §3.5: "`validity_months` is 36 when `awarded_tier` is at least 4 and 24 otherwise."
    PRD §3.5: "`rerating_window_opens_on` is the expiry date minus 90 calendar days at
    midnight UTC — the earliest date on which a re-rating cycle may be opened."

    Design: Difficulty/boundary_precision_check/weighted_total_exactly_at_tier_4_cutoff_and_compliance_floor
    """
    ctx = _spine_at_tier_four_cutoff(9.00)
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["credential_compliance_pct"] == pytest.approx(90.00, abs=0.005), (
        "9.00 qualifying fte against a declared 10.00 is exactly 90.00, the tier-4 floor, "
        f"got {provider['credential_compliance_pct']}"
    )

    set_clock("2026-08-12T18:00:00Z")
    awarded = validate_success(
        api.award_cycle(
            ctx["cycle"]["id"], {"score_variant": "FINAL"}, make_admin_headers("sa-award-8")
        )
    )
    assert awarded["observation_composite"] == pytest.approx(5.00, abs=0.005)
    assert awarded["domain_points"] == {
        "LEARNING_ENVIRONMENT": 32,
        "STAFF_QUALIFICATIONS": 24,
        "FAMILY_PARTNERSHIP": 14,
        "ADMINISTRATION": 8,
        "CHILD_ASSESSMENT": 6,
    }, (
        "a composite of 5.00 gives the 0.80 observation fraction (40 x 0.80 = 32) and a "
        "compliance of 90.00 gives the 0.80 credential fraction, capping the credited 26 "
        f"staff points at 24; got {awarded['domain_points']}"
    )
    assert awarded["weighted_total"] == pytest.approx(70.00, abs=0.005), (
        f"weighted_total must land on exactly 70.00, got {awarded['weighted_total']}"
    )
    assert awarded["points_tier"] == 4, (
        f"70.00 is inclusive of the tier-4 cutoff, got points_tier {awarded['points_tier']}"
    )
    assert awarded["highest_block_cleared"] == 3
    assert awarded["awarded_tier"] == 4
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_by_user_id"] == "sa-award-8"
    assert awarded["validity_months"] == 36
    assert awarded["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert awarded["expires_on"] == "2029-08-31T23:59:59.999Z"
    assert awarded["rerating_window_opens_on"] == "2029-06-02T00:00:00.000Z"


def test_compliance_of_89_00_fails_the_tier_4_floor_on_the_same_weighted_total(api):
    """PRD §3.5: "Third, the compliance floor: the provider's `credential_compliance_pct` must
    reach the minimum for the tier the determination just produced — measured against
    `awarded_tier`, not against `points_tier` — where tier 1 requires 0.00, tier 2 requires
    60.00, tier 3 requires 80.00, tier 4 requires 90.00, and tier 5 requires 95.00; a
    shortfall is `ERR_CREDENTIAL_COMPLIANCE_BELOW_MINIMUM` with HTTP 422."
    PRD §3.5: "The credential fraction is 1.00 when `credential_compliance_pct` is at least
    95.00, 0.80 when it is at least 85.00, 0.60 when it is at least 70.00, 0.40 when it is at
    least 55.00, and 0.20 otherwise."
    PRD §3.2: "The percentage is one hundred multiplied by the numerator and divided by the
    denominator, rounded half up to two decimal places, and then capped so the stored
    `credential_compliance_pct` never exceeds 100.00."

    Design: Difficulty/boundary_precision_check/weighted_total_exactly_at_tier_4_cutoff_and_compliance_floor
    """
    ctx = _spine_at_tier_four_cutoff(8.90)
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["credential_compliance_pct"] == pytest.approx(89.00, abs=0.005), (
        "8.90 qualifying fte against a declared 10.00 is 89.00, one point under the floor, "
        f"got {provider['credential_compliance_pct']}"
    )

    set_clock("2026-08-12T18:00:00Z")
    refused = api.award_cycle(
        ctx["cycle"]["id"], {"score_variant": "FINAL"}, make_admin_headers("sa-award-8")
    )
    validate_error(refused, "ERR_CREDENTIAL_COMPLIANCE_BELOW_MINIMUM", 422)

    # 89.00 is still inside the 0.80 credential band, so the staff cap and therefore the
    # weighted total are unchanged at the tier-4 cutoff: only the floor moved the outcome.
    preview = validate_success(
        api.get_score_preview(ctx["cycle"]["id"], ADMIN, params={"variant": "FINAL"})
    )
    assert preview["weighted_total"] == pytest.approx(70.00, abs=0.005), (
        f"weighted_total must still be exactly 70.00, got {preview['weighted_total']}"
    )
    assert preview["awarded_tier"] == 4
    unchanged = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert unchanged["status"] == "OBSERVATION_FINALIZED"
    assert unchanged["awarded_tier"] is None
    assert unchanged["awarded_on"] is None


# --- 3. the inclusive hours ceiling and the strict admin-fee breakpoint -------


def test_coaching_hours_cap_admits_exactly_40_0_and_refuses_40_1(api):
    """PRD §3.9: "The hours ceiling is 40.0 hours at tier 1, 32.0 at tier 2, 24.0 at tier 3,
    16.0 at tier 4, and 8.0 at tier 5; `allocated_hours` above the ceiling for the effective
    tier is refused with `ERR_COACHING_HOURS_CAP_EXCEEDED` and HTTP 422."
    PRD §3.9: "The **effective tier** is the provider's `current_tier`, or 1 when the provider
    has no current tier."
    PRD §3.9: "Second, `admin_fee_cents` is that base cost multiplied by an administrative fee
    rate and rounded half up to whole cents, where the rate is 0.12 when the base cost is
    below 50,000 cents, 0.09 when the base cost is below 200,000 cents, and 0.06 otherwise;
    both breakpoints are strict on their upper bound, so a base cost of exactly 50,000 cents
    falls in the 0.09 band while 49,999 cents falls in the 0.12 band."
    PRD §3.9: "The hours check is evaluated before the spend check."

    Design: Difficulty/boundary_precision_check/coaching_hours_cap_inclusive_and_admin_fee_band_strict_less_than
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_enrolled_provider(
        legal_name="Juniper Court Child Care",
        county_code="ADA",
        region_code="URBAN",
        licensed_capacity=35,
        active_staff_fte=5.00,
        weekly_onsite_cap_hours=10,
    )
    assert provider["current_tier"] is None, (
        "an unrated provider has no current tier, so the effective tier is 1"
    )

    on_the_cap = validate_success(
        api.create_coaching_allocation(
            provider["id"],
            create_coaching_allocation_payload(
                "coach-21",
                funding_source="STATE_BASE",
                funding_grant_id=None,
                period_start="2026-08-03",
                period_end="2026-11-30",
                allocated_hours=40.0,
                hourly_rate_cents=1250,
            ),
            ADMIN,
        ),
        201,
    )
    assert on_the_cap["status"] == "PROPOSED"
    assert on_the_cap["base_hours_cost_cents"] == 50000, (
        f"40.0 hours at 1250 cents is 50000, got {on_the_cap['base_hours_cost_cents']}"
    )
    assert on_the_cap["admin_fee_cents"] == 4500, (
        "a base of exactly 50000 is not below 50000, so the 0.09 band applies, "
        f"got {on_the_cap['admin_fee_cents']}"
    )
    assert on_the_cap["total_cost_cents"] == 54500
    assert on_the_cap["spend_cap_cents"] == 500000, (
        "the tier-1 spend ceiling is 900000 but the state base appropriation bears only "
        f"500000, got {on_the_cap['spend_cap_cents']}"
    )

    over_the_cap = api.create_coaching_allocation(
        provider["id"],
        create_coaching_allocation_payload(
            "coach-21",
            funding_source="STATE_BASE",
            funding_grant_id=None,
            period_start="2026-08-03",
            period_end="2026-11-30",
            allocated_hours=40.1,
            hourly_rate_cents=1250,
        ),
        ADMIN,
    )
    validate_error(over_the_cap, "ERR_COACHING_HOURS_CAP_EXCEEDED", 422)

    one_cent_under_the_band = validate_success(
        api.create_coaching_allocation(
            provider["id"],
            create_coaching_allocation_payload(
                "coach-22",
                funding_source="STATE_BASE",
                funding_grant_id=None,
                period_start="2026-08-03",
                period_end="2026-11-30",
                allocated_hours=1.0,
                hourly_rate_cents=49999,
            ),
            ADMIN,
        ),
        201,
    )
    assert one_cent_under_the_band["base_hours_cost_cents"] == 49999
    assert one_cent_under_the_band["admin_fee_cents"] == 6000, (
        "49999 is below the 50000 breakpoint, so the 0.12 band applies and 5999.88 rounds "
        f"half up to 6000, got {one_cent_under_the_band['admin_fee_cents']}"
    )
    assert one_cent_under_the_band["total_cost_cents"] == 55999
    assert (
        one_cent_under_the_band["total_cost_cents"] > on_the_cap["total_cost_cents"]
    ), (
        "the band is strict on its upper bound, so a base one cent smaller carries a "
        "larger total than a base sitting exactly on the breakpoint"
    )

    allocations, _meta = validate_paginated(
        api.list_coaching_allocations(ADMIN, params={"provider_id": provider["id"]})
    )
    assert len(allocations) == 2, (
        f"only the two admitted allocations may exist, got {len(allocations)}"
    )


# --- 4. inclusive category ceilings and the zero-balance edge -----------------

GRANT_DOMAINS = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 40,
        "block_min_points": 10,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 3.00,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 30,
        "block_min_points": 5,
        "weight": 0.25,
        "observation_linked": False,
    },
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 8,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 5,
        "weight": 0.15,
        "observation_linked": False,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 10,
        "block_min_points": 4,
        "weight": 0.10,
        "observation_linked": False,
    },
]

POINTS_K = {
    "LEARNING_ENVIRONMENT": 16,
    "STAFF_QUALIFICATIONS": 8,
    "FAMILY_PARTNERSHIP": 10,
    "ADMINISTRATION": 6,
    "CHILD_ASSESSMENT": 5,
}


def test_category_ceilings_are_inclusive_and_the_last_cent_drives_availability_to_zero(api):
    """PRD §3.8: "Each cost category has a ceiling expressed as a share of the grant: equipment
    may consume up to 40 percent of `awarded_amount_cents`, professional development up to 30
    percent, facility work up to 25 percent, and administrative costs up to 10 percent, each
    computed by multiplying the awarded amount by that share and discarding any fractional
    cent."
    PRD §3.8: "A submission is admitted when the category's existing `category_spend_cents`
    entry plus the new `amount_cents` is no greater than that ceiling — the comparison is
    inclusive, so a submission landing exactly on the ceiling is accepted — and otherwise
    refused with `ERR_GRANT_CATEGORY_CEILING_EXCEEDED` and HTTP 422."
    PRD §3.8: "The grant balance check requires `amount_cents` to be no greater than
    `available_cents`; a submission consuming exactly the remaining availability is accepted
    and leaves `available_cents` at 0, while a larger one is refused with
    `ERR_GRANT_FUNDS_EXHAUSTED` and HTTP 422."
    PRD §3.8: "An accepted submission creates the line in `SUBMITTED` with `reimbursable_cents`
    and `disallowed_cents` at 0, adds its amount to `committed_cents`, subtracts it from
    `available_cents`, adds it to that category's entry in `category_spend_cents`, and
    increments the grant's `version` by 1."

    Design: Difficulty/boundary_precision_check/grant_category_ceiling_floor_and_available_cents_zero_edge
    """
    spine = build_rating_spine(
        stop_at="ACTIVE",
        domains=GRANT_DOMAINS,
        provider_overrides={
            "legal_name": "Kestrel Lane Learning Center",
            "county_code": "BEN",
            "region_code": "URBAN",
            "licensed_capacity": 30,
            "active_staff_fte": 10.00,
            "weekly_onsite_cap_hours": 14,
        },
        credentials=[],
        claimed=POINTS_K,
        verified=POINTS_K,
        raw_score=3.0,
        window_start="2026-08-12T09:00:00Z",
        window_end="2026-08-12T12:00:00Z",
        award_clock="2026-08-12T18:00:00Z",
        activation_clock="2026-09-01T00:00:00Z",
    )
    cycle = validate_success(api.get_rating_cycle(spine["cycle"]["id"], ADMIN))
    assert cycle["observation_composite"] == pytest.approx(3.00, abs=0.005)
    assert cycle["domain_points"]["LEARNING_ENVIRONMENT"] == 16
    assert cycle["domain_points"]["STAFF_QUALIFICATIONS"] == 6, (
        "no verified credential leaves compliance at 0.00, whose credential fraction is "
        f"0.20, capping 30 max points at 6; got {cycle['domain_points']}"
    )
    assert cycle["weighted_total"] == pytest.approx(36.50, abs=0.005)
    assert cycle["awarded_tier"] == 1

    set_clock("2026-09-02T00:00:00Z")
    provider_id = spine["provider"]["id"]
    _ctx, grant = setup_open_grant(
        spine=spine, awarded_amount_cents=1_000_005, spend_deadline="2026-12-31"
    )
    assert grant["status"] == "OPEN"
    assert grant["available_cents"] == 1_000_005

    provider_headers = make_provider_headers(provider_id)

    def spend(category, amount_cents):
        version = validate_success(api.get_improvement_grant(grant["id"], ADMIN))["version"]
        return api.create_expenditure(
            grant["id"],
            {
                "category": category,
                "amount_cents": amount_cents,
                "invoice_date": "2026-09-02",
                "expected_grant_version": version,
            },
            provider_headers,
        )

    # 10 percent of 1000005 is 100000.5, so the ADMIN ceiling floors to 100000.
    admin_line = validate_success(spend("ADMIN", 100_000), 201)
    assert admin_line["status"] == "SUBMITTED"

    # 30 percent of 1000005 is 300001.5, so the PROF_DEV ceiling floors to 300001.
    validate_error(spend("PROF_DEV", 300_002), "ERR_GRANT_CATEGORY_CEILING_EXCEEDED", 422)
    after_refusal = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert after_refusal["committed_cents"] == 100_000, (
        f"a refused submission must commit nothing, got {after_refusal['committed_cents']}"
    )
    assert after_refusal["available_cents"] == 900_005
    assert after_refusal["category_spend_cents"]["PROF_DEV"] == 0

    prof_dev_line = validate_success(spend("PROF_DEV", 300_001), 201)
    assert prof_dev_line["status"] == "SUBMITTED"
    # 40 percent of 1000005 is 400002.0, so the EQUIPMENT ceiling is exactly 400002.
    validate_success(spend("EQUIPMENT", 400_002), 201)
    # 200002 is inside the 250001 FACILITY ceiling and consumes the last available cent.
    validate_success(spend("FACILITY", 200_002), 201)

    drained = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert drained["available_cents"] == 0, (
        "100000 + 300001 + 400002 + 200002 is exactly 1000005, so availability must be 0, "
        f"got {drained['available_cents']}"
    )
    assert drained["committed_cents"] == 1_000_005
    assert drained["category_spend_cents"]["ADMIN"] == 100_000
    assert drained["category_spend_cents"]["PROF_DEV"] == 300_001
    assert drained["category_spend_cents"]["EQUIPMENT"] == 400_002
    assert drained["category_spend_cents"]["FACILITY"] == 200_002

    validate_error(spend("FACILITY", 1), "ERR_GRANT_FUNDS_EXHAUSTED", 422)
    unchanged = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert unchanged["available_cents"] == 0
    assert unchanged["committed_cents"] == 1_000_005
    assert unchanged["category_spend_cents"]["FACILITY"] == 200_002
