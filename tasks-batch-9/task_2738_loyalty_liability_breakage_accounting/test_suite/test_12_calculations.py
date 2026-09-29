"""
The arithmetic edge cases of the Loyalty Liability & Breakage Accounting API.

Every figure asserted here was recomputed by hand from the contract's formulas
with the round-half-up rule applied at exactly the points the contract names, so
a collapsed two-step rounding, a clamp applied to the wrong quantity or a
threshold tested before the carry-forward is added shows up as a mismatch.
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
    BREAKAGE_METHOD_COHORT_WEIGHTED,
    BREAKAGE_METHOD_PROGRAM_HISTORICAL,
    CHANGE_EXPIRY_DAYS,
    CHANGE_SSP,
    CHANGE_TIER_MULTIPLIER,
    CLOCK_EPOCH,
    ESTIMATE_DRAFT,
    LOT_ESCHEATED,
    LOT_FULLY_REDEEMED,
    LOT_OUTSTANDING,
    MEMBER_ACTIVE,
    MEMBER_DORMANT,
    METHOD_COHORT_WEIGHTED,
    METHOD_PROGRAM_HISTORICAL,
    METHOD_SINGLE_COHORT,
    ORDER_MODELED,
    PERIOD_SEP_CODE,
    PERIOD_SEP_END,
    PERIOD_SEP_START,
    STATE_DE,
    TIER_BASE,
    TIER_GOLD,
    TIER_SILVER,
)
from test_helpers.test_users import ACCOUNTANT_HEADERS, ACCOUNTANT_ID

# ─── The reference configuration these fixtures share ────────────────────────
SSP_1200 = 1200
SSP_1000 = 1000
HISTORICAL_RATE_BP = 7500
SEEDED_BREAKAGE_RATE_BP = 2500  # 10000 - 7500, installed by first activation
POINT_CAP = 5000
PROMO_CAP_BP = 30000

# ─── Cohort behaviour ────────────────────────────────────────────────────────
C1_OBSERVED_BP = 8200
C2_OBSERVED_BP = 400
C2_ADJUSTMENT_BP = -300  # 400 + -300 == 100, clamped up to the 200 bp floor
C2_CLAMPED_BP = 200
C1_ENROLLMENT_START = "2024-01-01T00:00:00Z"
C1_ENROLLMENT_END = "2024-12-31T00:00:00Z"
C2_ENROLLMENT_START = "2025-01-01T00:00:00Z"
C2_ENROLLMENT_END = "2025-12-31T00:00:00Z"

# ─── A 1000-point BASE lot at 1200 millicents ────────────────────────────────
LOT_1000_GROSS_CENTS = 1200  # 1000 * 1200 / 1000
LOT_1000_RESERVE_CENTS = 300  # 1200 * 2500 / 10000
LOT_1000_DEFERRED_CENTS = 900

# ─── The two-cohort programme-wide measurement ───────────────────────────────
TWO_COHORT_RATE_BP = 4200  # (8200 * 1000 + 200 * 1000) / 2000
TWO_COHORT_BREAKAGE_BP = 5800
TWO_COHORT_POINTS = 2000
TWO_COHORT_GROSS_CENTS = 2400  # 1200 + 1200, each lot rounded first
TWO_COHORT_REQUIRED_CENTS = 1008  # 2400 * 4200 / 10000
SINGLE_COHORT_REQUIRED_CENTS = 984  # 1200 * 8200 / 10000

# ─── The GOLD lot of 4000 base points ────────────────────────────────────────
GOLD_BASE_POINTS = 4000
GOLD_POINTS_ISSUED = 5000  # 4000 * 12500 / 10000
GOLD_GROSS_CENTS = 6000  # 5000 * 1200 / 1000
HISTORICAL_REQUIRED_CENTS = 4500  # 6000 * 7500 / 10000
COHORT_REQUIRED_ON_GOLD_CENTS = 4920  # 6000 * 8200 / 10000

# ─── The exact-half tie fixture, priced at 1000 millicents per point ─────────
TIE_OBSERVED_BP = 8205
TIE_GROSS_CENTS = 1000  # 1000 points at 1000 millicents
TIE_REQUIRED_CENTS = 821  # 1000 * 8205 / 10000 == 820.5, rounded up
TIE_LOW_BP = 7705
TIE_HIGH_BP = 8705
TIE_LOW_CENTS = 771  # exactly 770.5
TIE_HIGH_CENTS = 871  # exactly 870.5
TIE_BAND_RANGE_CENTS = 100
TIE_SILVER_BASE_POINTS = 250
TIE_SILVER_TIER_POINTS = 258  # 250 * 10300 / 10000 == 257.5, rounded up
TIE_SILVER_GROSS_CENTS = 258
TIE_SILVER_RESERVE_CENTS = 65  # 258 * 2500 / 10000 == 64.5, rounded up
TIE_SILVER_DEFERRED_CENTS = 193
TIE_SILVER_TIER_EXPENSE_CENTS = 8  # (258 - 250) * 1000 / 1000

# ─── The input-set filter fixture ────────────────────────────────────────────
FILTERED_POINTS = 2000  # two surviving lots of 1000, not three
FILTERED_GROSS_CENTS = 2400
FILTERED_REQUIRED_CENTS = 1968  # 2400 * 8200 / 10000

# ─── The carry-forward settlement fixture ────────────────────────────────────
PARTNER_ISSUANCE_RATE = 900
PARTNER_REDEMPTION_RATE = 1100
PARTNER_LAG_DAYS = 30
CARRY_MIN_INVOICE_CENTS = 3000
CARRY_BASE_POINTS = 2000
CARRY_RECEIVABLE_CENTS = 1800  # 2000 * 900 / 1000
CARRY_BILLED_CENTS = 3600  # 1800 receivable plus 1800 carried forward
PER1_DUE_DATE = "2026-10-01T00:00:00Z"  # 2026-09-01 plus 30 whole days
PER2_DUE_DATE = "2026-10-31T00:00:00Z"  # 2026-10-01 plus 30 whole days

# ─── The change-order projection fixture ─────────────────────────────────────
PROJ_BASE_POINTS = 3999
PROJ_POINTS_ISSUED = 4999  # 3999 * 12500 / 10000 == 4998.75, rounded up
PROJ_BASELINE_GROSS_CENTS = 5999  # 4999 * 1200 / 1000 == 5998.8, rounded up
PROJ_BASELINE_RATE_BP = 7500  # 10000 - 2500
PROJ_BASELINE_LIABILITY_CENTS = 4499  # 5999 * 7500 / 10000 == 4499.25
PROJ_NEW_SSP = 1500
PROJ_ELASTICITY_BP = -400
PROJ_RATE_BP = 7100
PROJ_GROSS_CENTS = 7499  # 4999 * 1500 / 1000 == 7498.5, rounded up
PROJ_LIABILITY_CENTS = 5324  # 7499 * 7100 / 10000 == 5324.29
PROJ_DELTA_CENTS = 825  # 5324 - 4499, each leg rounded before subtracting

RATE_CEILING_BP = 9800
RATE_FLOOR_BP = 200
CEILING_ELASTICITY_BP = 2500  # 7500 + 2500 == 10000, clamped down to 9800
CEILING_LIABILITY_CENTS = 5879  # 5999 * 9800 / 10000 == 5879.02
CEILING_DELTA_CENTS = 1380  # 5879 - 4499

# The floor is reached from a programme whose historical rate is lower, because the
# elasticity itself is only accepted from -5000 through 5000.
FLOOR_HISTORICAL_RATE_BP = 4000
FLOOR_BASELINE_RATE_BP = 4000  # 10000 - 6000
FLOOR_ELASTICITY_BP = -5000  # 4000 - 5000 == -1000, clamped up to 200
FLOOR_BASELINE_LIABILITY_CENTS = 2400  # 5999 * 4000 / 10000 == 2399.6
FLOOR_LIABILITY_CENTS = 120  # 5999 * 200 / 10000 == 119.98
FLOOR_DELTA_CENTS = -2280  # 120 - 2400
NEW_EXPIRY_DAYS = 1095
NEW_TIER_MULTIPLIER_BP = {"BASE": 10000, "SILVER": 10100, "GOLD": 10500, "PLATINUM": 11000}

# ─── The escheatment latch fixture ───────────────────────────────────────────
ESCHEAT_THRESHOLD_CENTS = 3601
ESCHEAT_RATE_BP = 6000
LOT1_ISSUED_AT = "2026-08-05T00:00:00Z"
LOT1_EXPIRES_AT = "2028-08-04T00:00:00Z"  # 2026-08-05 plus 730 whole days
LOT2_ISSUED_AT = "2026-09-05T00:00:00Z"
LOT2_EXPIRES_AT = "2028-09-04T00:00:00Z"
SWEEP_1_CLOCK = "2028-08-05T00:00:00Z"
SWEEP_2_CLOCK = "2028-09-05T00:00:00Z"
LOT1_GROSS_CENTS = 6000
LOT1_DEFERRED_CENTS = 4500
LOT1_ESCHEATED_CENTS = 3600  # 6000 * 6000 / 10000
LOT2_GROSS_CENTS = 120
LOT2_DEFERRED_CENTS = 90
LOT2_ESCHEATED_CENTS = 72  # 120 * 6000 / 10000
ESCHEAT_TOTAL_AFTER_BOTH_CENTS = 3672

# ─── The two-uplift expense fixture ──────────────────────────────────────────
EXPENSE_BASE_POINTS = 250
EXPENSE_PROMO_BP = 10300
EXPENSE_TIER_POINTS = 258  # 250 * 10300 / 10000 == 257.5, rounded up
EXPENSE_POINTS_ISSUED = 266  # 258 * 10300 / 10000 == 265.74, rounded up
EXPENSE_GROSS_CENTS = 319  # 266 * 1200 / 1000 == 319.2
EXPENSE_RESERVE_CENTS = 80  # 319 * 2500 / 10000 == 79.75, rounded up
EXPENSE_DEFERRED_CENTS = 239
EXPENSE_TIER_LEG_CENTS = 10  # (258 - 250) * 1200 / 1000 == 9.6
EXPENSE_PROMO_LEG_CENTS = 10  # (266 - 258) * 1200 / 1000 == 9.6


# ─── Shared setup ────────────────────────────────────────────────────────────
C1_SPEC = {
    "observed_redemption_rate_bp": C1_OBSERVED_BP,
    "program_change_adjustment_bp": 0,
    "enrollment_start_date": C1_ENROLLMENT_START,
    "enrollment_end_date": C1_ENROLLMENT_END,
}
C2_SPEC = {
    "observed_redemption_rate_bp": C2_OBSERVED_BP,
    "program_change_adjustment_bp": C2_ADJUSTMENT_BP,
    "enrollment_start_date": C2_ENROLLMENT_START,
    "enrollment_end_date": C2_ENROLLMENT_END,
}


def _activated_program(
    api, cohort_specs=None, clock=CLOCK_EPOCH, rule_overrides=None, **program_overrides
):
    """
    An ACTIVE programme carrying one state expiry rule and the cohorts described,
    returned as ``(program, cohorts)`` with the programme read back after
    activation so its seeded breakage rate is current.
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


def _two_cohort_fixture(api):
    """
    A programme measuring by cohort weight, with two equally weighted cohorts: C1
    observed at 8200 bp with no adjustment, and C2 whose adjusted rate falls under
    the floor and is therefore clamped up to 200 bp.
    """
    program, cohorts = _activated_program(
        api,
        [dict(C1_SPEC), dict(C2_SPEC)],
        ssp_millicents_per_point=SSP_1200,
        breakage_method=BREAKAGE_METHOD_COHORT_WEIGHTED,
        historical_redemption_rate_bp=HISTORICAL_RATE_BP,
    )
    period = fixtures.new_period(api, program["id"])
    lots = []
    for cohort in cohorts:
        member = fixtures.new_member(api, program["id"], cohort["id"], tier=TIER_BASE)
        lots.append(fixtures.issue_lot(api, member["id"], period["id"], 1000))
    return program, cohorts, period, lots


def test_supplied_cohort_id_selects_the_single_cohort_variant(api):
    """
    Two equally weighted cohorts sit under a programme whose method is cohort
    weighting, so the programme-wide estimate blends 8200 bp and the clamped 200 bp
    into 4200 bp over both lots, while an otherwise identical request that names C1
    collapses to that cohort's own 8200 bp over C1's lot alone. Naming a cohort
    switches the variant even though the programme's own method is unchanged, and
    each variant carries its own weight, its own frozen gross and its own liability.

    "`COHORT_WEIGHTED` runs when the programme's `breakage_method` is `COHORT_WEIGHTED` and the request omits `cohort_id`."
    "`SINGLE_COHORT` runs whenever the request supplies `cohort_id`, regardless of the programme's `breakage_method`."
    "The candidate set is restricted to that one cohort, so the total weight is that cohort's weight and the weighted mean collapses to that cohort's own clamped adjusted rate — its `observed_redemption_rate_bp` plus its `program_change_adjustment_bp`, clamped into 200 through 9800 — with no division and therefore no division rounding."
    "From the measured rate, `breakage_rate_bp` is 10000 basis points less `estimated_redemption_rate_bp`."
    "`outstanding_points_at_estimate` is the total weight — that is, the total outstanding points over the lot set that was measured."
    "`outstanding_gross_ssp_cents_at_estimate` is the sum, over that same lot set, of each lot's `remaining_gross_ssp_cents`, with each lot rounded first and the rounded amounts then added."
    "The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment."
    "The estimate is then persisted in `state` `DRAFT`, with `prepared_by_user_id` set to the acting `X-User-ID`, `revision_count` at 0, `supersedes_estimate_id` null, `approved_by_user_id` null, `rejection_reason` null, and `submitted_at` and `approved_at` both null."

    Design: Corner/calculations/calc_estimate_single_cohort_variant_selected_by_cohort_id
    """
    program, cohorts, period, lots = _two_cohort_fixture(api)
    for lot in lots:
        assert_fields(
            lot,
            points_issued=1000,
            points_remaining=1000,
            gross_ssp_cents=LOT_1000_GROSS_CENTS,
            breakage_reserve_cents=LOT_1000_RESERVE_CENTS,
            deferred_revenue_cents=LOT_1000_DEFERRED_CENTS,
        )

    program_wide = fixtures.draft_estimate(api, program["id"], period["id"])
    assert_fields(
        program_wide,
        method_applied=METHOD_COHORT_WEIGHTED,
        cohort_id=None,
        estimated_redemption_rate_bp=TWO_COHORT_RATE_BP,
        breakage_rate_bp=TWO_COHORT_BREAKAGE_BP,
        outstanding_points_at_estimate=TWO_COHORT_POINTS,
        outstanding_gross_ssp_cents_at_estimate=TWO_COHORT_GROSS_CENTS,
        required_liability_cents=TWO_COHORT_REQUIRED_CENTS,
        state=ESTIMATE_DRAFT,
        prepared_by_user_id=ACCOUNTANT_ID,
    )

    narrowed = fixtures.draft_estimate(
        api, program["id"], period["id"], cohort_id=cohorts[0]["id"]
    )
    assert_fields(
        narrowed,
        method_applied=METHOD_SINGLE_COHORT,
        cohort_id=cohorts[0]["id"],
        estimated_redemption_rate_bp=C1_OBSERVED_BP,
        breakage_rate_bp=10000 - C1_OBSERVED_BP,
        outstanding_points_at_estimate=1000,
        outstanding_gross_ssp_cents_at_estimate=LOT_1000_GROSS_CENTS,
        required_liability_cents=SINGLE_COHORT_REQUIRED_CENTS,
        state=ESTIMATE_DRAFT,
        prepared_by_user_id=ACCOUNTANT_ID,
    )


def _historical_fixture(api):
    """A programme measuring from its own history, holding one GOLD lot of 5000 points."""
    program, cohorts = _activated_program(
        api,
        ssp_millicents_per_point=SSP_1200,
        breakage_method=BREAKAGE_METHOD_PROGRAM_HISTORICAL,
        historical_redemption_rate_bp=HISTORICAL_RATE_BP,
        per_issuance_point_cap=POINT_CAP,
    )
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"], tier=TIER_GOLD)
    period = fixtures.new_period(api, program["id"])
    lot = fixtures.issue_lot(api, member["id"], period["id"], GOLD_BASE_POINTS)
    return program, cohorts[0], period, lot


def test_program_historical_variant_takes_the_programme_rate_verbatim(api):
    """
    The programme's method is its own history, so an estimate that names no cohort
    ignores the 8200 bp cohort entirely and adopts the programme's 7500 bp exactly
    as configured, while still measuring the outstanding balance itself: 5000 points
    at 1200 millicents give a frozen gross of 6000 cents and a liability of 4500.

    "`PROGRAM_HISTORICAL` runs when the programme's `breakage_method` is `PROGRAM_HISTORICAL` and the request omits `cohort_id`."
    "Cohort weights and adjustments are ignored entirely and `estimated_redemption_rate_bp` takes the programme's `historical_redemption_rate_bp` verbatim."
    "`outstanding_points_at_estimate` and `outstanding_gross_ssp_cents_at_estimate` are still measured over the same lot set, so `required_liability_cents` still varies with the outstanding balance, and `ERR_NO_OUTSTANDING_POINTS` still applies when nothing is outstanding."
    "`tier_points` is `base_points` multiplied by `tier_multiplier_bp_at_issue`, divided by 10000, and rounded half up to a whole number of points."
    "Only once `points_issued` has been measured is the cap tested: a `points_issued` strictly greater than the programme's `per_issuance_point_cap` is rejected with `ERR_ISSUANCE_CAP_EXCEEDED`, and a value exactly equal to the cap passes."
    "The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment."

    Design: Corner/calculations/calc_estimate_program_historical_variant_selected_by_program_method
    """
    program, _cohort, period, lot = _historical_fixture(api)
    assert_fields(
        lot,
        tier_multiplier_bp_at_issue=12500,
        points_issued=GOLD_POINTS_ISSUED,
        points_remaining=GOLD_POINTS_ISSUED,
        gross_ssp_cents=GOLD_GROSS_CENTS,
    )

    estimate = fixtures.draft_estimate(api, program["id"], period["id"])
    assert_fields(
        estimate,
        method_applied=METHOD_PROGRAM_HISTORICAL,
        cohort_id=None,
        estimated_redemption_rate_bp=HISTORICAL_RATE_BP,
        breakage_rate_bp=10000 - HISTORICAL_RATE_BP,
        outstanding_points_at_estimate=GOLD_POINTS_ISSUED,
        outstanding_gross_ssp_cents_at_estimate=GOLD_GROSS_CENTS,
        required_liability_cents=HISTORICAL_REQUIRED_CENTS,
        state=ESTIMATE_DRAFT,
    )


def test_named_cohort_outranks_the_programme_historical_method(api):
    """
    Against the same programme whose method is its own history, naming a cohort
    still switches the variant to the single-cohort one: the rate becomes the
    cohort's own 8200 bp rather than the programme's 7500 bp, and the liability over
    the same frozen gross of 6000 cents is 4920 rather than 4500.

    "`SINGLE_COHORT` runs whenever the request supplies `cohort_id`, regardless of the programme's `breakage_method`."
    "The candidate set is restricted to that one cohort, so the total weight is that cohort's weight and the weighted mean collapses to that cohort's own clamped adjusted rate — its `observed_redemption_rate_bp` plus its `program_change_adjustment_bp`, clamped into 200 through 9800 — with no division and therefore no division rounding."
    "From the measured rate, `breakage_rate_bp` is 10000 basis points less `estimated_redemption_rate_bp`."
    "The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment."

    Design: Corner/calculations/calc_estimate_program_historical_variant_selected_by_program_method
    """
    program, cohort, period, _lot = _historical_fixture(api)

    estimate = fixtures.draft_estimate(
        api, program["id"], period["id"], cohort_id=cohort["id"]
    )
    assert_fields(
        estimate,
        method_applied=METHOD_SINGLE_COHORT,
        cohort_id=cohort["id"],
        estimated_redemption_rate_bp=C1_OBSERVED_BP,
        breakage_rate_bp=10000 - C1_OBSERVED_BP,
        outstanding_points_at_estimate=GOLD_POINTS_ISSUED,
        outstanding_gross_ssp_cents_at_estimate=GOLD_GROSS_CENTS,
        required_liability_cents=COHORT_REQUIRED_ON_GOLD_CENTS,
    )


TIE_MEMO = "Tie-breaking measurement recorded for the audit file."


def _tie_fixture(api):
    """
    A programme priced at exactly 1000 millicents per point holding one 1000-point
    lot, so a rate of 8205 bp lands the liability on an exact half-cent.
    """
    spec = dict(C1_SPEC)
    spec["observed_redemption_rate_bp"] = TIE_OBSERVED_BP
    program, cohorts = _activated_program(
        api,
        [spec],
        ssp_millicents_per_point=SSP_1000,
        breakage_method=BREAKAGE_METHOD_COHORT_WEIGHTED,
        historical_redemption_rate_bp=HISTORICAL_RATE_BP,
    )
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"], tier=TIER_BASE)
    period = fixtures.new_period(api, program["id"])
    fixtures.issue_lot(api, member["id"], period["id"], 1000)
    return program, cohorts[0], period


def _tie_estimate(api, program_id, period_id):
    return fixtures.draft_estimate(
        api,
        program_id,
        period_id,
        memo_narrative=TIE_MEMO,
        sensitivity_low_bp=TIE_LOW_BP,
        sensitivity_high_bp=TIE_HIGH_BP,
    )


def test_required_liability_rounds_half_up_at_an_exact_half(api):
    """
    A frozen gross of 1000 cents measured at 8205 bp gives exactly 820.5 cents, the
    one input where truncation, banker's rounding and round-half-up all disagree.
    The contract's rule sends the remaining half away from zero, so the liability is
    821 rather than 820.

    "Rounding is uniform: every division named in this document is followed by rounding to a whole number using the round-half-up rule — a remainder of exactly one half rounds away from zero, upward in magnitude."
    "The arithmetic must be carried out on exact rational or decimal values and rounded once at each point the specification names, never approximated through binary floating point."
    "Multiply each cohort's clamped rate by that cohort's weight, add those products together, divide by the total of all the weights, and round half up once to a whole number of basis points."
    "The estimate's own `required_liability_cents` is `outstanding_gross_ssp_cents_at_estimate` multiplied by `estimated_redemption_rate_bp`, divided by 10000, rounded half up; it is the liability this estimate measured, and it is deliberately distinct from the like-named figure a period computes at its close, which is re-measured against the lot balances as they stand at that later moment."

    Design: Corner/calculations/calc_required_liability_uses_round_half_up_at_exact_half
    """
    program, _cohort, period = _tie_fixture(api)

    estimate = _tie_estimate(api, program["id"], period["id"])
    assert_fields(
        estimate,
        method_applied=METHOD_COHORT_WEIGHTED,
        estimated_redemption_rate_bp=TIE_OBSERVED_BP,
        outstanding_points_at_estimate=1000,
        outstanding_gross_ssp_cents_at_estimate=TIE_GROSS_CENTS,
        required_liability_cents=TIE_REQUIRED_CENTS,
    )


def test_sensitivity_bands_are_each_rounded_half_up_independently(api):
    """
    All three scenarios land on an exact half against the frozen gross of 1000
    cents: 770.5, 820.5 and 870.5. Each is rounded on its own, giving 771, 821 and
    871 and a band range of 100 cents. Deriving the outer bands by adding a rounded
    delta onto the rounded base would drift, and the range would not be 100.

    "The response reports that frozen gross as `outstanding_gross_ssp_cents`, echoes the three scenarios as `low_bp`, `base_bp` and `high_bp` (respectively `sensitivity_low_bp`, the measured `estimated_redemption_rate_bp`, and `sensitivity_high_bp`), and gives `low_required_liability_cents`, `base_required_liability_cents` and `high_required_liability_cents` as the frozen gross multiplied by each of those three rates in turn, divided by 10000, each rounded half up **independently** — deriving the high band by adding a rounded delta onto the rounded base drifts and is wrong."
    "`band_range_cents` is the high band less the low band, and `memo_narrative` is echoed from the estimate."
    "Rounding is uniform: every division named in this document is followed by rounding to a whole number using the round-half-up rule — a remainder of exactly one half rounds away from zero, upward in magnitude."

    Design: Corner/calculations/calc_required_liability_uses_round_half_up_at_exact_half
    """
    program, _cohort, period = _tie_fixture(api)
    estimate = _tie_estimate(api, program["id"], period["id"])

    bands = assert_ok(api.get_sensitivity(estimate["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        bands,
        outstanding_gross_ssp_cents=TIE_GROSS_CENTS,
        low_bp=TIE_LOW_BP,
        base_bp=TIE_OBSERVED_BP,
        high_bp=TIE_HIGH_BP,
        low_required_liability_cents=TIE_LOW_CENTS,
        base_required_liability_cents=TIE_REQUIRED_CENTS,
        high_required_liability_cents=TIE_HIGH_CENTS,
        band_range_cents=TIE_BAND_RANGE_CENTS,
        memo_narrative=TIE_MEMO,
    )


def test_sensitivity_bands_stay_on_the_frozen_snapshot_after_a_later_issuance(api):
    """
    A second lot is issued after the estimate was measured, so a band recomputed
    from live data would grow. Because the band is drawn from the estimate's own
    frozen gross, the second read is identical to the first, and the estimate's
    stored figures have not moved either.

    "Audit support reads the frozen snapshot rather than live data."
    "A `LoyaltyAccountant` or a `Controller` may ask one estimate for its sensitivity bands, and the answer is computed from the estimate's own `outstanding_gross_ssp_cents_at_estimate` — never from a fresh measurement — which is what makes the band reproducible long after the underlying lots have moved."
    "Measurement runs at creation and is frozen thereafter."

    Design: Corner/calculations/calc_required_liability_uses_round_half_up_at_exact_half
    """
    program, cohort, period = _tie_fixture(api)
    estimate = _tie_estimate(api, program["id"], period["id"])
    first_read = assert_ok(api.get_sensitivity(estimate["id"], ACCOUNTANT_HEADERS))

    second_member = fixtures.new_member(
        api, program["id"], cohort["id"], tier=TIER_SILVER
    )
    fixtures.issue_lot(api, second_member["id"], period["id"], TIE_SILVER_BASE_POINTS)

    second_read = assert_ok(api.get_sensitivity(estimate["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        second_read,
        outstanding_gross_ssp_cents=first_read["outstanding_gross_ssp_cents"],
        low_required_liability_cents=first_read["low_required_liability_cents"],
        base_required_liability_cents=first_read["base_required_liability_cents"],
        high_required_liability_cents=first_read["high_required_liability_cents"],
        band_range_cents=first_read["band_range_cents"],
    )
    assert_fields(
        second_read,
        outstanding_gross_ssp_cents=TIE_GROSS_CENTS,
        band_range_cents=TIE_BAND_RANGE_CENTS,
    )
    reread = assert_ok(api.get_estimate(estimate["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        reread,
        outstanding_points_at_estimate=1000,
        outstanding_gross_ssp_cents_at_estimate=TIE_GROSS_CENTS,
        required_liability_cents=TIE_REQUIRED_CENTS,
    )


def test_tier_uplift_rounds_half_up_at_an_exact_half_point(api):
    """
    250 base points at the SILVER multiplier of 10300 bp give exactly 257.5 points,
    which rounds up to 258. Every downstream figure inherits that whole number: a
    gross of 258 cents at 1000 millicents, a reserve on the exact half 64.5 that
    rounds up to 65, and a deferral of 193.

    "`tier_points` is `base_points` multiplied by `tier_multiplier_bp_at_issue`, divided by 10000, and rounded half up to a whole number of points."
    "`gross_ssp_cents` is `points_issued` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`breakage_reserve_cents` is `gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."
    "`tier_benefit_expense_cents` is the difference between `tier_points` and `base_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up — and is therefore 0 for a `BASE` member."

    Design: Corner/calculations/calc_required_liability_uses_round_half_up_at_exact_half
    """
    program, cohort, period = _tie_fixture(api)
    silver = fixtures.new_member(api, program["id"], cohort["id"], tier=TIER_SILVER)

    lot = fixtures.issue_lot(api, silver["id"], period["id"], TIE_SILVER_BASE_POINTS)
    assert_fields(
        lot,
        tier_points=TIE_SILVER_TIER_POINTS,
        points_issued=TIE_SILVER_TIER_POINTS,
        points_remaining=TIE_SILVER_TIER_POINTS,
        gross_ssp_cents=TIE_SILVER_GROSS_CENTS,
        breakage_reserve_cents=TIE_SILVER_RESERVE_CENTS,
        deferred_revenue_cents=TIE_SILVER_DEFERRED_CENTS,
        tier_benefit_expense_cents=TIE_SILVER_TIER_EXPENSE_CENTS,
        promo_expense_cents=0,
    )
    assert_lot_split(lot)


def _three_lot_fixture(api):
    """
    One member holding three 1000-point lots issued on three consecutive days, so
    first-in-first-out consumption is unambiguous.
    """
    program, cohorts = _activated_program(
        api,
        ssp_millicents_per_point=SSP_1200,
        breakage_method=BREAKAGE_METHOD_COHORT_WEIGHTED,
        historical_redemption_rate_bp=HISTORICAL_RATE_BP,
    )
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"], tier=TIER_BASE)
    period = fixtures.new_period(api, program["id"])
    lots = []
    for day in ("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"):
        fixtures.set_clock(api, day)
        lots.append(fixtures.issue_lot(api, member["id"], period["id"], 1000))
    return program, period, member, lots


def test_fully_redeemed_lot_leaves_the_estimate_input_set(api):
    """
    Three 1000-point lots are reduced to two by a redemption that consumes the
    oldest one exactly. The estimate that follows must weigh 2000 points and freeze
    a gross of 2400 cents — the surviving two lots only — giving a liability of 1968
    rather than the 2952 a stale three-lot input set would produce.

    "The candidate set is built from the programme's cohorts that carry a non-zero weight, where a cohort's **weight** is the total `points_remaining` over the lots held by that cohort's members whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`."
    "Lots that are `FULLY_REDEEMED`, `EXPIRED` or `ESCHEATED` contribute nothing — neither to a weight nor to any gross figure."
    "A lot that was `OUTSTANDING` and gives up exactly its `points_remaining` moves `OUTSTANDING → FULLY_REDEEMED`, with `points_remaining` set to 0, one `ALLOCATION` row appended, and its `version` incremented by 1."
    "The candidates are walked in order of `issued_at` ascending and then `created_at` ascending — never by identifier — so a lot recorded later but carrying an earlier issuance instant is still consumed first."
    "`outstanding_gross_ssp_cents_at_estimate` is the sum, over that same lot set, of each lot's `remaining_gross_ssp_cents`, with each lot rounded first and the rounded amounts then added."

    Design: Corner/calculations/calc_estimate_input_set_excludes_fully_redeemed_lots
    """
    program, period, member, lots = _three_lot_fixture(api)
    fixtures.allocated_redemption(api, member["id"], period["id"], 1000)

    oldest = assert_ok(api.get_point_lot(lots[0]["id"], ACCOUNTANT_HEADERS))
    assert_fields(oldest, lifecycle_state=LOT_FULLY_REDEEMED, points_remaining=0)
    for survivor in lots[1:]:
        still_there = assert_ok(api.get_point_lot(survivor["id"], ACCOUNTANT_HEADERS))
        assert_fields(
            still_there, lifecycle_state=LOT_OUTSTANDING, points_remaining=1000
        )
    assert_fields(
        assert_ok(api.get_member(member["id"], ACCOUNTANT_HEADERS)),
        point_balance=FILTERED_POINTS,
    )

    estimate = fixtures.draft_estimate(api, program["id"], period["id"])
    assert_fields(
        estimate,
        estimated_redemption_rate_bp=C1_OBSERVED_BP,
        outstanding_points_at_estimate=FILTERED_POINTS,
        outstanding_gross_ssp_cents_at_estimate=FILTERED_GROSS_CENTS,
        required_liability_cents=FILTERED_REQUIRED_CENTS,
    )


def test_estimate_refused_once_every_lot_is_fully_redeemed(api):
    """
    Redeeming the whole balance leaves the cohort with no weight at all, so a second
    estimate cannot be measured and is refused outright rather than measured at zero.
    The first estimate survives the refusal, so exactly one estimate remains on file.

    "If no candidate cohort carries any outstanding points, the estimate cannot be measured and the request is rejected with `ERR_NO_OUTSTANDING_POINTS`."
    "Lots that are `FULLY_REDEEMED`, `EXPIRED` or `ESCHEATED` contribute nothing — neither to a weight nor to any gross figure."

    Design: Corner/calculations/calc_estimate_input_set_excludes_fully_redeemed_lots
    """
    program, period, member, lots = _three_lot_fixture(api)
    fixtures.allocated_redemption(api, member["id"], period["id"], 1000)
    first = fixtures.draft_estimate(api, program["id"], period["id"])

    fixtures.allocated_redemption(api, member["id"], period["id"], FILTERED_POINTS)
    for lot in lots:
        assert_fields(
            assert_ok(api.get_point_lot(lot["id"], ACCOUNTANT_HEADERS)),
            lifecycle_state=LOT_FULLY_REDEEMED,
            points_remaining=0,
        )
    assert_fields(
        assert_ok(api.get_member(member["id"], ACCOUNTANT_HEADERS)), point_balance=0
    )

    assert_error(
        api.create_estimate(
            program["id"],
            factories.estimate_payload(period["id"]),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.NO_OUTSTANDING_POINTS,
    )
    assert_page(
        api.list_estimates(ACCOUNTANT_HEADERS, program_id=program["id"]),
        expected_ids=[first["id"]],
        total_count=1,
    )


def _carry_forward_fixture(api):
    """
    A partner billed at 900 millicents per issued point under a 3000-cent minimum
    invoice, with two consecutive periods to bill and one 2000-point partner lot in
    the first of them.
    """
    program, cohorts = _activated_program(
        api,
        ssp_millicents_per_point=SSP_1200,
        historical_redemption_rate_bp=HISTORICAL_RATE_BP,
    )
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"], tier=TIER_BASE)
    first = fixtures.new_period(api, program["id"])
    second = fixtures.new_period(
        api,
        program["id"],
        period_code=PERIOD_SEP_CODE,
        start_at=PERIOD_SEP_START,
        end_at=PERIOD_SEP_END,
    )
    agreement = fixtures.new_agreement(
        api,
        program["id"],
        issuance_rate_millicents_per_point=PARTNER_ISSUANCE_RATE,
        redemption_rate_millicents_per_point=PARTNER_REDEMPTION_RATE,
        settlement_lag_days=PARTNER_LAG_DAYS,
        net_settlement_enabled=False,
        min_invoice_cents=CARRY_MIN_INVOICE_CENTS,
    )
    fixtures.issue_lot(
        api,
        member["id"],
        first["id"],
        CARRY_BASE_POINTS,
        partner_agreement_id=agreement["id"],
    )
    return program, member, first, second, agreement


def test_candidate_below_the_minimum_invoice_is_deferred_whole(api):
    """
    2000 partner-issued points at 900 millicents give a receivable of 1800 cents,
    and with nothing carried in the candidate is 1800 — short of the 3000-cent
    minimum. Nothing is billed: the whole candidate becomes the deferred remainder
    on both the statement and the agreement, the due date is the period's end plus
    30 whole days, and issuing the statement adds nothing to what the partner owes.

    "`partner_issued_points` is the sum of `points_issued` over the matching lots, with every `lifecycle_state` included — issuance is billable the moment it happens, and a later redemption, expiry or escheatment does not un-bill it."
    "From those two counts, `issuance_receivable_cents` is `partner_issued_points` multiplied by the agreement's `issuance_rate_millicents_per_point`, divided by 1000, rounded half up, and `redemption_payable_cents` is `partner_redeemed_points` multiplied by the agreement's `redemption_rate_millicents_per_point`, divided by 1000, rounded half up."
    "The statement then picks up whatever the previous statement was too small to bill: `carried_forward_cents` is a snapshot of the agreement's `deferred_below_minimum_cents` read before this statement overwrites it, and it is 0 on an agreement's first statement."
    "When the candidate is strictly less than the agreement's `min_invoice_cents`, `net_due_cents` is 0 and `deferred_below_minimum_cents` takes the whole candidate."
    "Either way the statement's `deferred_below_minimum_cents` is copied onto the agreement's own `deferred_below_minimum_cents`, where the next statement will find it as its carry-forward; the value is signed, a positive figure meaning the partner still owes the programme and a negative figure meaning the programme still owes the partner."
    "`due_date` is the period's `end_at` advanced by the agreement's `settlement_lag_days` whole days."
    "Issuing a statement is a `LoyaltyAccountant` action that moves it `DRAFT → ISSUED`, requires the owning agreement to be `ACTIVE`, sets `issued_at` to the clock reading, adds the statement's `net_due_cents` to the agreement's `outstanding_settlement_cents`, and increments both the agreement's and the statement's `version` by 1."

    Design: Corner/calculations/calc_partner_settlement_carry_forward_added_before_minimum_test
    """
    _program, _member, first, _second, agreement = _carry_forward_fixture(api)

    statement = fixtures.draft_statement(api, agreement["id"], first["id"])
    assert_fields(
        statement,
        partner_issued_points=CARRY_BASE_POINTS,
        partner_redeemed_points=0,
        issuance_receivable_cents=CARRY_RECEIVABLE_CENTS,
        redemption_payable_cents=0,
        carried_forward_cents=0,
        net_due_cents=0,
        deferred_below_minimum_cents=CARRY_RECEIVABLE_CENTS,
        due_date=PER1_DUE_DATE,
    )
    assert_statement_net(statement)
    assert_fields(
        assert_ok(api.get_agreement(agreement["id"], ACCOUNTANT_HEADERS)),
        deferred_below_minimum_cents=CARRY_RECEIVABLE_CENTS,
        outstanding_settlement_cents=0,
    )

    assert_ok(api.issue_statement(statement["id"], None, ACCOUNTANT_HEADERS))
    assert_fields(
        assert_ok(api.get_agreement(agreement["id"], ACCOUNTANT_HEADERS)),
        outstanding_settlement_cents=0,
    )


def test_carry_forward_is_added_before_the_minimum_invoice_test(api):
    """
    The second period bills another 1800 cents, which on its own would again fall
    short of the 3000-cent minimum and be deferred forever. Because the 1800 carried
    in from the first statement is added first, the candidate is 3600 and clears the
    threshold: the whole 3600 is billed, the deferred remainder returns to 0, and
    issuing the statement books 3600 onto what the partner owes.

    "The minimum-invoice threshold is applied to the candidate **after** the carry-forward has been added, never to the current period's legs alone — applying it earlier would strand the carry-forward forever."
    "Under `GROSS`, the billable candidate is `issuance_receivable_cents` plus `carried_forward_cents`."
    "Otherwise `net_due_cents` takes the candidate and `deferred_below_minimum_cents` is 0."
    "The statement then picks up whatever the previous statement was too small to bill: `carried_forward_cents` is a snapshot of the agreement's `deferred_below_minimum_cents` read before this statement overwrites it, and it is 0 on an agreement's first statement."
    "Measurement looks only at lots and events matching **both** the statement's `partner_agreement_id` and its `period_id`; anything with no partner agreement is never included."
    "`due_date` is the period's `end_at` advanced by the agreement's `settlement_lag_days` whole days."
    "Issuing a statement is a `LoyaltyAccountant` action that moves it `DRAFT → ISSUED`, requires the owning agreement to be `ACTIVE`, sets `issued_at` to the clock reading, adds the statement's `net_due_cents` to the agreement's `outstanding_settlement_cents`, and increments both the agreement's and the statement's `version` by 1."

    Design: Corner/calculations/calc_partner_settlement_carry_forward_added_before_minimum_test
    """
    _program, member, first, second, agreement = _carry_forward_fixture(api)
    fixtures.issued_statement(api, agreement["id"], first["id"])

    fixtures.set_clock(api, "2026-09-05T00:00:00Z")
    fixtures.issue_lot(
        api,
        member["id"],
        second["id"],
        CARRY_BASE_POINTS,
        partner_agreement_id=agreement["id"],
    )

    statement = fixtures.draft_statement(api, agreement["id"], second["id"])
    assert_fields(
        statement,
        partner_issued_points=CARRY_BASE_POINTS,
        issuance_receivable_cents=CARRY_RECEIVABLE_CENTS,
        carried_forward_cents=CARRY_RECEIVABLE_CENTS,
        net_due_cents=CARRY_BILLED_CENTS,
        deferred_below_minimum_cents=0,
        due_date=PER2_DUE_DATE,
    )
    assert_statement_net(statement)
    assert_fields(
        assert_ok(api.get_agreement(agreement["id"], ACCOUNTANT_HEADERS)),
        deferred_below_minimum_cents=0,
    )

    assert_ok(api.issue_statement(statement["id"], None, ACCOUNTANT_HEADERS))
    assert_fields(
        assert_ok(api.get_agreement(agreement["id"], ACCOUNTANT_HEADERS)),
        outstanding_settlement_cents=CARRY_BILLED_CENTS,
    )


def _projection_fixture(api, historical_rate_bp=HISTORICAL_RATE_BP):
    """
    A programme holding one 4999-point GOLD lot priced at 1200 millicents, the
    single lot every change-order projection here is measured over.
    """
    program, cohorts = _activated_program(
        api,
        ssp_millicents_per_point=SSP_1200,
        historical_redemption_rate_bp=historical_rate_bp,
        per_issuance_point_cap=POINT_CAP,
    )
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"], tier=TIER_GOLD)
    period = fixtures.new_period(api, program["id"])
    lot = fixtures.issue_lot(api, member["id"], period["id"], PROJ_BASE_POINTS)
    return program, period, lot


def test_ssp_change_projection_rounds_each_leg_before_subtracting(api):
    """
    A repricing from 1200 to 1500 millicents reprices the same single lot from 5999
    to 7499 cents while the elasticity drops the redemption rate from 7500 to 7100
    bp. Rounding each leg first gives 5324 less 4499, a delta of 825; rounding the
    difference of the two unrounded products instead gives 824, so the discipline is
    visible in the answer.

    "`baseline_redemption_rate_bp` is 10000 basis points less the programme's `current_breakage_rate_bp`."
    "`projected_redemption_rate_bp` is that baseline plus `behavior_elasticity_bp`, clamped into the band from 200 through 9800 inclusive, so a large elasticity saturates rather than escaping the band."
    "Both gross figures are measured over the **same** lot set — the programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` — but at different prices: `baseline_outstanding_gross_ssp_cents` sums each lot's `points_remaining` multiplied by that lot's own `ssp_millicents_per_point_at_issue` divided by 1000, rounded half up per lot, while `projected_outstanding_gross_ssp_cents` reprices the identical lot set at `new_ssp_millicents_per_point` for an `SSP_CHANGE` and is otherwise identical to the baseline."
    "`projected_liability_delta_cents` is then the projected gross multiplied by the projected rate divided by 10000 and rounded half up, **less** the baseline gross multiplied by the baseline rate divided by 10000 and rounded half up: each leg is rounded independently and only then subtracted, since rounding the difference of the two unrounded products gives a different figure."
    "The order is born in `state` `MODELED`, the programme is untouched, and the projection is **never** re-measured when the order is later approved or applied."

    Design: Corner/calculations/calc_change_order_projection_two_legs_rounded_independently
    """
    program, _period, lot = _projection_fixture(api)
    assert_fields(
        lot,
        points_issued=PROJ_POINTS_ISSUED,
        points_remaining=PROJ_POINTS_ISSUED,
        ssp_millicents_per_point_at_issue=SSP_1200,
        remaining_gross_ssp_cents=PROJ_BASELINE_GROSS_CENTS,
    )

    order = fixtures.modeled_change_order(
        api,
        program["id"],
        "2026-12-01T00:00:00Z",
        change_type=CHANGE_SSP,
        behavior_elasticity_bp=PROJ_ELASTICITY_BP,
        new_point_expiry_days=None,
        new_ssp_millicents_per_point=PROJ_NEW_SSP,
    )
    assert_fields(
        order,
        state=ORDER_MODELED,
        baseline_redemption_rate_bp=PROJ_BASELINE_RATE_BP,
        projected_redemption_rate_bp=PROJ_RATE_BP,
        baseline_outstanding_gross_ssp_cents=PROJ_BASELINE_GROSS_CENTS,
        projected_outstanding_gross_ssp_cents=PROJ_GROSS_CENTS,
        projected_liability_delta_cents=PROJ_DELTA_CENTS,
        applied_at=None,
    )
    assert PROJ_LIABILITY_CENTS - PROJ_BASELINE_LIABILITY_CENTS == PROJ_DELTA_CENTS
    assert_fields(
        assert_ok(api.get_program(program["id"], ACCOUNTANT_HEADERS)),
        ssp_millicents_per_point=SSP_1200,
        current_breakage_rate_bp=SEEDED_BREAKAGE_RATE_BP,
    )


def test_projected_rate_saturates_at_the_ceiling(api):
    """
    A baseline of 7500 bp plus an elasticity of 2500 bp lands exactly on 10000, above
    the 9800 ceiling, so the projection saturates at 9800 rather than escaping the
    band. The change type leaves the price alone, so both grosses stay at 5999 and
    the whole delta of 1380 cents comes from the rate.

    "`projected_redemption_rate_bp` is that baseline plus `behavior_elasticity_bp`, clamped into the band from 200 through 9800 inclusive, so a large elasticity saturates rather than escaping the band."
    "For `EXPIRY_DAYS_CHANGE` and `TIER_MULTIPLIER_CHANGE` the two grosses are equal, so the delta is driven purely by `behavior_elasticity_bp`."
    "`projected_liability_delta_cents` is then the projected gross multiplied by the projected rate divided by 10000 and rounded half up, **less** the baseline gross multiplied by the baseline rate divided by 10000 and rounded half up: each leg is rounded independently and only then subtracted, since rounding the difference of the two unrounded products gives a different figure."
    "The order is born in `state` `MODELED`, the programme is untouched, and the projection is **never** re-measured when the order is later approved or applied."

    Design: Corner/calculations/calc_change_order_projection_rate_clamped_to_floor_and_ceiling
    """
    program, _period, _lot = _projection_fixture(api)

    order = fixtures.modeled_change_order(
        api,
        program["id"],
        "2027-01-01T00:00:00Z",
        change_type=CHANGE_EXPIRY_DAYS,
        behavior_elasticity_bp=CEILING_ELASTICITY_BP,
        new_point_expiry_days=NEW_EXPIRY_DAYS,
    )
    assert_fields(
        order,
        state=ORDER_MODELED,
        baseline_redemption_rate_bp=PROJ_BASELINE_RATE_BP,
        projected_redemption_rate_bp=RATE_CEILING_BP,
        baseline_outstanding_gross_ssp_cents=PROJ_BASELINE_GROSS_CENTS,
        projected_outstanding_gross_ssp_cents=PROJ_BASELINE_GROSS_CENTS,
        projected_liability_delta_cents=CEILING_DELTA_CENTS,
    )
    assert CEILING_LIABILITY_CENTS - PROJ_BASELINE_LIABILITY_CENTS == CEILING_DELTA_CENTS
    assert_fields(
        assert_ok(api.get_program(program["id"], ACCOUNTANT_HEADERS)),
        point_expiry_days=730,
    )


def test_projected_rate_saturates_at_the_floor(api):
    """
    Against a programme whose baseline redemption rate is 4000 bp, the most negative
    elasticity the contract accepts drives the raw projection to -1000, below the 200
    bp floor, so it saturates at 200. Both grosses stay at 5999 because the change
    type leaves the price alone, and the delta of 120 less 2400 is negative.

    "`projected_redemption_rate_bp` is that baseline plus `behavior_elasticity_bp`, clamped into the band from 200 through 9800 inclusive, so a large elasticity saturates rather than escaping the band."
    "The order also carries `behavior_elasticity_bp`, from -5000 through 5000, expressing how the change is expected to move redemption behaviour, and `effective_at`, which must be at or after the clock reading at the moment of creation."
    "The delta may be negative."
    "For `EXPIRY_DAYS_CHANGE` and `TIER_MULTIPLIER_CHANGE` the two grosses are equal, so the delta is driven purely by `behavior_elasticity_bp`."

    Design: Corner/calculations/calc_change_order_projection_rate_clamped_to_floor_and_ceiling
    """
    program, _period, _lot = _projection_fixture(
        api, historical_rate_bp=FLOOR_HISTORICAL_RATE_BP
    )

    order = fixtures.modeled_change_order(
        api,
        program["id"],
        "2027-02-01T00:00:00Z",
        change_type=CHANGE_TIER_MULTIPLIER,
        behavior_elasticity_bp=FLOOR_ELASTICITY_BP,
        new_point_expiry_days=None,
        new_tier_multiplier_bp=dict(NEW_TIER_MULTIPLIER_BP),
    )
    assert_fields(
        order,
        state=ORDER_MODELED,
        baseline_redemption_rate_bp=FLOOR_BASELINE_RATE_BP,
        projected_redemption_rate_bp=RATE_FLOOR_BP,
        baseline_outstanding_gross_ssp_cents=PROJ_BASELINE_GROSS_CENTS,
        projected_outstanding_gross_ssp_cents=PROJ_BASELINE_GROSS_CENTS,
        projected_liability_delta_cents=FLOOR_DELTA_CENTS,
    )
    assert FLOOR_LIABILITY_CENTS - FLOOR_BASELINE_LIABILITY_CENTS == FLOOR_DELTA_CENTS


def _escheat_fixture(api):
    """
    A Delaware programme whose disclosure threshold sits one cent above the accrual
    the first expiry will raise, holding one 5000-point lot that expires in August
    2028 and one 100-point lot that expires a month later, with an OPEN period ready
    to receive each sweep.
    """
    program, cohorts = _activated_program(
        api,
        rule_overrides={
            "state_code": STATE_DE,
            "expiry_permitted": True,
            "min_dormancy_days": 730,
            "escheatment_required": True,
            "escheat_rate_bp": ESCHEAT_RATE_BP,
        },
        ssp_millicents_per_point=SSP_1200,
        historical_redemption_rate_bp=HISTORICAL_RATE_BP,
        per_issuance_point_cap=POINT_CAP,
        escheat_disclosure_threshold_cents=ESCHEAT_THRESHOLD_CENTS,
    )
    first = fixtures.new_period(api, program["id"])
    second = fixtures.new_period(
        api,
        program["id"],
        period_code=PERIOD_SEP_CODE,
        start_at=PERIOD_SEP_START,
        end_at=PERIOD_SEP_END,
    )
    sweep_one = fixtures.new_period(
        api,
        program["id"],
        period_code="2028-08",
        start_at="2028-08-01T00:00:00Z",
        end_at="2028-09-01T00:00:00Z",
    )
    sweep_two = fixtures.new_period(
        api,
        program["id"],
        period_code="2028-09",
        start_at="2028-09-01T00:00:00Z",
        end_at="2028-10-01T00:00:00Z",
    )
    big_holder = fixtures.new_member(
        api, program["id"], cohorts[0]["id"], tier=TIER_BASE, state_code=STATE_DE
    )
    small_holder = fixtures.new_member(
        api, program["id"], cohorts[0]["id"], tier=TIER_BASE, state_code=STATE_DE
    )
    fixtures.set_clock(api, LOT1_ISSUED_AT)
    big_lot = fixtures.issue_lot(api, big_holder["id"], first["id"], 5000)
    fixtures.set_clock(api, LOT2_ISSUED_AT)
    small_lot = fixtures.issue_lot(api, small_holder["id"], second["id"], 100)
    return {
        "program": program,
        "sweep_one_period": sweep_one,
        "sweep_two_period": sweep_two,
        "big_holder": big_holder,
        "small_holder": small_holder,
        "big_lot": big_lot,
        "small_lot": small_lot,
    }


def test_escheat_accrual_one_cent_short_of_the_threshold_does_not_latch(api):
    """
    The first sweep expires a 5000-point lot worth 6000 cents gross, releasing its
    4500-cent deferral into the swept period and accruing 3600 cents of escheatment.
    The programme's disclosure threshold is 3601, so the running total stops one cent
    short and the disclosure flag stays false — a flag latched on a greater-than-zero
    accrual rather than on reaching the threshold would already be true here.

    "Candidates are the programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` and whose `expires_at` is at or before the clock reading; the comparison is inclusive, so a lot whose `expires_at` is exactly the current clock reading is eligible while one an instant later is not."
    "`expired_gross_ssp_cents` is captured from the lot's current `remaining_gross_ssp_cents`, and the released deferral is captured from its current `remaining_deferred_cents`."
    "The captured released deferral is added to the **swept** period's `expiry_released_cents`, and the lot's `version` increments by 1."
    "When the governing rule's `escheatment_required` is true, `escheated_cents` is `expired_gross_ssp_cents` multiplied by the rule's `escheat_rate_bp`, divided by 10000, rounded half up; `lifecycle_state` moves `EXPIRED → ESCHEATED`, which is terminal for the lifecycle dimension; the amount is added both to the swept period's `escheat_accrual_cents` and to the programme's `total_escheat_accrual_cents`; and a third link fires from that accrual — once the programme's `total_escheat_accrual_cents` reaches `escheat_disclosure_threshold_cents`, the boundary being inclusive, `escheat_disclosure_required` latches to true and is never cleared again, even if a later reopen reduces other figures."
    "A member whose `status` is `ACTIVE`, whose `point_balance` is 0 after the pass, and whose `dormancy_days` is at least 730 — two years since `last_activity_at` — moves `ACTIVE → DORMANT` with `version` incremented by 1."
    "`issued_at` takes the current logical clock reading, and `expires_at` is set to `issued_at` advanced by the programme's `point_expiry_days` whole days."

    Design: Corner/calculations/calc_escheat_accrual_below_disclosure_threshold_does_not_latch
    """
    fixture = _escheat_fixture(api)
    assert_fields(fixture["big_lot"], expires_at=LOT1_EXPIRES_AT)
    assert_fields(fixture["small_lot"], expires_at=LOT2_EXPIRES_AT)

    fixtures.set_clock(api, SWEEP_1_CLOCK)
    assert_ok(
        api.run_expiry_sweep(
            fixture["sweep_one_period"]["id"], None, ACCOUNTANT_HEADERS
        )
    )

    assert_fields(
        assert_ok(api.get_point_lot(fixture["big_lot"]["id"], ACCOUNTANT_HEADERS)),
        lifecycle_state=LOT_ESCHEATED,
        points_remaining=0,
        expired_gross_ssp_cents=LOT1_GROSS_CENTS,
        escheated_cents=LOT1_ESCHEATED_CENTS,
    )
    assert_fields(
        assert_ok(
            api.get_period(fixture["sweep_one_period"]["id"], ACCOUNTANT_HEADERS)
        ),
        expiry_released_cents=LOT1_DEFERRED_CENTS,
        escheat_accrual_cents=LOT1_ESCHEATED_CENTS,
    )
    assert_fields(
        assert_ok(api.get_program(fixture["program"]["id"], ACCOUNTANT_HEADERS)),
        total_escheat_accrual_cents=LOT1_ESCHEATED_CENTS,
        escheat_disclosure_required=False,
    )
    assert_fields(
        assert_ok(api.get_member(fixture["big_holder"]["id"], ACCOUNTANT_HEADERS)),
        status=MEMBER_DORMANT,
        point_balance=0,
    )
    assert_fields(
        assert_ok(api.get_member(fixture["small_holder"]["id"], ACCOUNTANT_HEADERS)),
        status=MEMBER_ACTIVE,
    )
    assert_fields(
        assert_ok(api.get_point_lot(fixture["small_lot"]["id"], ACCOUNTANT_HEADERS)),
        lifecycle_state=LOT_OUTSTANDING,
        points_remaining=100,
        expired_gross_ssp_cents=0,
        escheated_cents=0,
    )


def test_escheat_accrual_reaching_the_threshold_latches_disclosure(api):
    """
    A second sweep a month later expires the 100-point lot, accruing another 72 cents
    and carrying the programme's running total to 3672 — past the 3601 threshold — so
    the disclosure flag latches. The second sweep books its own release and accrual
    into its own period, leaving the first swept period's figures alone.

    "When the governing rule's `escheatment_required` is true, `escheated_cents` is `expired_gross_ssp_cents` multiplied by the rule's `escheat_rate_bp`, divided by 10000, rounded half up; `lifecycle_state` moves `EXPIRED → ESCHEATED`, which is terminal for the lifecycle dimension; the amount is added both to the swept period's `escheat_accrual_cents` and to the programme's `total_escheat_accrual_cents`; and a third link fires from that accrual — once the programme's `total_escheat_accrual_cents` reaches `escheat_disclosure_threshold_cents`, the boundary being inclusive, `escheat_disclosure_required` latches to true and is never cleared again, even if a later reopen reduces other figures."
    "Lots already `EXPIRED` or `ESCHEATED` are never re-swept, and `settlement_state` is irrelevant to eligibility."
    "The captured released deferral is added to the **swept** period's `expiry_released_cents`, and the lot's `version` increments by 1."

    Design: Corner/calculations/calc_escheat_accrual_below_disclosure_threshold_does_not_latch
    """
    fixture = _escheat_fixture(api)
    fixtures.set_clock(api, SWEEP_1_CLOCK)
    assert_ok(
        api.run_expiry_sweep(
            fixture["sweep_one_period"]["id"], None, ACCOUNTANT_HEADERS
        )
    )

    fixtures.set_clock(api, SWEEP_2_CLOCK)
    assert_ok(
        api.run_expiry_sweep(
            fixture["sweep_two_period"]["id"], None, ACCOUNTANT_HEADERS
        )
    )

    assert_fields(
        assert_ok(api.get_point_lot(fixture["small_lot"]["id"], ACCOUNTANT_HEADERS)),
        lifecycle_state=LOT_ESCHEATED,
        points_remaining=0,
        expired_gross_ssp_cents=LOT2_GROSS_CENTS,
        escheated_cents=LOT2_ESCHEATED_CENTS,
    )
    assert_fields(
        assert_ok(
            api.get_period(fixture["sweep_two_period"]["id"], ACCOUNTANT_HEADERS)
        ),
        expiry_released_cents=LOT2_DEFERRED_CENTS,
        escheat_accrual_cents=LOT2_ESCHEATED_CENTS,
    )
    assert_fields(
        assert_ok(
            api.get_period(fixture["sweep_one_period"]["id"], ACCOUNTANT_HEADERS)
        ),
        expiry_released_cents=LOT1_DEFERRED_CENTS,
        escheat_accrual_cents=LOT1_ESCHEATED_CENTS,
    )
    assert_fields(
        assert_ok(api.get_program(fixture["program"]["id"], ACCOUNTANT_HEADERS)),
        total_escheat_accrual_cents=ESCHEAT_TOTAL_AFTER_BOTH_CENTS,
        escheat_disclosure_required=True,
    )


def test_tier_and_promotional_uplifts_are_expensed_on_their_own_deltas(api):
    """
    250 base points at the SILVER multiplier give 258 tier points, and the 10300 bp
    promotion lifts those to 266. Each uplift is expensed on its own delta of 8
    points, and each delta of 9.6 cents rounds up on its own to 10 — where expensing
    the combined 16-point delta in one shot would give 19 cents in total rather than
    20. The deferral of 239 cents, not the gross of 319, is what the period accrues.

    "The two uplifts are expensed separately, each measured on its own point delta at the snapshotted price."
    "`tier_benefit_expense_cents` is the difference between `tier_points` and `base_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up — and is therefore 0 for a `BASE` member."
    "`promo_expense_cents` is the difference between `points_issued` and `tier_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`points_issued` is the **already-rounded** `tier_points` multiplied by `promo_multiplier_bp`, divided by 10000, and rounded half up again."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."

    Design: Corner/calculations/calc_tier_and_promo_expense_attributed_to_own_point_delta
    """
    program, cohorts = _activated_program(
        api,
        ssp_millicents_per_point=SSP_1200,
        promo_multiplier_cap_bp=PROMO_CAP_BP,
        historical_redemption_rate_bp=HISTORICAL_RATE_BP,
    )
    member = fixtures.new_member(api, program["id"], cohorts[0]["id"], tier=TIER_SILVER)
    period = fixtures.new_period(api, program["id"])

    lot = fixtures.issue_lot(
        api,
        member["id"],
        period["id"],
        EXPENSE_BASE_POINTS,
        promo_multiplier_bp=EXPENSE_PROMO_BP,
    )
    assert_fields(
        lot,
        tier_multiplier_bp_at_issue=10300,
        promo_multiplier_bp=EXPENSE_PROMO_BP,
        tier_points=EXPENSE_TIER_POINTS,
        points_issued=EXPENSE_POINTS_ISSUED,
        points_remaining=EXPENSE_POINTS_ISSUED,
        gross_ssp_cents=EXPENSE_GROSS_CENTS,
        breakage_reserve_cents=EXPENSE_RESERVE_CENTS,
        deferred_revenue_cents=EXPENSE_DEFERRED_CENTS,
        tier_benefit_expense_cents=EXPENSE_TIER_LEG_CENTS,
        promo_expense_cents=EXPENSE_PROMO_LEG_CENTS,
    )
    assert_lot_split(lot)
    assert_fields(
        assert_ok(api.get_period(period["id"], ACCOUNTANT_HEADERS)),
        issuance_deferred_cents=EXPENSE_DEFERRED_CENTS,
    )
