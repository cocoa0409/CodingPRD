"""Judgment money: per-diem rounding order and zero-day floor (PRD 3.6)."""
from test_helpers import (
    ApiErrorId,
    CLERK_B,
    assert_instant_equal,
    create_judgment_payload,
    enter_judgment,
    setup_case_hearing_concluded,
    setup_judgment_entered,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestJudgmentInterestPerDiemRounding:
    """Depth instance: round the per-diem FIRST, then multiply by days."""

    def test_per_diem_rounded_before_multiplying(self, api):
        """PRD 3.6: "The per-diem interest is the principal multiplied by
        the jurisdiction's annual rate — ten percent in CA, six percent in TX,
        eight percent in OH — divided by 365, and that per-diem amount is
        rounded half-up to a whole cent before anything else happens; the
        interest_cents is then that rounded per-diem amount multiplied by the
        days overdue."

        Design: Difficulty/combinatorial_formula/judgment_interest_per_diem_rounding
        """
        ctx = setup_case_hearing_concluded("CA")
        # Principal 100034, CA rate 0.10: per-diem raw 27.4068 -> round 27.
        # Entered 2026-06-20; due 2026-06-10 -> 10 days overdue -> 270.
        judgment = enter_judgment(
            ctx, rent_awarded_cents=100033, damages_cents=1,
            late_fee_cents=0, court_costs_cents=0,
            oldest_unpaid_due_date="2026-06-10",
        )
        assert judgment["interest_cents"] == 270, (
            "round_half_up(100034 * 0.10 / 365) = 27; 27 x 10 = 270 "
            "(multiply-then-round would give 274)")
        assert judgment["total_awarded_cents"] == 100304
        assert judgment["outstanding_balance_cents"] == 100304

    def test_total_summed_in_pinned_order_and_appeal_deadline(self, api):
        """PRD 3.6: "The total_awarded_cents is the sum of rent, damages,
        late fees, court costs, and interest, added in exactly that order" and
        "computes the appeal_deadline as entered_at plus the jurisdictional
        appeal window — 5 days in CA".

        Design: Difficulty/combinatorial_formula/judgment_interest_per_diem_rounding
        """
        ctx = setup_case_hearing_concluded("CA")
        judgment = enter_judgment(
            ctx, rent_awarded_cents=100033, damages_cents=1,
            late_fee_cents=0, court_costs_cents=0,
            oldest_unpaid_due_date="2026-06-10",
        )
        assert judgment["total_awarded_cents"] == 100033 + 1 + 0 + 0 + 270
        # Entered at 2026-06-20T12:00:00Z, CA appeal window 5 days.
        assert_instant_equal(judgment["appeal_deadline"], "2026-06-25T12:00:00Z")


class TestInterestZeroWhenDueEqualsEntryDate:
    """Corner instance: days_overdue floors at zero."""

    def test_zero_days_overdue_yields_zero_interest(self, api):
        """PRD 3.6: "The days overdue are the calendar days between
        oldest_unpaid_due_date and the date of entry, floored at zero so a
        due date after entry yields none."

        Design: Corner/calculations/interest_zero_when_due_equals_entry_date
        """
        ctx = setup_case_hearing_concluded("CA")
        judgment = enter_judgment(
            ctx, rent_awarded_cents=77777, damages_cents=333,
            late_fee_cents=0, court_costs_cents=0,
            oldest_unpaid_due_date="2026-06-20",
        )
        assert judgment["interest_cents"] == 0
        assert judgment["total_awarded_cents"] == 77777 + 333

    def test_future_due_date_yields_zero_interest(self, api):
        """PRD 3.6: "The days overdue are the calendar days between
        oldest_unpaid_due_date and the date of entry, floored at zero so a
        due date after entry yields none."

        Design: Corner/calculations/interest_zero_when_due_equals_entry_date
        """
        ctx = setup_case_hearing_concluded("CA")
        # Due date AFTER the entry date (2026-06-20): floor at zero.
        judgment = enter_judgment(
            ctx, rent_awarded_cents=50000, damages_cents=0,
            late_fee_cents=0, court_costs_cents=0,
            oldest_unpaid_due_date="2026-06-21",
        )
        assert judgment["interest_cents"] == 0
        assert judgment["total_awarded_cents"] == 50000
