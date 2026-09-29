"""Rounding regimes and boundary placement across the derived-quantity calculations.

Credential compliance filtering and its cap, the observation composite and the
inter-rater reliability boundary, the weighted total and the sequential block fold,
the coaching administrative-fee band, and the per-age-band subsidy rounding.
"""
import pytest

from test_helpers import (
    COACH_USER_ID,
    SUBSCALE_CODES,
    TEST_USERS,
    add_credential,
    build_rating_spine,
    create_coaching_allocation_payload,
    create_enrolled_provider,
    make_observer_headers,
    points_map,
    run_expiry_run,
    score_payload,
    set_clock,
    setup_tier_one_active_spine,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

#: The tier-4 point map used by the weighted-total and subsidy instances.
TIER_FOUR_POINTS = points_map(learning=16, staff=12, family=10, administration=16, child=16)
#: Block 2 is starved while block 3 is fully cleared.
BLOCK_GAP_POINTS = points_map(learning=20, staff=20, family=4, administration=20, child=20)


# --- credential compliance ---------------------------------------------------


def test_credential_compliance_counts_only_rows_passing_all_four_filters(api):
    """PRD §3.2: "The numerator is the sum of the `fte` values of the provider's staff
    credential records that satisfy all four of these conditions at once: the record
    belongs to that provider, its `employment_status` is `ACTIVE`, its `registry_status`
    is `VERIFIED`, its `expires_on` is on or after the logical clock date, and its
    `credential_level` is at least the minimum for its `role_type`."
    PRD §3.2: "Each role carries a minimum credential level: a `DIRECTOR` must hold level
    4 or higher, a `LEAD_TEACHER` level 3 or higher, and an `ASSISTANT` level 1 or higher."
    PRD §3.2: "Records that are `UNLINKED`, `PENDING`, or `EXPIRED` contribute nothing,
    and `SEPARATED` records are excluded from the numerator but never from the
    denominator."
    PRD §3.2: "The denominator is always the provider's declared `active_staff_fte`."
    PRD §3.2: "Each registry write recomputes the provider's `credential_compliance_pct`
    and increments the provider's `version` by 1."

    Design: Corner/calculations/credential_compliance_filters_by_registry_status_and_level_floor
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_enrolled_provider(
        legal_name="Maple Learning",
        county_code="DANE",
        region_code="URBAN",
        licensed_capacity=40,
        active_staff_fte=4.00,
    )
    # Qualifies: DIRECTOR at level 4 whose verification expires on the clock date itself.
    add_credential(provider["id"], expires_on="2026-08-01",
                   role_type="DIRECTOR", credential_level=4, fte=1.00)
    # Excluded: LEAD_TEACHER below the level-3 floor for its role.
    add_credential(provider["id"], expires_on="2030-01-01",
                   role_type="LEAD_TEACHER", credential_level=2, fte=1.00)
    # Qualifies: ASSISTANT at the level-1 floor.
    add_credential(provider["id"], expires_on="2030-01-01",
                   role_type="ASSISTANT", credential_level=1, fte=1.00)
    # Excluded from the numerator only: SEPARATED DIRECTOR at level 5.
    add_credential(provider["id"], expires_on="2030-01-01",
                   role_type="DIRECTOR", credential_level=5, fte=1.00,
                   employment_status="SEPARATED")
    # Excluded until the registry answers: UNLINKED LEAD_TEACHER at level 5.
    pending = add_credential(provider["id"], registry_status="UNLINKED",
                             role_type="LEAD_TEACHER", credential_level=5, fte=1.00)

    before = validate_success(api.get_credential_compliance(provider["id"], ADMIN))
    assert before["credential_compliance_pct"] == pytest.approx(50.00, abs=0.005), (
        "two qualifying fte of an active_staff_fte of 4.00 is 50.00, got "
        f"{before['credential_compliance_pct']}"
    )

    linked = validate_success(
        api.registry_link(
            pending["id"],
            {"registry_status": "VERIFIED", "verified_on": "2026-08-01",
             "expires_on": "2030-01-01", "credential_level": 5},
            ADMIN,
        )
    )
    assert linked["registry_status"] == "VERIFIED"

    after = validate_success(api.get_provider(provider["id"], ADMIN))
    assert after["credential_compliance_pct"] == pytest.approx(75.00, abs=0.005), (
        "verifying the level-5 LEAD_TEACHER lifts three qualifying fte over 4.00 to "
        f"75.00, got {after['credential_compliance_pct']}"
    )
    assert float(after["active_staff_fte"]) == pytest.approx(4.00, abs=0.005), (
        "the declared active_staff_fte is the permanent denominator and never moves"
    )

    rows, meta = validate_paginated(
        api.list_staff_credentials(
            ADMIN, params={"provider_id": provider["id"], "registry_status": "VERIFIED"}
        )
    )
    assert meta["total_count"] == 5, (
        "all five records now carry VERIFIED, including the SEPARATED one and the "
        f"under-level LEAD_TEACHER that the numerator still excludes, got "
        f"{meta['total_count']}"
    )
    assert all(row["registry_status"] == "VERIFIED" for row in rows)


def test_credential_compliance_expires_on_boundary_is_inclusive(api):
    """PRD §3.2: "Moving a record to `VERIFIED` requires both dates: `verified_on`, the
    logical-clock date the linkage was confirmed, and `expires_on`, the inclusive last
    date the verified credential remains valid."
    PRD §3.2: "The numerator is the sum of the `fte` values of the provider's staff
    credential records that satisfy all four of these conditions at once: the record
    belongs to that provider, its `employment_status` is `ACTIVE`, its `registry_status`
    is `VERIFIED`, its `expires_on` is on or after the logical clock date, and its
    `credential_level` is at least the minimum for its `role_type`."
    PRD §3.5: "The expiry run is also where deferred promotions and deadline-driven
    freezes happen: awarded cycles whose `effective_date` has arrived advance to `ACTIVE`
    with the supersession cascade above, open grants whose `spend_deadline` has passed
    advance to `FROZEN` with their submitted expenditures voided, and every provider's
    `credential_compliance_pct` is recomputed."

    Design: Corner/calculations/credential_compliance_expires_on_boundary_is_inclusive
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_enrolled_provider(
        legal_name="Birch House",
        county_code="DANE",
        region_code="RURAL",
        licensed_capacity=30,
        active_staff_fte=4.00,
    )
    director = add_credential(provider["id"], expires_on="2026-08-01",
                              role_type="DIRECTOR", credential_level=4, fte=1.00)
    add_credential(provider["id"], expires_on="2030-01-01",
                   role_type="ASSISTANT", credential_level=1, fte=1.00)

    at_boundary = validate_success(api.get_provider(provider["id"], ADMIN))
    assert at_boundary["credential_compliance_pct"] == pytest.approx(50.00, abs=0.005), (
        "a credential expiring exactly on the clock date still counts, so two of four "
        f"fte is 50.00, got {at_boundary['credential_compliance_pct']}"
    )

    set_clock("2026-08-02T00:00:00Z")
    run_expiry_run()

    past_boundary = validate_success(api.get_provider(provider["id"], ADMIN))
    assert past_boundary["credential_compliance_pct"] == pytest.approx(25.00, abs=0.005), (
        "one day past expires_on the DIRECTOR drops out, leaving one of four fte at "
        f"25.00, got {past_boundary['credential_compliance_pct']}"
    )
    stored = validate_success(api.get_staff_credential(director["id"], ADMIN))
    assert float(stored["fte"]) == pytest.approx(1.00, abs=0.005)
    assert stored["registry_status"] == "VERIFIED", (
        "the expiry recomputation filters on the date and does not rewrite registry_status"
    )


def test_credential_compliance_is_capped_at_one_hundred(api):
    """PRD §3.2: "The percentage is one hundred multiplied by the numerator and divided by
    the denominator, rounded half up to two decimal places, and then capped so the stored
    `credential_compliance_pct` never exceeds 100.00."
    PRD §3.2: "Each registry write recomputes the provider's `credential_compliance_pct`
    and increments the provider's `version` by 1."
    PRD §3.2: "This figure is recomputed on every credential registration, on every registry
    write, on approval of an enrollment application, on every expiry run, on the computed
    compliance read, and immediately before the per-domain points award is computed inside
    any scoring request."

    Design: Corner/calculations/credential_compliance_caps_at_one_hundred
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_enrolled_provider(
        legal_name="Cedar Cottage",
        county_code="IOWA",
        region_code="FRONTIER",
        licensed_capacity=12,
        active_staff_fte=2.00,
    )
    add_credential(provider["id"], expires_on="2030-01-01",
                   role_type="DIRECTOR", credential_level=6, fte=1.00)
    add_credential(provider["id"], expires_on="2030-01-01",
                   role_type="LEAD_TEACHER", credential_level=3, fte=1.00)
    third = add_credential(provider["id"], registry_status="UNLINKED",
                           role_type="DIRECTOR", credential_level=6, fte=1.00)

    validate_success(
        api.registry_link(
            third["id"],
            {"registry_status": "VERIFIED", "verified_on": "2026-08-01",
             "expires_on": "2030-01-01", "credential_level": 6},
            ADMIN,
        )
    )

    provider_after = validate_success(api.get_provider(provider["id"], ADMIN))
    assert provider_after["credential_compliance_pct"] == pytest.approx(100.00, abs=0.005), (
        "three qualifying fte over an active_staff_fte of 2.00 is a raw 150.00 that must "
        f"be stored capped at 100.00, got {provider_after['credential_compliance_pct']}"
    )
    assert float(provider_after["active_staff_fte"]) == pytest.approx(2.00, abs=0.005)

    computed = validate_success(api.get_credential_compliance(provider["id"], ADMIN))
    assert computed["credential_compliance_pct"] == pytest.approx(100.00, abs=0.005), (
        "the computed read applies the same cap, got "
        f"{computed['credential_compliance_pct']}"
    )


# --- observation composite and reliability -----------------------------------


def _enter(api, visit_id, observer_id, per_subscale, codes):
    """Submit one score row per code under one observer, returning the last row."""
    row = None
    for code in codes:
        row = validate_success(
            api.submit_score(
                visit_id,
                score_payload(code, per_subscale[code]),
                make_observer_headers(observer_id),
            ),
            201,
        )
    return row


def test_composite_rounds_only_the_quotient_and_never_the_subscales(api):
    """PRD §3.4: "Otherwise the six raw scores are added together without any intermediate
    rounding, the sum is divided by six, and only that quotient is rounded half up to two
    decimal places. Rounding the individual subscale values first is forbidden."
    PRD §3.4: "Once the lead observer holds a current row for all six subscale codes the
    visit advances `IN_PROGRESS → SCORES_ENTERED` and the visit's `composite` is computed."
    PRD §3.4: "The first attempt for a combination carries `attempt_no` 1."

    Design: Corner/calculations/composite_rounds_only_the_quotient_to_5_08
    """
    ctx = build_rating_spine(stop_at="OBSERVATION_SCHEDULED")
    set_clock("2026-08-06T09:00:00Z")
    scores = {
        "SPACE_FURNISHINGS": 5.0,
        "PERSONAL_CARE": 5.0,
        "LANGUAGE_REASONING": 5.0,
        "ACTIVITIES": 5.5,
        "INTERACTION": 5.0,
        "PROGRAM_STRUCTURE": 5.0,
    }
    _enter(api, ctx["visit"]["id"], ctx["lead"]["id"], scores, SUBSCALE_CODES[:5])
    last = _enter(api, ctx["visit"]["id"], ctx["lead"]["id"], scores, SUBSCALE_CODES[5:])
    assert last["attempt_no"] == 1
    assert last["is_current"] is True

    visit = validate_success(api.get_observation_visit(ctx["visit"]["id"], ADMIN))
    assert visit["status"] == "SCORES_ENTERED"
    assert visit["composite"] == pytest.approx(5.08, abs=0.005), (
        "the six raw scores sum to 30.5 and 30.5 divided by six rounds half up to 5.08; "
        "rounding the sum or the subscales first would give 5.17, got "
        f"{visit['composite']}"
    )
    assert visit["composite"] != pytest.approx(5.17, abs=0.005), (
        "5.17 is the forbidden result of rounding before dividing"
    )
    assert visit["reliability_pct"] is None, (
        "a single-observer visit has no reliability percentage at SCORES_ENTERED"
    )
    assert visit["rescore_count"] == 0

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_SCHEDULED", (
        "score entry drives the visit only; the cycle waits for finalization"
    )
    assert cycle["observation_composite"] is None, (
        "the composite reaches the cycle only when the visit is finalized"
    )


def test_reliability_of_exactly_83_33_is_admissible(api):
    """PRD §3.4: "For each of the six subscale codes the system compares the lead observer's
    current raw score with the secondary observer's current raw score and counts the
    subscale as matched when the absolute difference between the two is no greater than 1.0."
    PRD §3.4: "The reliability percentage is one hundred multiplied by the matched count,
    divided by six, and rounded half up to two decimal places."
    PRD §3.4: "Scores are admissible when that percentage is at least 83.33 — the
    comparison is inclusive."
    PRD §3.4: "Five matched subscales produce exactly 83.33 and therefore pass; four
    matched subscales produce 66.67 and fail."
    PRD §3.4: "It stamps `finalized_on` from the logical clock, keeps the computed
    `reliability_pct` on the visit, propagates both the composite and the reliability
    percentage onto the parent cycle as `observation_composite` and `reliability_pct`,
    advances the cycle `OBSERVATION_SCHEDULED → OBSERVATION_FINALIZED`, and reruns the
    per-domain points award under the final variant."

    Design: Corner/calculations/reliability_83_33_is_admissible_at_the_inclusive_boundary
    """
    ctx = build_rating_spine(stop_at="SCORES_ENTERED", with_secondary=True, raw_score=5.0)
    secondary = {
        # An absolute difference of exactly 1.0 still counts as matched.
        "SPACE_FURNISHINGS": 6.0,
        "PERSONAL_CARE": 5.0,
        "LANGUAGE_REASONING": 5.0,
        "ACTIVITIES": 5.0,
        "INTERACTION": 5.0,
        # A difference of 1.5 is the single unmatched subscale.
        "PROGRAM_STRUCTURE": 3.5,
    }
    _enter(api, ctx["visit"]["id"], ctx["secondary"]["id"], secondary, SUBSCALE_CODES)

    visit = validate_success(api.get_observation_visit(ctx["visit"]["id"], ADMIN))
    assert visit["status"] == "RELIABILITY_CHECK"
    assert visit["reliability_pct"] == pytest.approx(83.33, abs=0.005), (
        "five of six matched subscales is 83.33 after rounding half up, got "
        f"{visit['reliability_pct']}"
    )
    assert visit["composite"] == pytest.approx(5.00, abs=0.005), (
        "the composite is the lead observer's average alone and ignores the secondary rows"
    )

    finalized = validate_success(api.finalize_visit(ctx["visit"]["id"], ADMIN))
    assert finalized["status"] == "FINALIZED", (
        "83.33 sits on the inclusive side of the admissibility threshold"
    )
    assert finalized["reliability_pct"] == pytest.approx(83.33, abs=0.005)

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_FINALIZED"
    assert cycle["observation_composite"] == pytest.approx(5.00, abs=0.005)
    assert cycle["reliability_pct"] == pytest.approx(83.33, abs=0.005)

    rows, meta = validate_paginated(
        api.list_observation_scores(
            ADMIN, params={"observation_visit_id": ctx["visit"]["id"]}
        )
    )
    assert meta["total_count"] == 12, (
        f"six first-attempt rows per observer across two observers, got {meta['total_count']}"
    )
    assert all(row["is_current"] is True for row in rows), (
        "no rescore happened, so every stored row is still the current one"
    )


def test_reliability_of_66_67_is_below_the_threshold(api):
    """PRD §3.4: "For each of the six subscale codes the system compares the lead observer's
    current raw score with the secondary observer's current raw score and counts the
    subscale as matched when the absolute difference between the two is no greater than 1.0."
    PRD §3.4: "Five matched subscales produce exactly 83.33 and therefore pass; four matched
    subscales produce 66.67 and fail."
    PRD §3.4: "It requires the visit's `reliability_pct` to be at least 83.33, and it
    requires both named observers to be in `RELIABLE` standing with certification covering
    the visit's `window_start` date."

    Design: Corner/calculations/reliability_83_33_is_admissible_at_the_inclusive_boundary
    """
    ctx = build_rating_spine(stop_at="SCORES_ENTERED", with_secondary=True, raw_score=5.0)
    secondary = {
        "SPACE_FURNISHINGS": 6.0,
        "PERSONAL_CARE": 5.0,
        "LANGUAGE_REASONING": 5.0,
        "ACTIVITIES": 5.0,
        # Two subscales now differ by more than 1.0.
        "INTERACTION": 3.0,
        "PROGRAM_STRUCTURE": 3.5,
    }
    _enter(api, ctx["visit"]["id"], ctx["secondary"]["id"], secondary, SUBSCALE_CODES)

    visit = validate_success(api.get_observation_visit(ctx["visit"]["id"], ADMIN))
    assert visit["reliability_pct"] == pytest.approx(66.67, abs=0.005), (
        f"four of six matched subscales is 66.67, got {visit['reliability_pct']}"
    )
    validate_error(
        api.finalize_visit(ctx["visit"]["id"], ADMIN),
        "ERR_RELIABILITY_BELOW_THRESHOLD",
        422,
    )


# --- weighted total, tier cutoffs and the block fold -------------------------


def test_weighted_total_of_exactly_seventy_is_tier_four_with_a_36_month_window(api):
    """PRD §3.5: "From that total alone comes `points_tier`: 5 when the weighted total is
    at least 85.00, 4 when it is at least 70.00, 3 when it is at least 55.00, 2 when it is
    at least 40.00, and 1 otherwise. Every one of those comparisons is inclusive, so a
    weighted total of exactly 70.00 is tier 4 while 69.99 is tier 3."
    PRD §3.5: "`validity_months` is 36 when `awarded_tier` is at least 4 and 24 otherwise."
    PRD §3.5: "On a fresh award the `effective_date` is the first day of the month after
    the award date at midnight UTC with three fractional digits of zero."
    PRD §3.5: "The `expires_on` instant is the `effective_date` advanced by that many
    calendar months and then pulled back by one day, at 23:59:59.999 UTC; because the
    effective date is always the first day of a month, month addition never needs day
    clamping."
    PRD §3.5: "`rerating_window_opens_on` is the expiry date minus 90 calendar days at
    midnight UTC — the earliest date on which a re-rating cycle may be opened."

    Design: Corner/calculations/weighted_total_exactly_seventy_awards_tier_four_and_36_months
    """
    ctx = build_rating_spine(
        stop_at="AWARDED",
        claimed=TIER_FOUR_POINTS,
        verified=TIER_FOUR_POINTS,
        raw_score=5.0,
        with_secondary=True,
        award_clock="2026-08-11T00:00:00Z",
    )
    cycle = ctx["cycle"]
    assert cycle["observation_composite"] == pytest.approx(5.00, abs=0.005)
    assert cycle["domain_points"] == {
        "LEARNING_ENVIRONMENT": 16,
        "STAFF_QUALIFICATIONS": 12,
        "FAMILY_PARTNERSHIP": 10,
        "ADMINISTRATION": 16,
        "CHILD_ASSESSMENT": 16,
    }, f"unexpected domain_points {cycle['domain_points']}"
    assert cycle["weighted_total"] == pytest.approx(70.00, abs=0.005), (
        "24.00 + 12.00 + 10.00 + 12.00 + 12.00 is exactly 70.00, got "
        f"{cycle['weighted_total']}"
    )
    assert cycle["points_tier"] == 4, (
        "the tier-4 cutoff of 70.00 is inclusive, so exactly 70.00 must not fall to tier 3"
    )
    assert cycle["block_clearance"] == {"1": "CLEARED", "2": "CLEARED", "3": "CLEARED"}
    assert cycle["highest_block_cleared"] == 3
    assert cycle["awarded_tier"] == 4, (
        "the all-blocks ceiling of 5 leaves points_tier 4 as the smaller value"
    )
    assert cycle["validity_months"] == 36, (
        f"awarded_tier 4 carries a 36-month window, got {cycle['validity_months']}"
    )
    assert cycle["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert cycle["expires_on"] == "2029-08-31T23:59:59.999Z", (
        "2026-09-01 plus 36 months pulled back one day is 2029-08-31, got "
        f"{cycle['expires_on']}"
    )
    assert cycle["rerating_window_opens_on"] == "2029-06-02T00:00:00.000Z", (
        "2029-08-31 minus 90 calendar days is 2029-06-02, got "
        f"{cycle['rerating_window_opens_on']}"
    )
    assert cycle["status"] == "AWARDED"
    assert cycle["score_variant"] == "FINAL"
    assert cycle["awarded_on"] == "2026-08-11T00:00:00.000Z"


def test_a_cleared_block_three_cannot_rescue_a_failed_block_two(api):
    """PRD §3.5: "The blocks are then folded sequentially: `highest_block_cleared` is 0 when
    block 1 is `NOT_CLEARED`, and otherwise the largest number K from 1 to 3 such that
    blocks 1 through K are all `CLEARED`. Clearing block 3 while block 2 remains
    `NOT_CLEARED` therefore still leaves `highest_block_cleared` at 1."
    PRD §3.5: "Each level of block clearance implies a tier ceiling: clearing no blocks caps
    the rating at tier 1, clearing block 1 caps it at tier 2, clearing blocks 1 and 2 caps
    it at tier 4, and clearing all three permits tier 5. The `awarded_tier` is the smaller
    of `points_tier` and that ceiling — which is how a provider with an excellent weighted
    score can still be held at tier 2 because it never cleared its second block."
    PRD §3.5: "`validity_months` is 36 when `awarded_tier` is at least 4 and 24 otherwise."

    Design: Corner/calculations/block_folding_is_sequential_so_block_three_cannot_rescue_tier
    """
    ctx = build_rating_spine(
        stop_at="AWARDED",
        claimed=BLOCK_GAP_POINTS,
        verified=BLOCK_GAP_POINTS,
        raw_score=6.0,
        with_secondary=True,
        award_clock="2026-08-11T00:00:00Z",
    )
    cycle = ctx["cycle"]
    assert cycle["weighted_total"] == pytest.approx(84.00, abs=0.005), (
        "30.00 + 20.00 + 4.00 + 15.00 + 15.00 is 84.00, got "
        f"{cycle['weighted_total']}"
    )
    assert cycle["points_tier"] == 4
    assert cycle["block_clearance"] == {
        "1": "CLEARED",
        "2": "NOT_CLEARED",
        "3": "CLEARED",
    }, (
        "FAMILY_PARTNERSHIP is 4 points against a block_min_points of 10, so only block 2 "
        f"fails, got {cycle['block_clearance']}"
    )
    assert cycle["highest_block_cleared"] == 1, (
        "the fold stops at the first gap, so a cleared block 3 is not counted, got "
        f"{cycle['highest_block_cleared']}"
    )
    assert cycle["awarded_tier"] == 2, (
        "a highest_block_cleared of 1 caps the award at tier 2 despite a tier-4 points "
        f"score, got {cycle['awarded_tier']}"
    )
    assert cycle["validity_months"] == 24, (
        f"an awarded_tier below 4 carries a 24-month window, got {cycle['validity_months']}"
    )
    assert cycle["expires_on"] == "2028-08-31T23:59:59.999Z", (
        "2026-09-01 plus 24 months pulled back one day is 2028-08-31, got "
        f"{cycle['expires_on']}"
    )
    assert cycle["rerating_window_opens_on"] == "2028-06-02T00:00:00.000Z"


# --- coaching administrative fee band boundary -------------------------------


def test_a_base_cost_one_cent_over_the_band_edge_costs_less_in_total(api):
    """PRD §3.9: "First, `base_hours_cost_cents` is the `allocated_hours` multiplied by the
    `hourly_rate_cents`, rounded half up to whole cents. Second, `admin_fee_cents` is that
    base cost multiplied by an administrative fee rate and rounded half up to whole cents,
    where the rate is 0.12 when the base cost is below 50,000 cents, 0.09 when the base
    cost is below 200,000 cents, and 0.06 otherwise; both breakpoints are strict on their
    upper bound, so a base cost of exactly 50,000 cents falls in the 0.09 band while 49,999
    cents falls in the 0.12 band."
    PRD §3.9: "Third, `total_cost_cents` is the base cost plus the administrative fee."
    PRD §3.9: "The allocation's `spend_cap_cents` is the smaller of the tier spend ceiling
    and that funding balance, and `total_cost_cents` above `spend_cap_cents` is refused with
    `ERR_COACHING_SPEND_CAP_EXCEEDED` and HTTP 422."

    Design: Corner/calculations/admin_fee_band_boundary_makes_a_larger_base_cost_less
    """
    ctx = setup_tier_one_active_spine()
    provider_id = ctx["provider"]["id"]
    provider = validate_success(api.get_provider(provider_id, ADMIN))
    assert provider["current_tier"] == 1

    below = validate_success(
        api.create_coaching_allocation(
            provider_id,
            create_coaching_allocation_payload(
                COACH_USER_ID,
                funding_source="STATE_BASE",
                funding_grant_id=None,
                period_start="2026-09-01",
                period_end="2026-12-31",
                allocated_hours=10.0,
                hourly_rate_cents=4999,
            ),
            ADMIN,
        ),
        201,
    )
    assert below["base_hours_cost_cents"] == 49990
    assert below["admin_fee_cents"] == 5999, (
        "49,990 cents is still below the first breakpoint, so 0.12 applies and 5998.8 "
        f"rounds half up to 5999, got {below['admin_fee_cents']}"
    )
    assert below["total_cost_cents"] == 55989

    at_edge = validate_success(
        api.create_coaching_allocation(
            provider_id,
            create_coaching_allocation_payload(
                COACH_USER_ID,
                funding_source="STATE_BASE",
                funding_grant_id=None,
                period_start="2026-09-01",
                period_end="2026-12-31",
                allocated_hours=10.0,
                hourly_rate_cents=5000,
            ),
            ADMIN,
        ),
        201,
    )
    assert at_edge["base_hours_cost_cents"] == 50000
    assert at_edge["admin_fee_cents"] == 4500, (
        "a base cost of exactly 50,000 cents sits in the 0.09 band, got "
        f"{at_edge['admin_fee_cents']}"
    )
    assert at_edge["total_cost_cents"] == 54500
    assert at_edge["total_cost_cents"] < below["total_cost_cents"], (
        "the strict breakpoint makes the larger base cost cheaper overall: 54500 against "
        f"55989, got {at_edge['total_cost_cents']} against {below['total_cost_cents']}"
    )

    assert below["spend_cap_cents"] == 500000, (
        "the tier-1 spend ceiling of 900000 is bounded by the flat 500000 state base "
        f"funding balance, got {below['spend_cap_cents']}"
    )
    assert at_edge["spend_cap_cents"] == 500000
    assert at_edge["status"] == "PROPOSED"
    assert float(at_edge["scheduled_hours"]) == pytest.approx(0.0, abs=0.05)
    assert float(at_edge["delivered_hours"]) == pytest.approx(0.0, abs=0.05)
    assert float(at_edge["remaining_hours"]) == pytest.approx(10.0, abs=0.05)


# --- subsidy reimbursement rounding ------------------------------------------


def test_subsidy_rounds_each_age_band_before_summing_the_three(api):
    """PRD §3.7: "each age band's subsidised child-days are multiplied by that band's base
    daily rate — 4,500 cents per infant day, 3,800 cents per toddler day, and 3,200 cents
    per preschool day — and the three products are added to give `base_amount_cents`."
    PRD §3.7: "For each of the three bands the system multiplies that band's child-days by
    that band's base daily rate, by `tier_multiplier_applied`, and by the provider's region
    factor, and rounds the product half up to whole cents. The three rounded band amounts
    are added together to give `reimbursement_cents`, and that sum is never rounded again."
    PRD §3.7: "A tier maps to a multiplier: tier 1 pays at 1.00, tier 2 at 1.05, tier 3 at
    1.15, tier 4 at 1.30, and tier 5 at 1.50. The provider's `region_code` supplies a second
    factor: 1.00 for `URBAN`, 1.08 for `RURAL`, and 1.15 for `FRONTIER`."
    PRD §3.7: "Under the **interim** variant a single multiplier is used for the whole
    month, taken from the tier in force on the first calendar day of the service month, so a
    mid-month tier change is ignored; that value is rounded half up to four decimal places
    and stored as `tier_multiplier_applied`."

    Design: Corner/calculations/subsidy_interim_rounds_each_age_band_before_summing
    """
    ctx = build_rating_spine(
        stop_at="PUBLISHED",
        provider_overrides={
            "legal_name": "Prairie Rural Child Care",
            "county_code": "GRN",
            "region_code": "RURAL",
            "licensed_capacity": 55,
            "active_staff_fte": 1.00,
        },
        claimed=TIER_FOUR_POINTS,
        verified=TIER_FOUR_POINTS,
        raw_score=5.0,
        with_secondary=True,
        award_clock="2026-08-11T00:00:00Z",
        activation_clock="2026-09-01T00:00:00Z",
    )
    assert ctx["cycle"]["awarded_tier"] == 4
    assert ctx["cycle"]["status"] == "ACTIVE"
    assert ctx["cycle"]["effective_date"] == "2026-09-01T00:00:00.000Z"

    claim = submit_claim(ctx["provider"]["id"], "2026-09", infant=7, toddler=3, preschool=2)
    assert claim["base_amount_cents"] == 49300, (
        "7 infant days at 4500, 3 toddler days at 3800 and 2 preschool days at 3200 is "
        f"49300, got {claim['base_amount_cents']}"
    )

    approved = validate_success(
        api.adjudicate_claim(claim["id"], {"decision": "APPROVE", "variant": "INTERIM"}, ADMIN)
    )
    assert approved["variant_applied"] == "INTERIM"
    assert approved["tier_multiplier_applied"] == pytest.approx(1.3000, abs=0.00005), (
        "the tier in force on 2026-09-01 is 4, whose multiplier is 1.30, got "
        f"{approved['tier_multiplier_applied']}"
    )
    assert approved["reimbursement_cents"] == 69218, (
        "the bands round to 44226, 16006 and 8986 before they are added, giving 69218, got "
        f"{approved['reimbursement_cents']}"
    )
    assert approved["reimbursement_cents"] != 69217, (
        "69217 is the result of rounding the 69217.2 total once at the end instead of "
        "rounding each band"
    )
