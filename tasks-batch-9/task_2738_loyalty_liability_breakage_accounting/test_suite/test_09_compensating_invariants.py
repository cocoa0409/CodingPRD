"""
Compensation that is exact, not approximate.

Two operations in this contract undo an earlier one, and neither is allowed to
leave a residue. Reversing a redemption appends mirror journal rows rather than
editing history, so the lot's ledger identity holds at every instant and both
period accumulators return to zero. Reopening a period zeroes the close figures
and, because the programme's year-to-date recognised breakage is summed rather
than incremented, that programme-level figure returns to the exact value it held
before the close — even though the catch-up it booked was negative and the
breakage it recognised was therefore positive.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_allocation_seq_ascending,
    assert_envelope_array,
    assert_error,
    assert_fields,
    assert_null_fields,
    assert_ok,
    assert_page,
    assert_rollforward_ties,
)
from test_helpers.constants import (
    CLOCK_EPOCH,
    COHORT_C1_CODE,
    COHORT_C1_ENROLLMENT_END,
    COHORT_C1_ENROLLMENT_START,
    COHORT_C1_OBSERVED_RATE_BP,
    COHORT_C1_SAMPLE_SIZE,
    COHORT_C2_CODE,
    COHORT_C2_ENROLLMENT_END,
    COHORT_C2_ENROLLMENT_START,
    COHORT_C2_OBSERVED_RATE_BP,
    COHORT_C2_SAMPLE_SIZE,
    ENTRY_TYPE_ALLOCATION,
    ENTRY_TYPE_REVERSAL,
    ESTIMATE_APPROVED,
    ESTIMATE_SUPERSEDED,
    LOT_OUTSTANDING,
    LOT_PARTIALLY_REDEEMED,
    PERIOD_AUG_CODE,
    PERIOD_AUG_END,
    PERIOD_AUG_START,
    PERIOD_HARD_CLOSED,
    PERIOD_OPEN,
    PERIOD_SEP_CODE,
    PERIOD_SEP_END,
    PERIOD_SEP_START,
    PERIOD_SOFT_CLOSED,
    REDEMPTION_FULFILLED,
    REDEMPTION_REVERSED,
    STATE_TX,
    TIER_GOLD,
    TIER_SILVER,
)
from test_helpers.test_users import ACCOUNTANT_HEADERS, CONTROLLER_HEADERS

# ─── The programme both chains are built on ──────────────────────────────────
SEEDED_BREAKAGE_RATE_BP = 2500  # 10000 less historical_redemption_rate_bp 7500
C1_ADJUSTMENT_BP = 0
C2_ADJUSTMENT_BP = -300
C2_CLAMPED_RATE_BP = 200  # 400 + (-300) = 100, lifted to the 200 bp floor

# ─── August issuance ─────────────────────────────────────────────────────────
LOT1_BASE_POINTS = 4000  # GOLD 12500 bp, no promotion
LOT1_POINTS = 5000  # exactly the per-issuance cap, so no clamping is observable
LOT1_GROSS_CENTS = 6000
LOT1_DEFERRED_CENTS = 4500

LOT2_BASE_POINTS = 250  # SILVER 10300 bp, promotion 10300 bp
LOT2_PROMO_BP = 10300
LOT2_TIER_ONLY_POINTS = 258  # 250 * 10300 / 10000 = 257.5, half up
LOT2_POINTS = 266  # 258 * 10300 / 10000 = 265.74, half up
LOT2_GROSS_CENTS = 319
LOT2_DEFERRED_CENTS = 239

ISSUANCE_DEFERRED_CENTS = 4739  # 4500 + 239

# ─── August's approved estimate ──────────────────────────────────────────────
E1_MEMO = "Aug-2026 cohort-weighted estimate"
E1_BAND_LOW_BP = 7296
E1_BAND_HIGH_BP = 8296
E1_RATE_BP = 7796  # (8200*5000 + 200*266) / 5266 = 7796.28, half up
E1_BREAKAGE_BP = 2204
E1_OUTSTANDING_POINTS = 5266
E1_OUTSTANDING_GROSS_CENTS = 6319  # 6000 + 319
E1_REQUIRED_CENTS = 4926  # 6319 * 7796 / 10000 = 4926.29, half up

# ─── The redemption that gets reversed ───────────────────────────────────────
REDEEMED_POINTS = 3000
LINE_GROSS_CENTS = 3600  # 3000 * 1200 / 1000
PROVISIONAL_RELEASE_CENTS = 2700  # 3600 * (10000 - 2500) / 10000, the lot's own rate
FINAL_RELEASE_CENTS = 2807  # 3600 * 7796 / 10000 = 2806.56, half up
REMEASUREMENT_DELTA_CENTS = 107  # 2807 - 2700
LOT1_REMAINING_AFTER_REDEMPTION = 2000
NEGATED = -1
REVERSAL_REASON = "Catalogue order cancelled before shipment"

# ─── August's close ──────────────────────────────────────────────────────────
AUG_PRE_CATCHUP_CENTS = 1932  # 0 + 4739 - 2700 - 107 - 0
# The at-close gross is 2400 + 319, each lot rounded on its own before summation.
AUG_REQUIRED_CENTS = 2120  # 2719 * 7796 / 10000 = 2119.73, half up
AUG_CATCH_UP_CENTS = 188  # 2120 - 1932
AUG_CLOSING_CENTS = 2120
AUG_BREAKAGE_RECOGNIZED_CENTS = -188

# ─── September's approved re-estimate ────────────────────────────────────────
E2_MEMO = "Sep-2026 re-estimate after August redemptions"
E2_BAND_LOW_BP = 6761
E2_BAND_HIGH_BP = 7761
E2_RATE_BP = 7261  # (8200*2000 + 200*266) / 2266 = 7261.34, half up
E2_BREAKAGE_BP = 2739
E2_OUTSTANDING_POINTS = 2266
E2_OUTSTANDING_GROSS_CENTS = 2719
E2_REQUIRED_CENTS = 1974  # 2719 * 7261 / 10000 = 1974.27, half up

# ─── September's close, whose catch-up is negative ───────────────────────────
SEP_OPENING_CENTS = 2120
SEP_PRE_CATCHUP_CENTS = 2120  # no movement of its own
SEP_REQUIRED_CENTS = 1974
SEP_CATCH_UP_CENTS = -146  # 1974 - 2120
SEP_CLOSING_CENTS = 1974
SEP_BREAKAGE_RECOGNIZED_CENTS = 146  # a negative catch-up releases liability

YTD_BEFORE_SEPTEMBER_CLOSE_CENTS = -188
YTD_AFTER_SEPTEMBER_CLOSE_CENTS = -42  # -188 + 146

REOPEN_ZEROED_FIGURES = (
    "opening_liability_cents",
    "pre_catchup_liability_cents",
    "required_liability_cents",
    "catch_up_adjustment_cents",
    "closing_liability_cents",
    "breakage_recognized_cents",
    "approved_estimate_rate_bp",
)


# ─── Setup ───────────────────────────────────────────────────────────────────
def _two_cohort_program(api):
    """
    An ACTIVE programme with two enrolment vintages whose adjusted rates sit on
    opposite sides of the band, and one member in each.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)
    fixtures.new_state_expiry_rule(
        api,
        program["id"],
        state_code=STATE_TX,
        escheatment_required=False,
        escheat_rate_bp=0,
    )
    cohort_one = fixtures.new_cohort(
        api,
        program["id"],
        cohort_code=COHORT_C1_CODE,
        enrollment_start_date=COHORT_C1_ENROLLMENT_START,
        enrollment_end_date=COHORT_C1_ENROLLMENT_END,
        observed_redemption_rate_bp=COHORT_C1_OBSERVED_RATE_BP,
        sample_size=COHORT_C1_SAMPLE_SIZE,
        program_change_adjustment_bp=C1_ADJUSTMENT_BP,
    )
    cohort_two = fixtures.new_cohort(
        api,
        program["id"],
        cohort_code=COHORT_C2_CODE,
        enrollment_start_date=COHORT_C2_ENROLLMENT_START,
        enrollment_end_date=COHORT_C2_ENROLLMENT_END,
        observed_redemption_rate_bp=COHORT_C2_OBSERVED_RATE_BP,
        sample_size=COHORT_C2_SAMPLE_SIZE,
        program_change_adjustment_bp=C2_ADJUSTMENT_BP,
    )
    program = fixtures.activate(api, program["id"])
    assert_fields(program, current_breakage_rate_bp=SEEDED_BREAKAGE_RATE_BP)
    return {
        "program": program,
        "cohort_one": cohort_one,
        "cohort_two": cohort_two,
        "member_one": fixtures.new_member(
            api, program["id"], cohort_one["id"], tier=TIER_GOLD, state_code=STATE_TX
        ),
        "member_two": fixtures.new_member(
            api, program["id"], cohort_two["id"], tier=TIER_SILVER, state_code=STATE_TX
        ),
    }


def _august_ledger(api):
    """
    August open with two lots, an approved cohort-weighted estimate, and one
    catalogue redemption of 3000 points taken all the way to FULFILLED.
    """
    bundle = _two_cohort_program(api)
    program_id = bundle["program"]["id"]

    bundle["august"] = fixtures.new_period(
        api,
        program_id,
        period_code=PERIOD_AUG_CODE,
        start_at=PERIOD_AUG_START,
        end_at=PERIOD_AUG_END,
    )
    bundle["lot_one"] = fixtures.issue_lot(
        api,
        bundle["member_one"]["id"],
        bundle["august"]["id"],
        base_points=LOT1_BASE_POINTS,
    )
    bundle["lot_two"] = fixtures.issue_lot(
        api,
        bundle["member_two"]["id"],
        bundle["august"]["id"],
        base_points=LOT2_BASE_POINTS,
        promo_multiplier_bp=LOT2_PROMO_BP,
    )
    bundle["estimate_one"] = fixtures.approved_estimate(
        api,
        program_id,
        bundle["august"]["id"],
        memo_narrative=E1_MEMO,
        sensitivity_low_bp=E1_BAND_LOW_BP,
        sensitivity_high_bp=E1_BAND_HIGH_BP,
    )
    bundle["redemption"] = fixtures.fulfilled_redemption(
        api,
        bundle["member_one"]["id"],
        bundle["august"]["id"],
        points_requested=REDEEMED_POINTS,
    )
    return bundle


def _august_hard_closed(api):
    """August driven through the eight-step close and then sealed."""
    bundle = _august_ledger(api)
    fixtures.set_clock(api, PERIOD_AUG_END)
    fixtures.soft_close(api, bundle["august"]["id"])
    bundle["august"] = assert_ok(
        api.hard_close_period(bundle["august"]["id"], None, CONTROLLER_HEADERS)
    )
    return bundle


def _september_ready(api):
    """
    September open behind a sealed August, carrying its own approved re-estimate
    and no activity of its own, with the clock past its end.
    """
    bundle = _august_hard_closed(api)
    bundle["september"] = fixtures.new_period(
        api,
        bundle["program"]["id"],
        period_code=PERIOD_SEP_CODE,
        start_at=PERIOD_SEP_START,
        end_at=PERIOD_SEP_END,
    )
    bundle["estimate_two"] = fixtures.approved_estimate(
        api,
        bundle["program"]["id"],
        bundle["september"]["id"],
        memo_narrative=E2_MEMO,
        sensitivity_low_bp=E2_BAND_LOW_BP,
        sensitivity_high_bp=E2_BAND_HIGH_BP,
    )
    fixtures.set_clock(api, PERIOD_SEP_END)
    return bundle


def _lot_ledger_points(api, lot_id):
    """The signed sum of points_allocated over every row that touched one lot."""
    rows, _ = assert_envelope_array(api.list_lot_allocations(lot_id, ACCOUNTANT_HEADERS))
    assert_allocation_seq_ascending(rows)
    return sum(row["points_allocated"] for row in rows)


def _program_ytd(api, program_id):
    """The programme's derived year-to-date recognised breakage."""
    return assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))[
        "recognized_breakage_ytd_cents"
    ]


# ─── Reversal is append-only compensation ────────────────────────────────────
def test_reversal_appends_a_mirror_row_and_leaves_the_original_verbatim(api):
    """
    The single ALLOCATION row written when the redemption was allocated must still
    be readable unchanged after the reversal, alongside one appended REVERSAL row
    whose points, line gross, provisional release and final release are the exact
    negations of it. Because the negated values are copied rather than re-measured,
    the mirror row's final release is -2807 even though the programme rate that
    produced 2807 is still live. Filtering by entry_type isolates one row each way.

    "For every `ALLOCATION` row of the event, walked in ascending `allocation_seq` order, one compensating row is appended with `entry_type` `REVERSAL` and the same `allocation_seq` ordering, carrying `points_allocated`, `line_gross_ssp_cents` and `provisional_release_cents` as the exact negations of the original row's values, and — when the event had been fulfilled — `final_release_cents` negated as well."
    "Nothing is re-measured on reversal: the negated values are copied from the original rows, which is what makes the compensation exact."
    "The rows that consumed or restored one lot can be read as a sub-resource of that lot, and the rows belonging to one event can be read as a sub-resource of that event; both reads accept `entry_type` as a filter so an auditor can look at the original consumption alone or the compensating entries alone, and both return rows ordered by `allocation_seq` ascending then `created_at` ascending."

    Design: Difficulty/compensating_invariant/compensating_redemption_reverse_conserves_lot_points
    """
    bundle = _august_ledger(api)
    event_id = bundle["redemption"]["id"]
    lot_one_id = bundle["lot_one"]["id"]

    before, _ = assert_envelope_array(
        api.list_redemption_allocations(event_id, ACCOUNTANT_HEADERS)
    )
    assert len(before) == 1, f"Expected one ALLOCATION row, saw {len(before)}"
    original = before[0]
    assert_fields(
        original,
        entry_type=ENTRY_TYPE_ALLOCATION,
        redemption_event_id=event_id,
        point_lot_id=lot_one_id,
        allocation_seq=1,
        points_allocated=REDEEMED_POINTS,
        line_gross_ssp_cents=LINE_GROSS_CENTS,
        provisional_release_cents=PROVISIONAL_RELEASE_CENTS,
        final_release_cents=FINAL_RELEASE_CENTS,
    )
    assert_fields(bundle["redemption"], state=REDEMPTION_FULFILLED)

    reversed_event = assert_ok(
        api.reverse_redemption(
            event_id, factories.reversal_payload(REVERSAL_REASON), ACCOUNTANT_HEADERS
        )
    )
    assert_fields(
        reversed_event,
        state=REDEMPTION_REVERSED,
        reversal_reason=REVERSAL_REASON,
        version=bundle["redemption"]["version"] + 1,
    )

    after, meta = assert_envelope_array(
        api.list_redemption_allocations(event_id, ACCOUNTANT_HEADERS)
    )
    assert meta["total_count"] == 2, (
        "The original row must survive alongside the compensating row, so the event "
        f"should carry two ledger rows; saw {meta['total_count']}"
    )
    assert_allocation_seq_ascending(after)
    assert_fields(
        after[0],
        id=original["id"],
        entry_type=ENTRY_TYPE_ALLOCATION,
        point_lot_id=lot_one_id,
        points_allocated=REDEEMED_POINTS,
        line_gross_ssp_cents=LINE_GROSS_CENTS,
        provisional_release_cents=PROVISIONAL_RELEASE_CENTS,
        final_release_cents=FINAL_RELEASE_CENTS,
    )
    assert_fields(
        after[1],
        entry_type=ENTRY_TYPE_REVERSAL,
        redemption_event_id=event_id,
        point_lot_id=lot_one_id,
        points_allocated=NEGATED * REDEEMED_POINTS,
        line_gross_ssp_cents=NEGATED * LINE_GROSS_CENTS,
        provisional_release_cents=NEGATED * PROVISIONAL_RELEASE_CENTS,
        final_release_cents=NEGATED * FINAL_RELEASE_CENTS,
    )

    assert_page(
        api.list_redemption_allocations(
            event_id, ACCOUNTANT_HEADERS, entry_type=ENTRY_TYPE_ALLOCATION
        ),
        expected_ids=[original["id"]],
        total_count=1,
    )
    assert_page(
        api.list_redemption_allocations(
            event_id, ACCOUNTANT_HEADERS, entry_type=ENTRY_TYPE_REVERSAL
        ),
        expected_ids=[after[1]["id"]],
        total_count=1,
    )


def test_reversal_restores_the_lot_without_ever_touching_points_issued(api):
    """
    The journal identity — the signed sum of points_allocated over a lot's rows
    equals points_issued less points_remaining — must hold on both sides of the
    reversal: 3000 equals 5000 less 2000 beforehand, and 0 equals 5000 less 5000
    afterwards. points_issued stays at 5000 throughout, the lot walks
    PARTIALLY_REDEEMED back to OUTSTANDING, and its frozen issue-time breakage rate
    is not re-stamped from the programme's newer rate. The untouched sibling lot
    proves the restoration is scoped to the lots the event actually consumed.

    "Note that `points_issued` is never touched by any of this, which is precisely why the journal invariant holds at every instant: the sum of `points_allocated` across all of a lot's rows equals that lot's `points_issued` less its `points_remaining`."
    "A `PARTIALLY_REDEEMED` lot whose `points_remaining` equals `points_issued` after the restoration moves `PARTIALLY_REDEEMED → OUTSTANDING`."
    "Each consumed lot has its `points_remaining` restored by the reversed count and its `lifecycle_state` driven back, with its `version` incremented by 1 in each case."

    Design: Difficulty/compensating_invariant/compensating_redemption_reverse_conserves_lot_points
    """
    bundle = _august_ledger(api)
    lot_one_id = bundle["lot_one"]["id"]
    lot_two_id = bundle["lot_two"]["id"]

    consumed = assert_ok(api.get_point_lot(lot_one_id, ACCOUNTANT_HEADERS))
    assert_fields(
        consumed,
        lifecycle_state=LOT_PARTIALLY_REDEEMED,
        points_issued=LOT1_POINTS,
        points_remaining=LOT1_REMAINING_AFTER_REDEMPTION,
        gross_ssp_cents=LOT1_GROSS_CENTS,
        deferred_revenue_cents=LOT1_DEFERRED_CENTS,
        breakage_rate_bp_at_issue=SEEDED_BREAKAGE_RATE_BP,
        version=bundle["lot_one"]["version"] + 1,
    )
    assert _lot_ledger_points(api, lot_one_id) == (
        consumed["points_issued"] - consumed["points_remaining"]
    ), "The journal must already tie before the reversal"
    assert _lot_ledger_points(api, lot_one_id) == REDEEMED_POINTS

    assert_ok(
        api.reverse_redemption(
            bundle["redemption"]["id"],
            factories.reversal_payload(REVERSAL_REASON),
            ACCOUNTANT_HEADERS,
        )
    )

    restored = assert_ok(api.get_point_lot(lot_one_id, ACCOUNTANT_HEADERS))
    assert_fields(
        restored,
        lifecycle_state=LOT_OUTSTANDING,
        points_issued=LOT1_POINTS,
        points_remaining=LOT1_POINTS,
        gross_ssp_cents=LOT1_GROSS_CENTS,
        deferred_revenue_cents=LOT1_DEFERRED_CENTS,
        breakage_rate_bp_at_issue=SEEDED_BREAKAGE_RATE_BP,
        version=bundle["lot_one"]["version"] + 2,
    )
    assert _lot_ledger_points(api, lot_one_id) == 0, (
        "The compensating row must bring the lot's journal back to zero"
    )
    assert _lot_ledger_points(api, lot_one_id) == (
        restored["points_issued"] - restored["points_remaining"]
    )

    assert_fields(
        assert_ok(api.get_member(bundle["member_one"]["id"], ACCOUNTANT_HEADERS)),
        point_balance=LOT1_POINTS,
    )
    assert_fields(
        assert_ok(api.get_point_lot(lot_two_id, ACCOUNTANT_HEADERS)),
        lifecycle_state=LOT_OUTSTANDING,
        points_issued=LOT2_POINTS,
        points_remaining=LOT2_POINTS,
        gross_ssp_cents=LOT2_GROSS_CENTS,
        deferred_revenue_cents=LOT2_DEFERRED_CENTS,
        version=bundle["lot_two"]["version"],
    )
    assert LOT2_TIER_ONLY_POINTS < LOT2_POINTS, (
        "The two-step uplift must round twice, so the tier-only count is smaller"
    )


def test_reversal_unwinds_both_ledger_legs_and_restates_nothing_historical(api):
    """
    Allocation booked 2700 into the period's recognised redemption and fulfilment
    booked a further 107 into its re-measurement delta; the reversal must return
    both columns to exactly zero rather than netting them against each other or
    leaving a rounding residue. The deferral the issuances booked is untouched,
    because reversal reaches only the redemption legs. Nothing historical is
    restated: the approved estimate keeps its frozen snapshot and the programme
    keeps the rate that estimate installed. REVERSED is terminal, so a second
    reversal of the same event is refused even though its period is still open.

    "On the ledger side, reversal subtracts the event's `provisional_release_cents` from the period's `redemption_recognized_cents`, and — when the event had been fulfilled — also subtracts the event's `remeasurement_delta_cents` from the period's `remeasurement_delta_cents`."
    "Both legs are unwound, so the two period accumulators return to their exact pre-allocation values with no drift."
    "`REVERSED` is terminal for the event, and the event's `version` increments by 1."
    "**Current state is a legal source state for the requested transition** — `ERR_INVALID_STATE_TRANSITION` (409), on every action endpoint that drives a state machine."

    Design: Difficulty/compensating_invariant/compensating_redemption_reverse_conserves_lot_points
    """
    bundle = _august_ledger(api)
    period_id = bundle["august"]["id"]
    program_id = bundle["program"]["id"]

    assert_fields(
        assert_ok(api.get_period(period_id, CONTROLLER_HEADERS)),
        state=PERIOD_OPEN,
        issuance_deferred_cents=ISSUANCE_DEFERRED_CENTS,
        redemption_recognized_cents=PROVISIONAL_RELEASE_CENTS,
        remeasurement_delta_cents=REMEASUREMENT_DELTA_CENTS,
    )

    assert_ok(
        api.reverse_redemption(
            bundle["redemption"]["id"],
            factories.reversal_payload(REVERSAL_REASON),
            ACCOUNTANT_HEADERS,
        )
    )

    assert_fields(
        assert_ok(api.get_period(period_id, CONTROLLER_HEADERS)),
        state=PERIOD_OPEN,
        issuance_deferred_cents=ISSUANCE_DEFERRED_CENTS,
        redemption_recognized_cents=0,
        remeasurement_delta_cents=0,
        expiry_released_cents=0,
    )
    assert_fields(
        assert_ok(api.get_estimate(bundle["estimate_one"]["id"], CONTROLLER_HEADERS)),
        state=ESTIMATE_APPROVED,
        estimated_redemption_rate_bp=E1_RATE_BP,
        breakage_rate_bp=E1_BREAKAGE_BP,
        outstanding_points_at_estimate=E1_OUTSTANDING_POINTS,
        outstanding_gross_ssp_cents_at_estimate=E1_OUTSTANDING_GROSS_CENTS,
        required_liability_cents=E1_REQUIRED_CENTS,
        memo_narrative=E1_MEMO,
    )
    assert_fields(
        assert_ok(api.get_program(program_id, CONTROLLER_HEADERS)),
        current_breakage_rate_bp=E1_BREAKAGE_BP,
    )

    assert_error(
        api.reverse_redemption(
            bundle["redemption"]["id"],
            factories.reversal_payload(REVERSAL_REASON),
            ACCOUNTANT_HEADERS,
        ),
        ApiErrorId.INVALID_STATE_TRANSITION.value,
    )


# ─── Reopen compensates the close at the programme level ─────────────────────
def test_september_close_turns_a_negative_catch_up_into_positive_breakage(api):
    """
    September carries no activity of its own, so its whole catch-up comes from
    August's lots still being outstanding while the approved rate has fallen from
    7796 to 7261. The required balance re-measured at close is therefore lower than
    the balance carried forward, the catch-up is -146, and recognised breakage is
    its negation, +146 — a release rather than a top-up. That pushes the
    programme's year-to-date figure from -188 to -42, which is the sign convention
    most likely to be implemented backwards.

    "A period with no issuance, no redemption and no expiry still produces a non-zero `catch_up_adjustment_cents` whenever prior-period lots remain outstanding and the approved rate has moved since the last close."
    "`catch_up_adjustment_cents` is `required_liability_cents` less `pre_catchup_liability_cents`, and may be negative."
    "`breakage_recognized_cents` is the negation of `catch_up_adjustment_cents` — negative when the liability must be topped up and positive when it is released."
    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."
    "A period that is `HARD_CLOSED`, or already `OPEN`, is left entirely untouched."

    Design: Difficulty/compensating_invariant/compensating_period_reopen_conserves_program_recognized_breakage
    """
    bundle = _september_ready(api)
    program_id = bundle["program"]["id"]

    assert_fields(
        assert_ok(api.get_period(bundle["august"]["id"], CONTROLLER_HEADERS)),
        state=PERIOD_HARD_CLOSED,
        pre_catchup_liability_cents=AUG_PRE_CATCHUP_CENTS,
        required_liability_cents=AUG_REQUIRED_CENTS,
        catch_up_adjustment_cents=AUG_CATCH_UP_CENTS,
        closing_liability_cents=AUG_CLOSING_CENTS,
        breakage_recognized_cents=AUG_BREAKAGE_RECOGNIZED_CENTS,
        approved_estimate_rate_bp=E1_RATE_BP,
        reopen_count=0,
    )
    assert_fields(
        assert_ok(api.get_estimate(bundle["estimate_one"]["id"], CONTROLLER_HEADERS)),
        state=ESTIMATE_SUPERSEDED,
    )
    assert_fields(
        assert_ok(api.get_estimate(bundle["estimate_two"]["id"], CONTROLLER_HEADERS)),
        state=ESTIMATE_APPROVED,
        estimated_redemption_rate_bp=E2_RATE_BP,
        breakage_rate_bp=E2_BREAKAGE_BP,
        outstanding_points_at_estimate=E2_OUTSTANDING_POINTS,
        outstanding_gross_ssp_cents_at_estimate=E2_OUTSTANDING_GROSS_CENTS,
        required_liability_cents=E2_REQUIRED_CENTS,
    )
    assert_fields(
        assert_ok(api.get_program(program_id, CONTROLLER_HEADERS)),
        current_breakage_rate_bp=E2_BREAKAGE_BP,
        recognized_breakage_ytd_cents=YTD_BEFORE_SEPTEMBER_CLOSE_CENTS,
    )

    closed = fixtures.soft_close(api, bundle["september"]["id"])
    assert_fields(
        closed,
        state=PERIOD_SOFT_CLOSED,
        opening_liability_cents=SEP_OPENING_CENTS,
        issuance_deferred_cents=0,
        redemption_recognized_cents=0,
        remeasurement_delta_cents=0,
        expiry_released_cents=0,
        pre_catchup_liability_cents=SEP_PRE_CATCHUP_CENTS,
        required_liability_cents=SEP_REQUIRED_CENTS,
        catch_up_adjustment_cents=SEP_CATCH_UP_CENTS,
        closing_liability_cents=SEP_CLOSING_CENTS,
        breakage_recognized_cents=SEP_BREAKAGE_RECOGNIZED_CENTS,
        approved_estimate_rate_bp=E2_RATE_BP,
        reopen_count=0,
        version=bundle["september"]["version"] + 1,
    )
    assert_rollforward_ties(closed)
    assert closed["catch_up_adjustment_cents"] < 0 < closed["breakage_recognized_cents"], (
        "A negative catch-up must recognise positive breakage"
    )

    assert _program_ytd(api, program_id) == YTD_AFTER_SEPTEMBER_CLOSE_CENTS, (
        "August's -188 plus September's +146 must give -42"
    )
    assert C2_CLAMPED_RATE_BP < E2_RATE_BP < COHORT_C1_OBSERVED_RATE_BP, (
        "A weighted mean of the two clamped cohort rates must fall strictly between "
        "the floor-lifted 200 bp and the 8200 bp vintage"
    )


def test_reopening_september_returns_the_programme_figure_to_its_pre_close_value(api):
    """
    The reopen must zero all seven close figures on September and, because the
    programme's year-to-date recognised breakage is summed over closed periods
    rather than incremented in place, dropping September out of that set must land
    the programme back on exactly -188 — not -42 plus a correction, and not -334.
    August, already sealed, keeps every figure it closed with, and the estimate that
    backed September's close is not retracted.

    "The reopen is a full compensation: `opening_liability_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `breakage_recognized_cents`, `closing_liability_cents` and `approved_estimate_rate_bp` all reset to 0, `soft_closed_at` becomes null, `reopen_count` increments by 1 and `version` increments by 1."
    "Because the programme's `recognized_breakage_ytd_cents` only sums the periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`, dropping this period out of that set returns the programme-level figure to its exact pre-close value with zero drift."
    "The movement accumulators are deliberately **not** reset — they belong to the events that produced them, not to the close."

    Design: Difficulty/compensating_invariant/compensating_period_reopen_conserves_program_recognized_breakage
    """
    bundle = _september_ready(api)
    program_id = bundle["program"]["id"]
    september_id = bundle["september"]["id"]

    before_close = _program_ytd(api, program_id)
    assert before_close == YTD_BEFORE_SEPTEMBER_CLOSE_CENTS

    closed = fixtures.soft_close(api, september_id)
    assert _program_ytd(api, program_id) == YTD_AFTER_SEPTEMBER_CLOSE_CENTS

    reopened = assert_ok(api.reopen_period(september_id, None, CONTROLLER_HEADERS))
    assert_fields(
        reopened,
        state=PERIOD_OPEN,
        reopen_count=1,
        version=closed["version"] + 1,
        **{field: 0 for field in REOPEN_ZEROED_FIGURES},
    )
    assert_null_fields(reopened, "soft_closed_at")

    assert _program_ytd(api, program_id) == before_close, (
        "Reopening must return the programme figure to its exact pre-close value"
    )
    assert _program_ytd(api, program_id) == YTD_BEFORE_SEPTEMBER_CLOSE_CENTS

    assert_fields(
        assert_ok(api.get_period(bundle["august"]["id"], CONTROLLER_HEADERS)),
        state=PERIOD_HARD_CLOSED,
        closing_liability_cents=AUG_CLOSING_CENTS,
        breakage_recognized_cents=AUG_BREAKAGE_RECOGNIZED_CENTS,
        reopen_count=0,
    )
    assert_fields(
        assert_ok(api.get_estimate(bundle["estimate_two"]["id"], CONTROLLER_HEADERS)),
        state=ESTIMATE_APPROVED,
    )
    assert_fields(
        assert_ok(api.get_program(program_id, CONTROLLER_HEADERS)),
        current_breakage_rate_bp=E2_BREAKAGE_BP,
    )
    assert_fields(
        assert_ok(api.get_point_lot(bundle["lot_one"]["id"], ACCOUNTANT_HEADERS)),
        lifecycle_state=LOT_PARTIALLY_REDEEMED,
        points_remaining=LOT1_REMAINING_AFTER_REDEMPTION,
    )
    assert_fields(
        assert_ok(api.get_point_lot(bundle["lot_two"]["id"], ACCOUNTANT_HEADERS)),
        lifecycle_state=LOT_OUTSTANDING,
        points_remaining=LOT2_POINTS,
    )


def test_close_and_reopen_can_cycle_twice_with_no_drift_before_the_budget_bites(api):
    """
    Because the compensation is exact rather than approximate, closing and
    reopening September repeatedly must land on the same two programme figures each
    time — -42 while closed, -188 while open — with no accumulation. The reopen
    budget is two, so the third reopen is refused and September is left standing in
    SOFT_CLOSED with its close figures and the programme's -42 intact, which shows
    the refusal is not a partial compensation.

    "A `Controller` may reopen a soft-closed period, `SOFT_CLOSED → OPEN`, provided `reopen_count` is below 2 (otherwise `ERR_REOPEN_LIMIT_EXCEEDED`)."
    "Because the programme's `recognized_breakage_ytd_cents` only sums the periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`, dropping this period out of that set returns the programme-level figure to its exact pre-close value with zero drift."
    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."

    Design: Difficulty/compensating_invariant/compensating_period_reopen_conserves_program_recognized_breakage
    """
    bundle = _september_ready(api)
    program_id = bundle["program"]["id"]
    september_id = bundle["september"]["id"]
    expected_version = bundle["september"]["version"]

    for expected_reopen_count in (1, 2):
        closed = fixtures.soft_close(api, september_id)
        expected_version += 1
        assert_fields(
            closed,
            state=PERIOD_SOFT_CLOSED,
            opening_liability_cents=SEP_OPENING_CENTS,
            pre_catchup_liability_cents=SEP_PRE_CATCHUP_CENTS,
            required_liability_cents=SEP_REQUIRED_CENTS,
            catch_up_adjustment_cents=SEP_CATCH_UP_CENTS,
            closing_liability_cents=SEP_CLOSING_CENTS,
            breakage_recognized_cents=SEP_BREAKAGE_RECOGNIZED_CENTS,
            approved_estimate_rate_bp=E2_RATE_BP,
            reopen_count=expected_reopen_count - 1,
            version=expected_version,
        )
        assert_rollforward_ties(closed)
        assert _program_ytd(api, program_id) == YTD_AFTER_SEPTEMBER_CLOSE_CENTS

        reopened = assert_ok(api.reopen_period(september_id, None, CONTROLLER_HEADERS))
        expected_version += 1
        assert_fields(
            reopened,
            state=PERIOD_OPEN,
            reopen_count=expected_reopen_count,
            version=expected_version,
            **{field: 0 for field in REOPEN_ZEROED_FIGURES},
        )
        assert_null_fields(reopened, "soft_closed_at")
        assert _program_ytd(api, program_id) == YTD_BEFORE_SEPTEMBER_CLOSE_CENTS

    third_close = fixtures.soft_close(api, september_id)
    expected_version += 1
    assert_fields(
        third_close,
        state=PERIOD_SOFT_CLOSED,
        reopen_count=2,
        closing_liability_cents=SEP_CLOSING_CENTS,
        breakage_recognized_cents=SEP_BREAKAGE_RECOGNIZED_CENTS,
        version=expected_version,
    )

    assert_error(
        api.reopen_period(september_id, None, CONTROLLER_HEADERS),
        ApiErrorId.REOPEN_LIMIT_EXCEEDED.value,
    )
    assert_fields(
        assert_ok(api.get_period(september_id, CONTROLLER_HEADERS)),
        state=PERIOD_SOFT_CLOSED,
        reopen_count=2,
        closing_liability_cents=SEP_CLOSING_CENTS,
        breakage_recognized_cents=SEP_BREAKAGE_RECOGNIZED_CENTS,
        approved_estimate_rate_bp=E2_RATE_BP,
        version=expected_version,
    )
    assert _program_ytd(api, program_id) == YTD_AFTER_SEPTEMBER_CLOSE_CENTS
