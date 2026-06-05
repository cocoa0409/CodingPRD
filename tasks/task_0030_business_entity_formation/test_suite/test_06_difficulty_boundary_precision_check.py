"""Difficulty Rule 6 — boundary_precision_check.

Two boundary checks:
  (a) BOI deadline inclusivity on day-90 vs day-91 (FORMATION grace).
  (b) ZERO revenue_band on franchise tax — TX/ZERO yields 0 cents.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_active_llc,
    create_draft_annual_report,
    file_annual_report,
    create_draft_boi_disclosure,
    make_filer_headers,
)


class TestBOIDeadlineInclusivityBoundary:
    """PRD §3.11: 90-day FORMATION grace, inclusive on the deadline second.
    formed_at = 2026-01-01T00:00:00Z → deadline = 2026-04-01T00:00:00Z.
    A submit at the deadline second is on time; one second past is rejected.
    """

    def test_boi_submit_at_day_90_23_59_59_succeeds_inclusive(self, api):
        """PRD §3.11: "The deadline comparison is inclusive on the deadline second
        — a submission landing at exactly the deadline second is on time."
        PRD §3.11: "When the `triggering_event` is `FORMATION`, the deadline base is
        the parent's `formed_at` and the grace window is 90 whole days."
        PRD §3.11: "the deadline is the base instant plus the appropriate number
        of days."

        Design: Difficulty/boundary_precision_check/bpc_boi_deadline_inclusive_on_day_90_vs_day_91
        """
        set_clock("2026-01-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="NOV LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        boi = create_draft_boi_disclosure(be, triggering_event="FORMATION")
        # PRD §3.11: deadline = formed_at (2026-01-01T00:00:00Z) + 90 days
        # = 2026-04-01T00:00:00Z. The comparison is inclusive on the deadline
        # second, so a submission at exactly 2026-04-01T00:00:00Z is on time.
        set_clock("2026-04-01T00:00:00Z")
        res = api.submit_boi_disclosure(boi["id"], make_filer_headers(be["id"]))
        body = validate_success(res, 200)
        assert body["status"] == "SUBMITTED"

    def test_boi_submit_one_second_past_deadline_returns_past_deadline(self, api):
        """PRD §3.11: "A submit attempted past the deadline is rejected with
        `ERR_BOI_PAST_DEADLINE`."

        Design: Difficulty/boundary_precision_check/bpc_boi_deadline_inclusive_on_day_90_vs_day_91
        """
        set_clock("2026-01-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="OSC LLC", formation_state_code="DE", revenue_band="ZERO"
        )
        boi = create_draft_boi_disclosure(be, triggering_event="FORMATION")
        # PRD §3.11: deadline = base + 90 days = 2026-04-01T00:00:00Z (literal
        # arithmetic on the base instant). One second past that deadline is
        # 2026-04-01T00:00:01Z.
        set_clock("2026-04-01T00:00:01Z")
        res = api.submit_boi_disclosure(boi["id"], make_filer_headers(be["id"]))
        validate_error(res, "ERR_BOI_PAST_DEADLINE")


class TestZeroRevenueBandFranchiseTaxBoundary:
    """PRD §3.8: TX base is 0 cents across types; TX ZERO band yields 0 cents.
    """

    def test_tx_llc_zero_band_yields_zero_cents_franchise_tax(self, api):
        """PRD §3.8: "Texas charges nothing"
        PRD §3.8: "`ZERO` and `MICRO` are 1.00x (multiplier 100)"
        PRD §3.8: "The final `franchise_tax_amount_cents` is the larger of the raw
        amount and the state's minimum floor."

        Design: Difficulty/boundary_precision_check/bpc_zero_revenue_band_yields_minimum_floor_on_annual_report
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="PAPA TX LLC", formation_state_code="TX", revenue_band="ZERO"
        )
        ar = create_draft_annual_report(be, 2024)
        filed = file_annual_report(be, ar["id"])
        # TX LLC ZERO: base=0, mult=100 -> raw=0; floor=0; result=0.
        assert filed["franchise_tax_amount_cents"] == 0
        assert filed["status"] == "FILED"

    def test_tx_llc_zero_band_yields_zero_late_fee_on_time(self, api):
        """PRD §3.9: "When the current clock UTC at filing is at or before that
        deadline, `late_fee_cents` is 0 and no accrual occurs."

        Design: Difficulty/boundary_precision_check/bpc_zero_revenue_band_yields_minimum_floor_on_annual_report
        """
        set_clock("2025-03-01T00:00:00Z")
        be, _ = setup_active_llc(
            legal_name="PAPA TX2 LLC", formation_state_code="TX", revenue_band="ZERO"
        )
        ar = create_draft_annual_report(be, 2024)
        filed = file_annual_report(be, ar["id"])
        assert filed["late_fee_cents"] == 0
