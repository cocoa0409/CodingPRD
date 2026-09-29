"""
The refusal edge cases of the Loyalty Liability & Breakage Accounting API.

Each test here drives one guard to the exact instant it is supposed to bite —
the request that is allowed through so that allocation can refuse it, the
multiplier one basis point over the cap, the band that misses the measured rate
by one basis point, the code that repeats inside one programme but is free in
another, the window whose two ends coincide — and then reads the ledger back to
show that a refusal moved nothing at all.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_error,
    assert_fields,
    assert_lot_split,
    assert_ok,
    assert_page,
    assert_statement_net,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AGREEMENT_SUSPENDED,
    BASIS_GROSS,
    CLOCK_EPOCH,
    ESTIMATE_DRAFT,
    LOT_FULLY_REDEEMED,
    LOT_OUTSTANDING,
    MEMBER_ACTIVE,
    METHOD_COHORT_WEIGHTED,
    PERIOD_AUG_CODE,
    PERIOD_AUG_END,
    PERIOD_AUG_START,
    PERIOD_OPEN,
    PERIOD_SEP_CODE,
    PERIOD_SEP_END,
    PERIOD_SEP_START,
    REDEMPTION_ALLOCATED,
    REDEMPTION_REQUESTED,
    SETTLEMENT_NOT_APPLICABLE,
    SETTLEMENT_PENDING,
    SETTLEMENT_WRITTEN_OFF,
    STATE_DE,
    STATE_TX,
    STATEMENT_WRITTEN_OFF,
    TIER_BASE,
    TIER_GOLD,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)

# ─── The reference programme, priced at 1200 millicents a point ───────────────
# A first activation seeds the live breakage rate at 10000 basis points less the
# programme's historical redemption rate of 7500, so every lot issued below
# snapshots 2500 basis points.
SEEDED_BREAKAGE_RATE_BP = 2500

# One thousand base points to a BASE member: the tier multiplier is exactly
# 10000 basis points and the promotional multiplier defaults to 10000, so both
# uplift steps are identities and the lot carries 1000 points.
LOT_BASE_POINTS = 1000
LOT_POINTS_ISSUED = 1000
LOT_GROSS_CENTS = 1200
LOT_RESERVE_CENTS = 300
LOT_DEFERRED_CENTS = 900

# A request for half again as many points as the member holds.
OVERDRAWN_POINTS_REQUESTED = 1500

# The single cohort every helper builds unless a test asks for another.
C1_SPEC = dict(
    observed_redemption_rate_bp=8200,
    program_change_adjustment_bp=0,
    enrollment_start_date="2024-01-01T00:00:00Z",
    enrollment_end_date="2024-12-31T00:00:00Z",
)


def _activated_program(
    api, cohort_specs=None, clock=CLOCK_EPOCH, rule_overrides=None, **program_overrides
):
    """
    A programme carrying one state expiry rule and its cohorts, then activated.

    Activation is refused unless the programme already holds at least one state
    expiry rule and at least one cohort, so both are created first.
    """
    fixtures.set_clock(api, clock)
    program = fixtures.new_program(api, **program_overrides)
    fixtures.new_state_expiry_rule(api, program["id"], **(rule_overrides or {}))
    cohorts = [
        fixtures.new_cohort(api, program["id"], **spec)
        for spec in (cohort_specs if cohort_specs is not None else [dict(C1_SPEC)])
    ]
    program = fixtures.activate(api, program["id"])
    return program, cohorts


def _member_with_one_lot(api, base_points=LOT_BASE_POINTS, **program_overrides):
    """One BASE member of an active programme holding a single lot in an open period."""
    program, cohorts = _activated_program(api, **program_overrides)
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"])
    period = fixtures.new_period(api, program["id"])
    lot = fixtures.issue_lot(api, member["id"], period["id"], base_points)
    return {
        "program": program,
        "cohort": cohorts[0],
        "member": member,
        "period": period,
        "lot": lot,
    }


def test_overdrawn_request_is_accepted_and_only_allocation_refuses(api):
    """
    A request for more points than the member holds is not the request's problem.
    The balance test belongs to allocation, so the event is created in REQUESTED
    with all four of its monetary figures still at 0, and it is the allocation
    that returns ERR_INSUFFICIENT_POINT_BALANCE. Nothing moves: the event stays
    REQUESTED, the lot keeps every point, its journal is empty and the period has
    recognised no redemption.

    "**Member balance sufficient** — `ERR_INSUFFICIENT_POINT_BALANCE` (409), on redemption allocation."
    "The new **RedemptionEvent** is born in `state` `REQUESTED` with `requested_at` set to the clock reading, `allocated_at` null, `reversal_reason` null, and its four monetary figures — `provisional_release_cents`, `final_release_cents`, `remeasurement_delta_cents` and `partner_cost_cents` — all at 0."
    "No revenue is released by the request itself."
    "It requires the event to be `REQUESTED`, the member's programme to be `ACTIVE`, the event's period to be `OPEN`, and the member's outstanding balance to be sufficient: the sum of `points_remaining` over the member's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` must be at least `points_requested`, and a strictly smaller balance is rejected with `ERR_INSUFFICIENT_POINT_BALANCE`."

    Design: Corner/validations/valid_aggregate_balance_tested_at_allocate_not_at_request
    """
    bundle = _member_with_one_lot(api)

    event = fixtures.request_redemption(
        api,
        bundle["member"]["id"],
        bundle["period"]["id"],
        OVERDRAWN_POINTS_REQUESTED,
    )
    assert_fields(
        event,
        state=REDEMPTION_REQUESTED,
        points_requested=OVERDRAWN_POINTS_REQUESTED,
        provisional_release_cents=0,
        final_release_cents=0,
        remeasurement_delta_cents=0,
        partner_cost_cents=0,
        allocated_at=None,
    )

    assert_error(
        api.allocate_redemption(event["id"], None, ACCOUNTANT_HEADERS),
        ApiErrorId.INSUFFICIENT_POINT_BALANCE,
    )

    refused = assert_ok(api.get_redemption(event["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        refused,
        state=REDEMPTION_REQUESTED,
        provisional_release_cents=0,
        allocated_at=None,
    )

    lot = assert_ok(api.get_point_lot(bundle["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        lifecycle_state=LOT_OUTSTANDING,
        points_remaining=LOT_POINTS_ISSUED,
    )
    assert_page(
        api.list_lot_allocations(bundle["lot"]["id"], ACCOUNTANT_HEADERS),
        expected_ids=[],
        total_count=0,
    )

    period = assert_ok(api.get_period(bundle["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(period, redemption_recognized_cents=0)


def test_allocation_succeeds_when_the_balance_exactly_covers_the_request(api):
    """
    The balance comparison is inclusive, so a request for exactly the points the
    member holds allocates. The single line's gross is deducted by that one lot's
    own frozen breakage rate, giving a provisional release of 900 cents on a 1200
    cent line, the lot is driven straight to FULLY_REDEEMED with nothing left, and
    the release lands on the period's redemption accumulator.

    "It requires the event to be `REQUESTED`, the member's programme to be `ACTIVE`, the event's period to be `OPEN`, and the member's outstanding balance to be sufficient: the sum of `points_remaining` over the member's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` must be at least `points_requested`, and a strictly smaller balance is rejected with `ERR_INSUFFICIENT_POINT_BALANCE`."
    "It also records `provisional_release_cents` for the line: the line's gross less the reserve on that line, where the reserve is the line gross multiplied by **that lot's own** `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "A lot that was `OUTSTANDING` and gives up exactly its `points_remaining` moves `OUTSTANDING → FULLY_REDEEMED`, with `points_remaining` set to 0, one `ALLOCATION` row appended, and its `version` incremented by 1."
    "The event's `provisional_release_cents` is added to the period's `redemption_recognized_cents`."

    Design: Corner/validations/valid_aggregate_balance_tested_at_allocate_not_at_request
    """
    bundle = _member_with_one_lot(api)

    event = fixtures.allocated_redemption(
        api, bundle["member"]["id"], bundle["period"]["id"], LOT_POINTS_ISSUED
    )
    assert_fields(
        event,
        state=REDEMPTION_ALLOCATED,
        points_requested=LOT_POINTS_ISSUED,
        provisional_release_cents=LOT_DEFERRED_CENTS,
        partner_cost_cents=0,
    )

    lot = assert_ok(api.get_point_lot(bundle["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        lifecycle_state=LOT_FULLY_REDEEMED,
        points_remaining=0,
    )

    rows = assert_page(
        api.list_lot_allocations(bundle["lot"]["id"], ACCOUNTANT_HEADERS),
        total_count=1,
    )
    assert_fields(
        rows[0],
        points_allocated=LOT_POINTS_ISSUED,
        line_gross_ssp_cents=LOT_GROSS_CENTS,
        provisional_release_cents=LOT_DEFERRED_CENTS,
    )

    period = assert_ok(api.get_period(bundle["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(period, redemption_recognized_cents=LOT_DEFERRED_CENTS)


# ─── The promotional multiplier and its cap ───────────────────────────────────
PROMO_CAP_BP = 30000
PROMO_ONE_ABOVE_CAP_BP = 30001

# One hundred base points to a BASE member at the cap: the tier step is an
# identity, then 100 × 30000 ÷ 10000 = 300 points exactly.
PROMO_BASE_POINTS = 100
PROMO_TIER_POINTS = 100
PROMO_POINTS_ISSUED = 300
PROMO_GROSS_CENTS = 360
PROMO_RESERVE_CENTS = 90
PROMO_DEFERRED_CENTS = 270
PROMO_TIER_EXPENSE_CENTS = 0
PROMO_EXPENSE_CENTS = 240


def test_promotional_multiplier_one_point_above_the_cap_is_refused(api):
    """
    The programme's promotional cap defaults to 30000 basis points and the
    comparison is strict, so a multiplier of 30001 is refused. The refusal is
    total: no lot exists for the member afterwards and the period has deferred
    nothing.

    "Promotional generosity is capped separately by `promo_multiplier_cap_bp`, which defaults to 30000 and is accepted from 10000 through 100000 inclusive."
    "A promotional multiplier above the programme's `promo_multiplier_cap_bp` is rejected with `ERR_PROMO_MULTIPLIER_ABOVE_CAP`."
    "**Promotional multiplier within the programme cap** — `ERR_PROMO_MULTIPLIER_ABOVE_CAP` (409), on point-lot issuance."

    Design: Corner/validations/valid_conditional_promo_multiplier_above_program_cap_rejected
    """
    program, cohorts = _activated_program(api, promo_multiplier_cap_bp=PROMO_CAP_BP)
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"])
    period = fixtures.new_period(api, program["id"])

    assert_error(
        api.create_point_lot(
            factories.point_lot_payload(
                member["id"],
                period["id"],
                PROMO_BASE_POINTS,
                promo_multiplier_bp=PROMO_ONE_ABOVE_CAP_BP,
            ),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.PROMO_MULTIPLIER_ABOVE_CAP,
    )

    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, member_id=member["id"]),
        expected_ids=[],
        total_count=0,
    )
    assert_fields(
        assert_ok(api.get_period(period["id"], CONTROLLER_HEADERS)),
        issuance_deferred_cents=0,
    )


def test_promotional_multiplier_exactly_at_the_cap_is_expensed_in_full(api):
    """
    Only a multiplier above the cap is refused, so one exactly at 30000 basis
    points is issued. The promotional step consumes the already-rounded tier
    points, giving 300 points and 360 cents of gross; the two uplifts are then
    expensed on their own point deltas, so the tier leg is 0 for a BASE member
    while the promotional leg carries the whole 200-point uplift at 240 cents.
    Only the deferral, never the gross, reaches the period.

    "A promotional multiplier above the programme's `promo_multiplier_cap_bp` is rejected with `ERR_PROMO_MULTIPLIER_ABOVE_CAP`."
    "`points_issued` is the **already-rounded** `tier_points` multiplied by `promo_multiplier_bp`, divided by 10000, and rounded half up again."
    "`gross_ssp_cents` is `points_issued` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`breakage_reserve_cents` is `gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."
    "`tier_benefit_expense_cents` is the difference between `tier_points` and `base_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up — and is therefore 0 for a `BASE` member."
    "`promo_expense_cents` is the difference between `points_issued` and `tier_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."

    Design: Corner/validations/valid_conditional_promo_multiplier_above_program_cap_rejected
    """
    program, cohorts = _activated_program(api, promo_multiplier_cap_bp=PROMO_CAP_BP)
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"])
    period = fixtures.new_period(api, program["id"])

    lot = fixtures.issue_lot(
        api,
        member["id"],
        period["id"],
        PROMO_BASE_POINTS,
        promo_multiplier_bp=PROMO_CAP_BP,
    )
    assert_fields(
        lot,
        tier_points=PROMO_TIER_POINTS,
        points_issued=PROMO_POINTS_ISSUED,
        points_remaining=PROMO_POINTS_ISSUED,
        gross_ssp_cents=PROMO_GROSS_CENTS,
        breakage_reserve_cents=PROMO_RESERVE_CENTS,
        deferred_revenue_cents=PROMO_DEFERRED_CENTS,
        tier_benefit_expense_cents=PROMO_TIER_EXPENSE_CENTS,
        promo_expense_cents=PROMO_EXPENSE_CENTS,
        breakage_rate_bp_at_issue=SEEDED_BREAKAGE_RATE_BP,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_NOT_APPLICABLE,
    )
    assert_lot_split(lot)

    assert_fields(
        assert_ok(api.get_period(period["id"], CONTROLLER_HEADERS)),
        issuance_deferred_cents=PROMO_DEFERRED_CENTS,
    )


# ─── The sensitivity band and the measured rate ───────────────────────────────
# One cohort observed at 8200 basis points with no behavioural adjustment, and a
# single 1000-point lot priced at 1200 millicents a point: the weighted mean
# collapses onto 8200 and the frozen gross is 1200 cents.
MEASURED_RATE_BP = 8200
MEASURED_BREAKAGE_RATE_BP = 1800
ESTIMATE_OUTSTANDING_POINTS = 1000
ESTIMATE_GROSS_CENTS = 1200

# 1200 × 8200 ÷ 10000 = 984 exactly, so all three collapsed band legs agree.
ESTIMATE_REQUIRED_CENTS = 984

BAND_WHOLLY_ABOVE_LOW_BP = 8300
BAND_WHOLLY_ABOVE_HIGH_BP = 8700
BAND_WHOLLY_BELOW_LOW_BP = 7700
BAND_WHOLLY_BELOW_HIGH_BP = 8100

ESTIMATE_MEMO = "Single vintage measured against its own outstanding balance."


def _one_cohort_estimate_fixture(api):
    """An active single-cohort programme whose only lot fixes the measured rate at 8200."""
    return _member_with_one_lot(api)


def test_band_wholly_above_the_measured_rate_is_refused(api):
    """
    The low leg must be no greater than the measured rate. A band running from
    8300 to 8700 basis points sits entirely above the measured 8200, so it fails
    to straddle it and the create is refused with no estimate left behind.

    "Once the rate is known, the sensitivity band is checked: `sensitivity_low_bp` must be no greater than the measured `estimated_redemption_rate_bp`, and `sensitivity_high_bp` must be no less than it."
    "A band that fails to straddle the measured rate is rejected with `ERR_SENSITIVITY_BAND_INVALID`."
    "**Sensitivity band straddles the measured rate** — `ERR_SENSITIVITY_BAND_INVALID` (409), on breakage-estimate create."

    Design: Corner/validations/valid_sensitivity_band_must_straddle_the_measured_rate
    """
    bundle = _one_cohort_estimate_fixture(api)

    assert_error(
        api.create_estimate(
            bundle["program"]["id"],
            factories.estimate_payload(
                bundle["period"]["id"],
                memo_narrative=ESTIMATE_MEMO,
                sensitivity_low_bp=BAND_WHOLLY_ABOVE_LOW_BP,
                sensitivity_high_bp=BAND_WHOLLY_ABOVE_HIGH_BP,
            ),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.SENSITIVITY_BAND_INVALID,
    )

    assert_page(
        api.list_estimates(ACCOUNTANT_HEADERS, program_id=bundle["program"]["id"]),
        expected_ids=[],
        total_count=0,
    )


def test_band_wholly_below_the_measured_rate_is_refused(api):
    """
    The high leg must be no less than the measured rate. A band running from 7700
    to 8100 basis points stops one hundred basis points short of the measured
    8200, so it too fails to straddle it and nothing is persisted.

    "Once the rate is known, the sensitivity band is checked: `sensitivity_low_bp` must be no greater than the measured `estimated_redemption_rate_bp`, and `sensitivity_high_bp` must be no less than it."
    "A band that fails to straddle the measured rate is rejected with `ERR_SENSITIVITY_BAND_INVALID`."

    Design: Corner/validations/valid_sensitivity_band_must_straddle_the_measured_rate
    """
    bundle = _one_cohort_estimate_fixture(api)

    assert_error(
        api.create_estimate(
            bundle["program"]["id"],
            factories.estimate_payload(
                bundle["period"]["id"],
                memo_narrative=ESTIMATE_MEMO,
                sensitivity_low_bp=BAND_WHOLLY_BELOW_LOW_BP,
                sensitivity_high_bp=BAND_WHOLLY_BELOW_HIGH_BP,
            ),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.SENSITIVITY_BAND_INVALID,
    )

    assert_page(
        api.list_estimates(ACCOUNTANT_HEADERS, program_id=bundle["program"]["id"]),
        expected_ids=[],
        total_count=0,
    )


def test_band_collapsed_onto_the_measured_rate_is_accepted(api):
    """
    Both comparisons are inclusive, so a band whose two legs sit exactly on the
    measured rate straddles it degenerately and is accepted. The estimate keeps
    the collapsed band, and the audit read of the frozen snapshot returns the same
    984 cents on all three legs with a band range of zero.

    "Once the rate is known, the sensitivity band is checked: `sensitivity_low_bp` must be no greater than the measured `estimated_redemption_rate_bp`, and `sensitivity_high_bp` must be no less than it."
    "`COHORT_WEIGHTED` runs when the programme's `breakage_method` is `COHORT_WEIGHTED` and the request omits `cohort_id`."
    "From the measured rate, `breakage_rate_bp` is 10000 basis points less `estimated_redemption_rate_bp`."
    "The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment."
    "The response reports that frozen gross as `outstanding_gross_ssp_cents`, echoes the three scenarios as `low_bp`, `base_bp` and `high_bp` (respectively `sensitivity_low_bp`, the measured `estimated_redemption_rate_bp`, and `sensitivity_high_bp`), and gives `low_required_liability_cents`, `base_required_liability_cents` and `high_required_liability_cents` as the frozen gross multiplied by each of those three rates in turn, divided by 10000, each rounded half up **independently** — deriving the high band by adding a rounded delta onto the rounded base drifts and is wrong."
    "`band_range_cents` is the high band less the low band, and `memo_narrative` is echoed from the estimate."

    Design: Corner/validations/valid_sensitivity_band_must_straddle_the_measured_rate
    """
    bundle = _one_cohort_estimate_fixture(api)

    estimate = fixtures.draft_estimate(
        api,
        bundle["program"]["id"],
        bundle["period"]["id"],
        memo_narrative=ESTIMATE_MEMO,
        sensitivity_low_bp=MEASURED_RATE_BP,
        sensitivity_high_bp=MEASURED_RATE_BP,
    )
    assert_fields(
        estimate,
        state=ESTIMATE_DRAFT,
        method_applied=METHOD_COHORT_WEIGHTED,
        estimated_redemption_rate_bp=MEASURED_RATE_BP,
        breakage_rate_bp=MEASURED_BREAKAGE_RATE_BP,
        outstanding_points_at_estimate=ESTIMATE_OUTSTANDING_POINTS,
        outstanding_gross_ssp_cents_at_estimate=ESTIMATE_GROSS_CENTS,
        required_liability_cents=ESTIMATE_REQUIRED_CENTS,
        sensitivity_low_bp=MEASURED_RATE_BP,
        sensitivity_high_bp=MEASURED_RATE_BP,
    )

    bands = assert_ok(api.get_sensitivity(estimate["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        bands,
        outstanding_gross_ssp_cents=ESTIMATE_GROSS_CENTS,
        low_bp=MEASURED_RATE_BP,
        base_bp=MEASURED_RATE_BP,
        high_bp=MEASURED_RATE_BP,
        low_required_liability_cents=ESTIMATE_REQUIRED_CENTS,
        base_required_liability_cents=ESTIMATE_REQUIRED_CENTS,
        high_required_liability_cents=ESTIMATE_REQUIRED_CENTS,
        band_range_cents=0,
        memo_narrative=ESTIMATE_MEMO,
    )


# ─── Codes that repeat inside one programme but are free across programmes ─────
SHARED_MEMBER_REF = "EXT-SHARED-9001"


def test_repeated_member_reference_within_one_programme_is_refused(api):
    """
    A member reference is unique inside its programme. The second enrolment under
    the same programme reusing the reference is refused, and because the refusal
    happens before anything is written the incumbent keeps the tier it was
    enrolled with rather than the GOLD the rejected attempt asked for.

    "Members are enrolled by either a `ProgramAdmin` or a `LoyaltyAccountant` into a named cohort of a named programme, supplying `program_id`, `cohort_id`, an `external_member_ref` of at most 64 non-empty characters, a `state_code` of exactly two uppercase letters giving the state of residence that selects the governing expiry rule, and a `tier` of `BASE`, `SILVER`, `GOLD` or `PLATINUM` — `BASE` when omitted."
    "The `external_member_ref` must be unique within the programme (`ERR_DUPLICATE_CODE` otherwise), and the named cohort must belong to the same programme as the one named in the body, else `ERR_COHORT_PROGRAM_MISMATCH`."
    "**Codes are unique within their programme** — `ERR_DUPLICATE_CODE` (409), on period create, cohort create, state-expiry-rule create and member enrolment."

    Design: Corner/validations/valid_duplicate_external_member_ref_scoped_to_the_program
    """
    program, cohorts = _activated_program(api)

    incumbent = fixtures.new_member(
        api,
        program["id"],
        cohorts[0]["id"],
        external_member_ref=SHARED_MEMBER_REF,
        tier=TIER_BASE,
    )

    assert_error(
        api.create_member(
            factories.member_payload(
                program["id"],
                cohorts[0]["id"],
                external_member_ref=SHARED_MEMBER_REF,
                tier=TIER_GOLD,
            ),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CODE,
    )

    assert_fields(
        assert_ok(api.get_member(incumbent["id"], ACCOUNTANT_HEADERS)),
        external_member_ref=SHARED_MEMBER_REF,
        tier=TIER_BASE,
        status=MEMBER_ACTIVE,
    )
    assert_page(
        api.list_members(ACCOUNTANT_HEADERS, program_id=program["id"]),
        expected_ids=[incumbent["id"]],
        total_count=1,
    )


def test_same_member_reference_is_free_under_another_programme(api):
    """
    The uniqueness scope is the programme, not the whole system. The very
    reference that was refused as a repeat inside one programme is accepted for a
    member of a second programme, and that member is born ACTIVE like any other.

    "The `external_member_ref` must be unique within the programme (`ERR_DUPLICATE_CODE` otherwise), and the named cohort must belong to the same programme as the one named in the body, else `ERR_COHORT_PROGRAM_MISMATCH`."
    "A new member is born with `status` `ACTIVE`, with `enrolled_at` set to the current logical clock reading, and with `last_activity_at` initialised to that same instant."

    Design: Corner/validations/valid_duplicate_external_member_ref_scoped_to_the_program
    """
    first_program, first_cohorts = _activated_program(api)
    second_program, second_cohorts = _activated_program(api)

    here = fixtures.new_member(
        api,
        first_program["id"],
        first_cohorts[0]["id"],
        external_member_ref=SHARED_MEMBER_REF,
    )
    there = fixtures.new_member(
        api,
        second_program["id"],
        second_cohorts[0]["id"],
        external_member_ref=SHARED_MEMBER_REF,
    )
    assert_fields(
        there,
        program_id=second_program["id"],
        external_member_ref=SHARED_MEMBER_REF,
        status=MEMBER_ACTIVE,
    )
    assert there["id"] != here["id"]

    assert_page(
        api.list_members(ACCOUNTANT_HEADERS, program_id=first_program["id"]),
        expected_ids=[here["id"]],
        total_count=1,
    )
    assert_page(
        api.list_members(ACCOUNTANT_HEADERS, program_id=second_program["id"]),
        expected_ids=[there["id"]],
        total_count=1,
    )


def test_repeated_state_rule_within_one_programme_is_refused(api):
    """
    The same scoping governs expiry policy: it is the pairing of programme and
    state code that must be unique. A second rule for the state the programme is
    already configured for is refused, a rule for a different state is accepted,
    and the second programme keeps its own rule for the very state code that was
    refused as a repeat in the first.

    "Expiry policy is expressed per US state as a **StateExpiryRule** attached to a programme through a `program_id` and identified by a `state_code` of exactly two uppercase letters; the combination of programme and state code must be unique, and a repeat is rejected with `ERR_DUPLICATE_CODE`."
    "**Codes are unique within their programme** — `ERR_DUPLICATE_CODE` (409), on period create, cohort create, state-expiry-rule create and member enrolment."

    Design: Corner/validations/valid_duplicate_external_member_ref_scoped_to_the_program
    """
    first_program, _ = _activated_program(api, rule_overrides={"state_code": STATE_TX})
    second_program, _ = _activated_program(api, rule_overrides={"state_code": STATE_TX})

    assert_error(
        api.create_state_expiry_rule(
            factories.state_expiry_rule_payload(
                first_program["id"], state_code=STATE_TX
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CODE,
    )
    assert_page(
        api.list_state_expiry_rules(
            PROGRAM_ADMIN_HEADERS, program_id=first_program["id"]
        ),
        total_count=1,
    )

    fixtures.new_state_expiry_rule(api, first_program["id"], state_code=STATE_DE)
    assert_page(
        api.list_state_expiry_rules(
            PROGRAM_ADMIN_HEADERS, program_id=first_program["id"]
        ),
        total_count=2,
    )
    assert_page(
        api.list_state_expiry_rules(
            PROGRAM_ADMIN_HEADERS, program_id=second_program["id"], state_code=STATE_TX
        ),
        total_count=1,
    )


# ─── A partner agreement borrowed from another programme ──────────────────────
def test_issuance_naming_another_programmes_agreement_is_refused(api):
    """
    A partner named on an issuance must be a partner of the member's own
    programme. Naming an agreement registered under a second programme is
    refused, and the refusal leaves the member with no lot and the period with
    nothing deferred.

    "When a partner is named, that agreement must belong to the same programme as the member, else `ERR_AGREEMENT_PROGRAM_MISMATCH`; the named period must likewise belong to that programme, else `ERR_PERIOD_PROGRAM_MISMATCH`."
    "**Partner agreement belongs to the same programme** — `ERR_AGREEMENT_PROGRAM_MISMATCH` (409), on point-lot issuance, redemption request and statement create."

    Design: Corner/validations/valid_agreement_from_a_different_program_rejected_on_issuance
    """
    program, cohorts = _activated_program(api)
    stranger_program, _ = _activated_program(api)
    stranger_agreement = fixtures.new_agreement(api, stranger_program["id"])

    member = fixtures.new_member(api, program["id"], cohorts[0]["id"])
    period = fixtures.new_period(api, program["id"])

    assert_error(
        api.create_point_lot(
            factories.point_lot_payload(
                member["id"],
                period["id"],
                LOT_BASE_POINTS,
                partner_agreement_id=stranger_agreement["id"],
            ),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.AGREEMENT_PROGRAM_MISMATCH,
    )

    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, member_id=member["id"]),
        expected_ids=[],
        total_count=0,
    )
    assert_fields(
        assert_ok(api.get_period(period["id"], CONTROLLER_HEADERS)),
        issuance_deferred_cents=0,
    )


def test_issuance_naming_its_own_programmes_agreement_is_booked(api):
    """
    The same issuance succeeds once the agreement named belongs to the member's
    own programme. The lot is born on both of its state dimensions at once —
    OUTSTANDING on the redemption dimension and PENDING_SETTLEMENT on the billing
    dimension — and only its 900 cent deferral, never its 1200 cent gross, reaches
    the period.

    "When a partner is named, that agreement must belong to the same programme as the member, else `ERR_AGREEMENT_PROGRAM_MISMATCH`; the named period must likewise belong to that programme, else `ERR_PERIOD_PROGRAM_MISMATCH`."
    "The partner-billing dimension, `settlement_state`, is born `NOT_APPLICABLE` when no partner was named, and is born `PENDING_SETTLEMENT` when one was — the dimension-two assignment `NOT_APPLICABLE → PENDING_SETTLEMENT` happens at creation, so a partner lot is born `PENDING_SETTLEMENT` on one dimension while being born `OUTSTANDING` on the other."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."

    Design: Corner/validations/valid_agreement_from_a_different_program_rejected_on_issuance
    """
    program, cohorts = _activated_program(api)
    agreement = fixtures.new_agreement(api, program["id"])
    assert_fields(agreement, program_id=program["id"], status=AGREEMENT_ACTIVE)

    member = fixtures.new_member(api, program["id"], cohorts[0]["id"])
    period = fixtures.new_period(api, program["id"])

    lot = fixtures.issue_lot(
        api,
        member["id"],
        period["id"],
        LOT_BASE_POINTS,
        partner_agreement_id=agreement["id"],
    )
    assert_fields(
        lot,
        partner_agreement_id=agreement["id"],
        points_issued=LOT_POINTS_ISSUED,
        gross_ssp_cents=LOT_GROSS_CENTS,
        breakage_reserve_cents=LOT_RESERVE_CENTS,
        deferred_revenue_cents=LOT_DEFERRED_CENTS,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_PENDING,
    )
    assert_lot_split(lot)

    assert_fields(
        assert_ok(api.get_period(period["id"], CONTROLLER_HEADERS)),
        issuance_deferred_cents=LOT_DEFERRED_CENTS,
    )


# ─── Windows whose two ends coincide, and windows that run backwards ───────────
INVERTED_WINDOW_START = PERIOD_SEP_START
INVERTED_WINDOW_END = PERIOD_AUG_START
AGREEMENT_LATE_INSTANT = "2026-12-31T00:00:00Z"


def test_zero_length_period_window_is_refused_and_a_positive_one_accepted(api):
    """
    A period's end must fall strictly after its start, so a window whose two ends
    are the same instant encloses nothing and is refused. The refusal writes
    nothing, and a window of positive length over the same start is then accepted
    and born OPEN with no reopen behind it.

    "The end must fall strictly after the start; a window whose start is at or after its end is rejected with `ERR_INVALID_WINDOW`."
    "**Window sanity** — `ERR_INVALID_WINDOW` (409), on period create and partner-agreement create."
    "A new period is born in `state` `OPEN`, with `reopen_count` at 0, with `soft_closed_at` null, and with all eleven of its currency and rate rollforward figures at 0: `opening_liability_cents`, `issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents`, `expiry_released_cents`, `escheat_accrual_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `breakage_recognized_cents`, `closing_liability_cents` and `approved_estimate_rate_bp`."

    Design: Corner/validations/valid_zero_length_and_inverted_period_windows_rejected
    """
    program, _ = _activated_program(api)

    assert_error(
        api.create_period(
            factories.period_payload(
                program["id"],
                period_code=PERIOD_AUG_CODE,
                start_at=PERIOD_AUG_START,
                end_at=PERIOD_AUG_START,
            ),
            CONTROLLER_HEADERS,
        ),
        ApiErrorId.INVALID_WINDOW,
    )
    assert_page(
        api.list_periods(CONTROLLER_HEADERS, program_id=program["id"]),
        expected_ids=[],
        total_count=0,
    )

    period = fixtures.new_period(
        api,
        program["id"],
        period_code=PERIOD_AUG_CODE,
        start_at=PERIOD_AUG_START,
        end_at=PERIOD_AUG_END,
    )
    assert_fields(
        period,
        state=PERIOD_OPEN,
        start_at=PERIOD_AUG_START,
        end_at=PERIOD_AUG_END,
        reopen_count=0,
        soft_closed_at=None,
    )
    assert_page(
        api.list_periods(CONTROLLER_HEADERS, program_id=program["id"]),
        expected_ids=[period["id"]],
        total_count=1,
    )


def test_inverted_period_window_is_refused(api):
    """
    A start strictly after the end is refused by the same guard that refuses a
    coincident pair, since the rule covers a start at or after the end. No period
    survives the attempt.

    "The end must fall strictly after the start; a window whose start is at or after its end is rejected with `ERR_INVALID_WINDOW`."
    "**Window sanity** — `ERR_INVALID_WINDOW` (409), on period create and partner-agreement create."

    Design: Corner/validations/valid_zero_length_and_inverted_period_windows_rejected
    """
    program, _ = _activated_program(api)

    assert_error(
        api.create_period(
            factories.period_payload(
                program["id"],
                period_code=PERIOD_SEP_CODE,
                start_at=INVERTED_WINDOW_START,
                end_at=INVERTED_WINDOW_END,
            ),
            CONTROLLER_HEADERS,
        ),
        ApiErrorId.INVALID_WINDOW,
    )
    assert_page(
        api.list_periods(CONTROLLER_HEADERS, program_id=program["id"]),
        expected_ids=[],
        total_count=0,
    )


def test_zero_length_and_inverted_agreement_windows_are_refused(api):
    """
    A partner agreement's effective window answers to the same sanity rule as a
    period's: its end must fall strictly after its start, so both a coincident
    pair and a reversed pair are refused and the programme is left with no
    agreement at all.

    "The agreement's effective window is the closed interval from `effective_start_date` through `effective_end_date`, and the end must fall strictly after the start, else `ERR_INVALID_WINDOW`."
    "**Window sanity** — `ERR_INVALID_WINDOW` (409), on period create and partner-agreement create."

    Design: Corner/validations/valid_zero_length_and_inverted_period_windows_rejected
    """
    program, _ = _activated_program(api)

    assert_error(
        api.create_agreement(
            factories.agreement_payload(
                program["id"],
                effective_start_date=PERIOD_AUG_START,
                effective_end_date=PERIOD_AUG_START,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INVALID_WINDOW,
    )
    assert_error(
        api.create_agreement(
            factories.agreement_payload(
                program["id"],
                effective_start_date=AGREEMENT_LATE_INSTANT,
                effective_end_date=PERIOD_AUG_START,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INVALID_WINDOW,
    )

    assert_page(
        api.list_agreements(PROGRAM_ADMIN_HEADERS, program_id=program["id"]),
        expected_ids=[],
        total_count=0,
    )


# ─── A written-off statement and the suspension it cascades ───────────────────
WRITE_OFF_MIN_INVOICE_CENTS = 1000

# Five thousand base points to a BASE member sits exactly on the default issuance
# cap, so the whole lot is billable: 5000 × 1200 ÷ 1000 = 6000 cents of gross,
# 1500 of reserve and 4500 deferred.
PARTNER_BASE_POINTS = 5000
PARTNER_POINTS_ISSUED = 5000
PARTNER_GROSS_CENTS = 6000
PARTNER_RESERVE_CENTS = 1500
PARTNER_DEFERRED_CENTS = 4500

# The partner lot's deferral plus the programme-issued lot's own 900 cents.
PERIOD_DEFERRED_TOTAL_CENTS = 5400

# 5000 points × 900 millicents ÷ 1000 = 4500 cents, billed whole because the
# candidate clears the 1000 cent minimum invoice under a GROSS basis.
ISSUANCE_RECEIVABLE_CENTS = 4500
STATEMENT_NET_DUE_CENTS = 4500

# The August window ends on 1 September, and thirty whole days later is 1 October.
STATEMENT_DUE_DATE = "2026-10-01T00:00:00Z"


def _written_off_statement(api):
    """
    A partner statement issued and then written off, so its agreement is suspended.

    The period carries two lots — one billable to the partner and one issued by the
    programme itself — so the cascade can be shown to touch only the partner's.
    """
    program, cohorts = _activated_program(api)
    agreement = fixtures.new_agreement(
        api, program["id"], min_invoice_cents=WRITE_OFF_MIN_INVOICE_CENTS
    )
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"])
    first_period = fixtures.new_period(
        api,
        program["id"],
        period_code=PERIOD_AUG_CODE,
        start_at=PERIOD_AUG_START,
        end_at=PERIOD_AUG_END,
    )

    partner_lot = fixtures.issue_lot(
        api,
        member["id"],
        first_period["id"],
        PARTNER_BASE_POINTS,
        partner_agreement_id=agreement["id"],
    )
    own_lot = fixtures.issue_lot(
        api, member["id"], first_period["id"], LOT_BASE_POINTS
    )

    statement = fixtures.issued_statement(api, agreement["id"], first_period["id"])
    written_off = assert_ok(
        api.write_off_statement(
            statement["id"], factories.write_off_payload(), CONTROLLER_HEADERS
        )
    )
    return {
        "program": program,
        "agreement": agreement,
        "member": member,
        "first_period": first_period,
        "partner_lot": partner_lot,
        "own_lot": own_lot,
        "statement": written_off,
    }


def test_write_off_cascades_into_the_agreement_and_its_partner_lots(api):
    """
    Writing off a statement clears the 4500 cents it had added to the agreement's
    outstanding settlement, suspends the agreement and drives the partner lot's
    billing dimension to WRITTEN_OFF. The two dimensions stay independent: that
    same lot is still OUTSTANDING with all 5000 points to its name. The
    programme-issued lot alongside it is untouched, and the period's issuance
    deferral is unchanged by the whole affair, because billing a partner and
    deferring revenue are different ledgers.

    "Issuing a statement is a `LoyaltyAccountant` action that moves it `DRAFT → ISSUED`, requires the owning agreement to be `ACTIVE`, sets `issued_at` to the clock reading, adds the statement's `net_due_cents` to the agreement's `outstanding_settlement_cents`, and increments both the agreement's and the statement's `version` by 1."
    "Write-off is available from `ISSUED → WRITTEN_OFF` and equally from `DISPUTED → WRITTEN_OFF`; both paths behave identically."
    "A write-off stores the supplied `write_off_reason`, subtracts `net_due_cents` from the agreement's `outstanding_settlement_cents`, drives every matching `PENDING_SETTLEMENT` lot of the same agreement-and-period pair to `WRITTEN_OFF` in `created_at` ascending order with each lot's `version` incremented by 1, additionally drives the owning agreement `ACTIVE → SUSPENDED` — no new statement may be created while an agreement is suspended — and increments both the agreement's and the statement's `version` by 1."
    "The independence is real and testable: an `OUTSTANDING` lot may be `SETTLED`, and a `FULLY_REDEEMED` lot may still be `PENDING_SETTLEMENT`."
    "`partner_issued_points` is the sum of `points_issued` over the matching lots, with every `lifecycle_state` included — issuance is billable the moment it happens, and a later redemption, expiry or escheatment does not un-bill it."
    "From those two counts, `issuance_receivable_cents` is `partner_issued_points` multiplied by the agreement's `issuance_rate_millicents_per_point`, divided by 1000, rounded half up, and `redemption_payable_cents` is `partner_redeemed_points` multiplied by the agreement's `redemption_rate_millicents_per_point`, divided by 1000, rounded half up."
    "Under `GROSS`, the billable candidate is `issuance_receivable_cents` plus `carried_forward_cents`."
    "`due_date` is the period's `end_at` advanced by the agreement's `settlement_lag_days` whole days."

    Design: Corner/validations/valid_cascading_write_off_suspension_blocks_the_next_statement
    """
    bundle = _written_off_statement(api)

    assert_fields(
        bundle["statement"],
        state=STATEMENT_WRITTEN_OFF,
        settlement_basis=BASIS_GROSS,
        partner_issued_points=PARTNER_POINTS_ISSUED,
        partner_redeemed_points=0,
        issuance_receivable_cents=ISSUANCE_RECEIVABLE_CENTS,
        redemption_payable_cents=0,
        carried_forward_cents=0,
        net_due_cents=STATEMENT_NET_DUE_CENTS,
        deferred_below_minimum_cents=0,
        due_date=STATEMENT_DUE_DATE,
    )
    assert_statement_net(bundle["statement"])

    agreement = assert_ok(
        api.get_agreement(bundle["agreement"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_fields(
        agreement,
        status=AGREEMENT_SUSPENDED,
        outstanding_settlement_cents=0,
        deferred_below_minimum_cents=0,
    )

    partner_lot = assert_ok(
        api.get_point_lot(bundle["partner_lot"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_fields(
        partner_lot,
        settlement_state=SETTLEMENT_WRITTEN_OFF,
        lifecycle_state=LOT_OUTSTANDING,
        points_issued=PARTNER_POINTS_ISSUED,
        points_remaining=PARTNER_POINTS_ISSUED,
        gross_ssp_cents=PARTNER_GROSS_CENTS,
        breakage_reserve_cents=PARTNER_RESERVE_CENTS,
        deferred_revenue_cents=PARTNER_DEFERRED_CENTS,
    )

    own_lot = assert_ok(api.get_point_lot(bundle["own_lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        own_lot,
        settlement_state=SETTLEMENT_NOT_APPLICABLE,
        lifecycle_state=LOT_OUTSTANDING,
        points_remaining=LOT_POINTS_ISSUED,
    )

    assert_fields(
        assert_ok(api.get_period(bundle["first_period"]["id"], CONTROLLER_HEADERS)),
        issuance_deferred_cents=PERIOD_DEFERRED_TOTAL_CENTS,
    )


def test_suspended_agreement_refuses_the_next_statement(api):
    """
    The suspension the write-off caused is what blocks the following month: the
    agreement is no longer ACTIVE, so measuring a statement for the next period
    against it is refused even though that period is open and the version carried
    is current. The written-off statement remains the agreement's only one.

    "A write-off stores the supplied `write_off_reason`, subtracts `net_due_cents` from the agreement's `outstanding_settlement_cents`, drives every matching `PENDING_SETTLEMENT` lot of the same agreement-and-period pair to `WRITTEN_OFF` in `created_at` ascending order with each lot's `version` incremented by 1, additionally drives the owning agreement `ACTIVE → SUSPENDED` — no new statement may be created while an agreement is suspended — and increments both the agreement's and the statement's `version` by 1."
    "The agreement must be `ACTIVE` — a `SUSPENDED` or `TERMINATED` agreement yields `ERR_AGREEMENT_NOT_ACTIVE` — the period must not be `HARD_CLOSED`, and the period and the agreement must belong to the same programme, else `ERR_PERIOD_PROGRAM_MISMATCH` or `ERR_AGREEMENT_PROGRAM_MISMATCH` as appropriate."
    "**Addressed agreement is `ACTIVE`** — `ERR_AGREEMENT_NOT_ACTIVE` (409), on statement create and statement issue."

    Design: Corner/validations/valid_cascading_write_off_suspension_blocks_the_next_statement
    """
    bundle = _written_off_statement(api)

    second_period = fixtures.new_period(
        api,
        bundle["program"]["id"],
        period_code=PERIOD_SEP_CODE,
        start_at=PERIOD_SEP_START,
        end_at=PERIOD_SEP_END,
    )
    assert_fields(second_period, state=PERIOD_OPEN)

    assert_error(
        api.create_statement(
            factories.statement_payload(
                bundle["agreement"]["id"],
                second_period["id"],
                fixtures.agreement_version(api, bundle["agreement"]["id"]),
            ),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.AGREEMENT_NOT_ACTIVE,
    )

    assert_page(
        api.list_statements(
            ACCOUNTANT_HEADERS, partner_agreement_id=bundle["agreement"]["id"]
        ),
        expected_ids=[bundle["statement"]["id"]],
        total_count=1,
    )
