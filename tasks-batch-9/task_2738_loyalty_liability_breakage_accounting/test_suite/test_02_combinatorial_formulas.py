"""
Three multi-factor formulas whose answer depends on the order of their steps.

Issuance rounds the tier uplift before the promotional uplift consumes it. The
cohort-weighted redemption rate clamps each cohort's adjusted rate before the
weighting rather than after. And the period close runs eight pinned steps, the
seventh of which re-measures the outstanding gross at close instead of reusing
the estimate's frozen snapshot.
"""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_fields,
    assert_lot_split,
    assert_null_fields,
    assert_ok,
    assert_rollforward,
    assert_rollforward_ties,
    assert_unchanged,
)
from test_helpers.constants import (
    CLOCK_EPOCH,
    CLOSE_DERIVED_FIELDS,
    COHORT_C1_OBSERVED_RATE_BP,
    COHORT_C2_ENROLLMENT_END,
    COHORT_C2_ENROLLMENT_START,
    COHORT_C2_SAMPLE_SIZE,
    DEFAULT_PROGRAM_CHANGE_ADJUSTMENT_BP,
    DEFAULT_SEEDED_BREAKAGE_RATE_BP,
    DEFAULT_SSP_MILLICENTS_PER_POINT,
    ESTIMATE_DRAFT,
    METHOD_COHORT_WEIGHTED,
    PERIOD_AUG_END,
    PERIOD_OPEN,
    PERIOD_SOFT_CLOSED,
    REDEMPTION_RATE_FLOOR_BP,
    TIER_GOLD,
    TIER_SILVER,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    ACCOUNTANT_ID,
    CONTROLLER_HEADERS,
)

# ─── The nested-rounding issuance ────────────────────────────────────────────
SILVER_TIER_MULTIPLIER_BP = 10300
SILVER_BASE_POINTS = 250
SILVER_PROMO_MULTIPLIER_BP = 10300
# round_half_up(250 * 10300 / 10000) == round_half_up(257.5)
SILVER_TIER_POINTS = 258
# round_half_up(258 * 10300 / 10000) == round_half_up(265.74); the collapsed
# one-shot form round_half_up(250 * 10300 * 10300 / 10**8) would give 265.
SILVER_POINTS_ISSUED = 266
COLLAPSED_POINTS_ISSUED = 265
# round_half_up(266 * 1200 / 1000) == round_half_up(319.2); on 265 points the
# gross would instead be 318.
SILVER_GROSS_CENTS = 319
COLLAPSED_GROSS_CENTS = 318
# round_half_up(319 * 2500 / 10000) == round_half_up(79.75)
SILVER_RESERVE_CENTS = 80
SILVER_DEFERRED_CENTS = 239
# round_half_up((258 - 250) * 1200 / 1000) and round_half_up((266 - 258) * 1200 / 1000)
SILVER_TIER_EXPENSE_CENTS = 10
SILVER_PROMO_EXPENSE_CENTS = 10

# ─── The clamp-before-weighting measurement ──────────────────────────────────
GOLD_BASE_POINTS = 4000
GOLD_LOT_POINTS = 5000
GOLD_LOT_GROSS_CENTS = 6000
GOLD_LOT_DEFERRED_CENTS = 4500

# Cohort two's raw adjusted rate, 100 plus the default 0, sits below the floor
# and is lifted to 200 before it is weighted.
COHORT_TWO_OBSERVED_RATE_BP = 100
COHORT_TWO_RAW_ADJUSTED_RATE_BP = 100

OUTSTANDING_POINTS_AT_ESTIMATE = 5266
OUTSTANDING_GROSS_AT_ESTIMATE_CENTS = 6319
# (8200 * 5000 + 200 * 266) / 5266 == 7795.898..., rounded half up once.
MEASURED_REDEMPTION_RATE_BP = 7796
# Clamping the weighted mean instead of each cohort would give
# (8200 * 5000 + 100 * 266) / 5266 == 7790.85..., i.e. 7791.
LATE_CLAMP_RATE_BP = 7791
MEASURED_BREAKAGE_RATE_BP = 2204
# round_half_up(6319 * 7796 / 10000) == round_half_up(4926.2924)
ESTIMATE_REQUIRED_LIABILITY_CENTS = 4926

# ─── The eight-step rollforward ──────────────────────────────────────────────
REDEEMED_POINTS = 3000
PROVISIONAL_RELEASE_CENTS = 2700
REMEASUREMENT_DELTA_CENTS = 107
ISSUANCE_DEFERRED_CENTS = 4739
OPENING_LIABILITY_CENTS = 0
# 0 + 4739 - 2700 - 107 - 0
PRE_CATCHUP_LIABILITY_CENTS = 1932
# 2000 remaining gold points priced at 1200 millicents, plus the 266 silver
# points, each lot rounded before the addition: 2400 + 319.
AT_CLOSE_OUTSTANDING_GROSS_CENTS = 2719
# round_half_up(2719 * 7796 / 10000) == round_half_up(2119.7324)
REQUIRED_LIABILITY_CENTS = 2120
# Reusing the estimate's frozen gross would instead give 4926.
SNAPSHOT_REUSE_REQUIRED_LIABILITY_CENTS = 4926
CATCH_UP_ADJUSTMENT_CENTS = 188
CLOSING_LIABILITY_CENTS = 2120
BREAKAGE_RECOGNIZED_CENTS = -188


def _silver_member_world(api):
    """An ACTIVE programme with one SILVER holder and one OPEN period."""
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(api, program["id"])
    cohort = fixtures.new_cohort(api, program["id"])
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(api, program["id"], cohort["id"], tier=TIER_SILVER)
    period = fixtures.new_period(api, program["id"])
    return {"program": program, "member": member, "period": period}


def _two_cohort_world(api):
    """
    Two enrolment vintages whose adjusted rates land on opposite sides of the
    band floor, each holding one outstanding lot.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(api, program["id"])
    first_cohort = fixtures.new_cohort(api, program["id"])
    second_cohort = fixtures.new_cohort(
        api,
        program["id"],
        enrollment_start_date=COHORT_C2_ENROLLMENT_START,
        enrollment_end_date=COHORT_C2_ENROLLMENT_END,
        observed_redemption_rate_bp=COHORT_TWO_OBSERVED_RATE_BP,
        sample_size=COHORT_C2_SAMPLE_SIZE,
    )
    program = fixtures.activate(api, program["id"])
    gold_member = fixtures.new_member(
        api, program["id"], first_cohort["id"], tier=TIER_GOLD
    )
    silver_member = fixtures.new_member(
        api, program["id"], second_cohort["id"], tier=TIER_SILVER
    )
    period = fixtures.new_period(api, program["id"])
    gold_lot = fixtures.issue_lot(
        api, gold_member["id"], period["id"], base_points=GOLD_BASE_POINTS
    )
    silver_lot = fixtures.issue_lot(
        api,
        silver_member["id"],
        period["id"],
        base_points=SILVER_BASE_POINTS,
        promo_multiplier_bp=SILVER_PROMO_MULTIPLIER_BP,
    )
    return {
        "program": program,
        "first_cohort": first_cohort,
        "second_cohort": second_cohort,
        "gold_member": gold_member,
        "silver_member": silver_member,
        "period": period,
        "gold_lot": gold_lot,
        "silver_lot": silver_lot,
    }


def _closable_world(api):
    """
    The two-cohort world with an approved estimate at 7796 basis points and one
    3000-point redemption taken all the way to fulfilment, so all four movement
    accumulators and the at-close balances disagree with the estimate snapshot.
    """
    world = _two_cohort_world(api)
    world["estimate"] = fixtures.approved_estimate(
        api, world["program"]["id"], world["period"]["id"]
    )
    world["event"] = fixtures.fulfilled_redemption(
        api, world["gold_member"]["id"], world["period"]["id"], REDEEMED_POINTS
    )
    return world


def test_promotional_uplift_consumes_the_already_rounded_tier_points(api):
    """
    Both uplifts carry a fractional tail, so the two roundings cannot be
    collapsed. The tier step turns 250 base points into 257.5 and rounds it to
    258 whole points; the promotional step then multiplies that rounded 258 and
    rounds 265.74 up to 266. Multiplying both multipliers together before
    rounding once would yield 265 instead.

    "`tier_points` is `base_points` multiplied by `tier_multiplier_bp_at_issue`, divided by 10000, and rounded half up to a whole number of points."
    "`points_issued` is the **already-rounded** `tier_points` multiplied by `promo_multiplier_bp`, divided by 10000, and rounded half up again."
    "These are two separate roundings and the second consumes the first's rounded output; `points_issued` is never obtained in one shot from `base_points` by multiplying both multipliers together before rounding, because that produces a different whole number whenever both multipliers carry a fractional tail."
    "Where the specification names two consecutive roundings, both roundings are mandatory and the second consumes the first's already-rounded result."

    Design: Difficulty/combinatorial_formula/combinatorial_issuance_nested_tier_then_promo_rounding
    """
    world = _silver_member_world(api)
    lot = fixtures.issue_lot(
        api,
        world["member"]["id"],
        world["period"]["id"],
        base_points=SILVER_BASE_POINTS,
        promo_multiplier_bp=SILVER_PROMO_MULTIPLIER_BP,
    )
    assert_fields(
        lot,
        base_points=SILVER_BASE_POINTS,
        promo_multiplier_bp=SILVER_PROMO_MULTIPLIER_BP,
        tier_multiplier_bp_at_issue=SILVER_TIER_MULTIPLIER_BP,
        tier_points=SILVER_TIER_POINTS,
        points_issued=SILVER_POINTS_ISSUED,
        points_remaining=SILVER_POINTS_ISSUED,
    )
    assert lot["points_issued"] != COLLAPSED_POINTS_ISSUED, (
        "Collapsing the two uplifts into one multiply-then-round is wrong"
    )


def test_nested_rounding_propagates_into_the_gross_reserve_and_deferral(api):
    """
    The 266-versus-265 split does not stay in the point count. At 1200 millicents
    a point, 266 points price at 319.2 cents and round to 319, where 265 would
    have rounded to 318; the reserve on 319 at the pinned 2500 basis points is
    79.75 rounding to 80, and the deferral the period picks up is 239 rather than
    the gross.

    "`gross_ssp_cents` is `points_issued` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`breakage_reserve_cents` is `gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."
    "`issuance_deferred_cents` grows by each issued lot's `deferred_revenue_cents`."

    Design: Difficulty/combinatorial_formula/combinatorial_issuance_nested_tier_then_promo_rounding
    """
    world = _silver_member_world(api)
    lot = fixtures.issue_lot(
        api,
        world["member"]["id"],
        world["period"]["id"],
        base_points=SILVER_BASE_POINTS,
        promo_multiplier_bp=SILVER_PROMO_MULTIPLIER_BP,
    )
    assert_fields(
        lot,
        ssp_millicents_per_point_at_issue=DEFAULT_SSP_MILLICENTS_PER_POINT,
        breakage_rate_bp_at_issue=DEFAULT_SEEDED_BREAKAGE_RATE_BP,
        gross_ssp_cents=SILVER_GROSS_CENTS,
        breakage_reserve_cents=SILVER_RESERVE_CENTS,
        deferred_revenue_cents=SILVER_DEFERRED_CENTS,
    )
    assert lot["gross_ssp_cents"] != COLLAPSED_GROSS_CENTS, (
        "A gross of 318 cents means the collapsed point count was used"
    )
    assert_lot_split(lot)

    period = assert_ok(api.get_period(world["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(period, issuance_deferred_cents=SILVER_DEFERRED_CENTS)


def test_each_uplift_is_expensed_on_its_own_point_delta(api):
    """
    The two uplifts are expensed separately, each on the point delta it alone
    created and each rounded on its own. The tier step added 258 less 250 points
    and the promotional step added 266 less 258, so both deltas are 8 points, both
    price at 9.6 cents and both round to 10 — a figure unobtainable from the
    combined 16-point uplift, which would price at 19.2 and round to 19.

    "`tier_benefit_expense_cents` is the difference between `tier_points` and `base_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up — and is therefore 0 for a `BASE` member."
    "`promo_expense_cents` is the difference between `points_issued` and `tier_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "The two uplifts are expensed separately, each measured on its own point delta at the snapshotted price."

    Design: Difficulty/combinatorial_formula/combinatorial_issuance_nested_tier_then_promo_rounding
    """
    world = _silver_member_world(api)
    lot = fixtures.issue_lot(
        api,
        world["member"]["id"],
        world["period"]["id"],
        base_points=SILVER_BASE_POINTS,
        promo_multiplier_bp=SILVER_PROMO_MULTIPLIER_BP,
    )
    assert_fields(
        lot,
        tier_benefit_expense_cents=SILVER_TIER_EXPENSE_CENTS,
        promo_expense_cents=SILVER_PROMO_EXPENSE_CENTS,
    )
    assert lot["tier_points"] - lot["base_points"] == 8, (
        "The tier delta must be the rounded tier points less the base points"
    )
    assert lot["points_issued"] - lot["tier_points"] == 8, (
        "The promotional delta must be measured on the rounded tier points"
    )


def test_each_cohorts_adjusted_rate_is_clamped_before_the_weighting(api):
    """
    One of the two vintages sits below the band floor: its observed rate of 100
    basis points plus its default zero adjustment is 100, which the first step
    lifts to 200 before the second step weights it. Weighting the raw 100 and
    clamping the mean afterwards would leave the mean inside the band and so pass
    the clamp untouched, giving 7791 instead of the correct 7796 — the whole
    5-basis-point gap is the ordering.

    "For each candidate cohort, add its `program_change_adjustment_bp` to its `observed_redemption_rate_bp`, then clamp the sum into the band from 200 through 9800 basis points inclusive — a sum below 200 becomes 200, a sum above 9800 becomes 9800."
    "Multiply each cohort's clamped rate by that cohort's weight, add those products together, divide by the total of all the weights, and round half up once to a whole number of basis points."
    "The clamp belongs to the first step and is applied per cohort **before** weighting."
    "Clamping the weighted result instead produces a different rate whenever any single cohort's raw adjusted rate falls outside the 200-to-9800 band, and that different rate is wrong."
    "From the measured rate, `breakage_rate_bp` is 10000 basis points less `estimated_redemption_rate_bp`."

    Design: Difficulty/combinatorial_formula/combinatorial_cohort_rate_clamped_before_weighting
    """
    world = _two_cohort_world(api)
    estimate = fixtures.draft_estimate(
        api, world["program"]["id"], world["period"]["id"]
    )
    assert_fields(
        estimate,
        estimated_redemption_rate_bp=MEASURED_REDEMPTION_RATE_BP,
        breakage_rate_bp=MEASURED_BREAKAGE_RATE_BP,
        method_applied=METHOD_COHORT_WEIGHTED,
    )
    assert estimate["estimated_redemption_rate_bp"] != LATE_CLAMP_RATE_BP, (
        "A rate of 7791 means the band was applied to the weighted mean"
    )
    assert (
        world["second_cohort"]["observed_redemption_rate_bp"]
        + world["second_cohort"]["program_change_adjustment_bp"]
        == COHORT_TWO_RAW_ADJUSTED_RATE_BP
    ), "The second vintage's raw adjusted rate must sit below the band floor"
    assert COHORT_TWO_RAW_ADJUSTED_RATE_BP < REDEMPTION_RATE_FLOOR_BP, (
        "The whole point of the case is a raw rate the floor has to lift"
    )
    assert_fields(
        world["second_cohort"],
        program_change_adjustment_bp=DEFAULT_PROGRAM_CHANGE_ADJUSTMENT_BP,
    )
    assert_fields(
        world["first_cohort"], observed_redemption_rate_bp=COHORT_C1_OBSERVED_RATE_BP
    )


def test_the_weights_and_gross_come_from_the_same_outstanding_lot_set(api):
    """
    The weights that drove the rate and the gross the liability is struck on are
    two views of one lot set. The gold vintage contributes its whole 5000-point
    lot and the silver vintage its 266, so the total weight is 5266; the gross is
    each lot's remaining amount rounded on its own and then added, 6000 plus 319,
    and the required balance is that 6319 taken at the measured 7796.

    "The candidate set is built from the programme's cohorts that carry a non-zero weight, where a cohort's **weight** is the total `points_remaining` over the lots held by that cohort's members whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`."
    "`outstanding_points_at_estimate` is the total weight — that is, the total outstanding points over the lot set that was measured."
    "`outstanding_gross_ssp_cents_at_estimate` is the sum, over that same lot set, of each lot's `remaining_gross_ssp_cents`, with each lot rounded first and the rounded amounts then added."
    "The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment."

    Design: Difficulty/combinatorial_formula/combinatorial_cohort_rate_clamped_before_weighting
    """
    world = _two_cohort_world(api)
    assert_fields(
        world["gold_lot"],
        points_issued=GOLD_LOT_POINTS,
        points_remaining=GOLD_LOT_POINTS,
        gross_ssp_cents=GOLD_LOT_GROSS_CENTS,
        deferred_revenue_cents=GOLD_LOT_DEFERRED_CENTS,
    )
    estimate = fixtures.draft_estimate(
        api, world["program"]["id"], world["period"]["id"]
    )
    assert_fields(
        estimate,
        outstanding_points_at_estimate=OUTSTANDING_POINTS_AT_ESTIMATE,
        outstanding_gross_ssp_cents_at_estimate=OUTSTANDING_GROSS_AT_ESTIMATE_CENTS,
        required_liability_cents=ESTIMATE_REQUIRED_LIABILITY_CENTS,
    )
    assert (
        estimate["outstanding_points_at_estimate"]
        == world["gold_lot"]["points_remaining"] + world["silver_lot"]["points_remaining"]
    ), "The total weight must be the two vintages' outstanding points"


def test_the_measurement_is_frozen_at_creation_and_installs_no_rate(api):
    """
    A draft estimate is a snapshot, not a live query. After 3000 of the gold
    vintage's points are redeemed and allocated — which drops the outstanding
    balance to 2266 points and 2719 cents — the estimate still reports the 5266
    points, 6319 cents and 7796 basis points it measured at creation, and the
    programme's live rate is still the 2500 basis points activation seeded,
    because only an approval installs a new one.

    "Measurement runs at creation and is frozen thereafter."
    "The estimate is then persisted in `state` `DRAFT`, with `prepared_by_user_id` set to the acting `X-User-ID`, `revision_count` at 0, `supersedes_estimate_id` null, `approved_by_user_id` null, `rejection_reason` null, and `submitted_at` and `approved_at` both null."
    "That first activation seeds the programme's live breakage rate: `current_breakage_rate_bp` becomes 10000 basis points less `historical_redemption_rate_bp`."
    "The programme's `current_breakage_rate_bp` is overwritten with this estimate's `breakage_rate_bp`, and the programme's `version` increments by 1."

    Design: Difficulty/combinatorial_formula/combinatorial_cohort_rate_clamped_before_weighting
    """
    world = _two_cohort_world(api)
    estimate = fixtures.draft_estimate(
        api, world["program"]["id"], world["period"]["id"]
    )
    assert_fields(
        estimate,
        state=ESTIMATE_DRAFT,
        prepared_by_user_id=ACCOUNTANT_ID,
        revision_count=0,
    )
    assert_null_fields(
        estimate,
        "supersedes_estimate_id",
        "approved_by_user_id",
        "rejection_reason",
        "submitted_at",
        "approved_at",
    )

    # Allocation, not fulfilment: fulfilment "requires ... an `APPROVED` breakage
    # estimate to exist for that period", and approving one would itself install a
    # new programme rate, which is exactly what this test asserts has not happened.
    # Allocation alone consumes the lots, so the outstanding balance still moves
    # underneath the frozen snapshot.
    fixtures.allocated_redemption(
        api, world["gold_member"]["id"], world["period"]["id"], REDEEMED_POINTS
    )
    reread = assert_ok(api.get_estimate(estimate["id"], ACCOUNTANT_HEADERS))
    assert_unchanged(
        estimate,
        reread,
        "estimated_redemption_rate_bp",
        "breakage_rate_bp",
        "outstanding_points_at_estimate",
        "outstanding_gross_ssp_cents_at_estimate",
        "required_liability_cents",
    )

    program = assert_ok(api.get_program(world["program"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        program, current_breakage_rate_bp=DEFAULT_SEEDED_BREAKAGE_RATE_BP
    )


def test_the_eight_steps_run_in_their_pinned_order_at_soft_close(api):
    """
    Every one of the eight steps carries a figure the later ones consume, so the
    whole chain is asserted at once. With no earlier closed period the opening is
    0; the four accumulators are frozen at the 4739 deferred, 2700 recognised and
    107 re-measured the events left behind; Step 6's sign order turns those into
    1932; Step 7 strikes 2719 at the approved 7796 for 2120; and Step 8 derives a
    catch-up of 188, a closing balance of 2120 and recognised breakage of −188.

    "When the programme has no closed period at all, `opening_liability_cents` is 0."
    "`issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents` and `expiry_released_cents` are **frozen as they stand**."
    "`pre_catchup_liability_cents` is `opening_liability_cents` **plus** `issuance_deferred_cents`, **less** `redemption_recognized_cents`, **less** `remeasurement_delta_cents`, **less** `expiry_released_cents`."
    "`catch_up_adjustment_cents` is `required_liability_cents` less `pre_catchup_liability_cents`, and may be negative."
    "`closing_liability_cents` is `pre_catchup_liability_cents` plus `catch_up_adjustment_cents`."
    "`breakage_recognized_cents` is the negation of `catch_up_adjustment_cents` — negative when the liability must be topped up and positive when it is released."
    "On success the eight steps run in the pinned order, `opening_liability_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `closing_liability_cents`, `breakage_recognized_cents` and `approved_estimate_rate_bp` are persisted, `soft_closed_at` is set to the clock reading, and `version` increments by 1."

    Design: Difficulty/combinatorial_formula/combinatorial_period_close_rollforward_pinned_eight_step_order
    """
    world = _closable_world(api)
    before = assert_ok(api.get_period(world["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        before,
        state=PERIOD_OPEN,
        issuance_deferred_cents=ISSUANCE_DEFERRED_CENTS,
        redemption_recognized_cents=PROVISIONAL_RELEASE_CENTS,
        remeasurement_delta_cents=REMEASUREMENT_DELTA_CENTS,
        expiry_released_cents=0,
    )

    fixtures.set_clock(api, PERIOD_AUG_END)
    period = fixtures.soft_close(api, world["period"]["id"])
    assert_fields(
        period,
        state=PERIOD_SOFT_CLOSED,
        opening_liability_cents=OPENING_LIABILITY_CENTS,
        issuance_deferred_cents=ISSUANCE_DEFERRED_CENTS,
        redemption_recognized_cents=PROVISIONAL_RELEASE_CENTS,
        remeasurement_delta_cents=REMEASUREMENT_DELTA_CENTS,
        expiry_released_cents=0,
        pre_catchup_liability_cents=PRE_CATCHUP_LIABILITY_CENTS,
        approved_estimate_rate_bp=MEASURED_REDEMPTION_RATE_BP,
        required_liability_cents=REQUIRED_LIABILITY_CENTS,
        catch_up_adjustment_cents=CATCH_UP_ADJUSTMENT_CENTS,
        closing_liability_cents=CLOSING_LIABILITY_CENTS,
        breakage_recognized_cents=BREAKAGE_RECOGNIZED_CENTS,
        soft_closed_at=PERIOD_AUG_END,
        version=before["version"] + 1,
    )
    assert_rollforward_ties(period)

    program = assert_ok(api.get_program(world["program"]["id"], CONTROLLER_HEADERS))
    assert_fields(program, recognized_breakage_ytd_cents=BREAKAGE_RECOGNIZED_CENTS)


def test_step_seven_remeasures_the_gross_at_close_instead_of_reusing_the_snapshot(api):
    """
    Between approval and close, 3000 of the gold vintage's 5000 points were
    redeemed, so the two grosses have parted company: the estimate's frozen 6319
    cents against 2719 measured at close. Step 7 must take the later one, giving a
    required balance of 2120 rather than the 4926 the snapshot would produce, while
    the estimate itself is left untouched.

    "The outstanding gross standalone selling price is then measured **at close**, over the programme's lots — programme-wide, not period-scoped, because a lot issued in an earlier period still carries liability into this period's required balance — whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`, summing each lot's `points_remaining` multiplied by its own `ssp_millicents_per_point_at_issue` divided by 1000 and rounded half up per lot."
    "`required_liability_cents` is that at-close gross multiplied by `approved_estimate_rate_bp`, divided by 10000, rounded half up."
    "The estimate's own frozen `outstanding_gross_ssp_cents_at_estimate` is **not** reused here; measuring at close is what makes the catch-up reflect every redemption and expiry that happened between approval and close."
    "Steps 6 and 8 are exact integer arithmetic; the only rounding in the whole rollforward happens inside Step 7."

    Design: Difficulty/combinatorial_formula/combinatorial_period_close_rollforward_pinned_eight_step_order
    """
    world = _closable_world(api)
    assert_fields(
        world["estimate"],
        outstanding_gross_ssp_cents_at_estimate=OUTSTANDING_GROSS_AT_ESTIMATE_CENTS,
        required_liability_cents=ESTIMATE_REQUIRED_LIABILITY_CENTS,
    )

    preview = assert_ok(
        api.get_liability_rollforward(world["period"]["id"], CONTROLLER_HEADERS)
    )
    assert_rollforward(
        preview, outstanding_gross_ssp_cents=AT_CLOSE_OUTSTANDING_GROSS_CENTS
    )
    assert (
        preview["outstanding_gross_ssp_cents"]
        != OUTSTANDING_GROSS_AT_ESTIMATE_CENTS
    ), "The at-close gross must not be the estimate's frozen gross"

    fixtures.set_clock(api, PERIOD_AUG_END)
    period = fixtures.soft_close(api, world["period"]["id"])
    assert_fields(period, required_liability_cents=REQUIRED_LIABILITY_CENTS)
    assert period["required_liability_cents"] != SNAPSHOT_REUSE_REQUIRED_LIABILITY_CENTS, (
        "A required balance of 4926 means the estimate's snapshot was reused"
    )

    estimate = assert_ok(api.get_estimate(world["estimate"]["id"], ACCOUNTANT_HEADERS))
    assert_unchanged(
        world["estimate"],
        estimate,
        "outstanding_points_at_estimate",
        "outstanding_gross_ssp_cents_at_estimate",
        "required_liability_cents",
        "estimated_redemption_rate_bp",
    )


def test_the_preview_reports_all_twelve_figures_and_writes_none_of_them(api):
    """
    The preview re-runs the same eight steps and reaches the same answers as the
    close would — a 1932 pre-catch-up, a 2719 at-close gross, a 2120 required
    balance and a 188 catch-up — yet the period afterwards is still OPEN at its
    original version with all seven close-derived figures still 0 and
    `soft_closed_at` still null.

    "A `LoyaltyAccountant` or `Controller` may ask an open period for its liability rollforward preview, which re-runs all eight steps against current data and **persists nothing** — no field is written, no `version` is bumped, and the period's `state` is unchanged."
    "The preview reports `opening_liability_cents`, `issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents`, `expiry_released_cents`, `pre_catchup_liability_cents`, `outstanding_gross_ssp_cents` (the at-close gross the required balance was measured on), `required_liability_cents`, `catch_up_adjustment_cents`, `closing_liability_cents`, `breakage_recognized_cents` and `approved_estimate_rate_bp`."

    Design: Difficulty/combinatorial_formula/combinatorial_period_close_rollforward_pinned_eight_step_order
    """
    world = _closable_world(api)
    before = assert_ok(api.get_period(world["period"]["id"], CONTROLLER_HEADERS))

    preview = assert_ok(
        api.get_liability_rollforward(world["period"]["id"], ACCOUNTANT_HEADERS)
    )
    assert_rollforward(
        preview,
        opening_liability_cents=OPENING_LIABILITY_CENTS,
        issuance_deferred_cents=ISSUANCE_DEFERRED_CENTS,
        redemption_recognized_cents=PROVISIONAL_RELEASE_CENTS,
        remeasurement_delta_cents=REMEASUREMENT_DELTA_CENTS,
        expiry_released_cents=0,
        pre_catchup_liability_cents=PRE_CATCHUP_LIABILITY_CENTS,
        outstanding_gross_ssp_cents=AT_CLOSE_OUTSTANDING_GROSS_CENTS,
        required_liability_cents=REQUIRED_LIABILITY_CENTS,
        catch_up_adjustment_cents=CATCH_UP_ADJUSTMENT_CENTS,
        closing_liability_cents=CLOSING_LIABILITY_CENTS,
        breakage_recognized_cents=BREAKAGE_RECOGNIZED_CENTS,
        approved_estimate_rate_bp=MEASURED_REDEMPTION_RATE_BP,
    )
    assert_rollforward_ties(preview)

    after = assert_ok(api.get_period(world["period"]["id"], CONTROLLER_HEADERS))
    assert_unchanged(before, after, "state", "version", "updated_at")
    assert_fields(after, state=PERIOD_OPEN)
    assert_null_fields(after, "soft_closed_at")
    for field in CLOSE_DERIVED_FIELDS:
        assert after[field] == 0, (
            f"The preview must not write '{field}': found {after[field]}"
        )
