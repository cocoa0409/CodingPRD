"""Monthly billing: provisional preview vs final invoice, pinned rounding
order, tiered volume discount, and the cancellation penalty notice bands."""
from test_helpers import (
    api_client,
    book_slot_in,
    file_flight_log,
    issue_invoice,
    make_client_headers,
    schedule_slot,
    set_clock,
    setup_operation,
    validate_success,
)
from test_helpers.fixtures import FINANCE


def _billing_preview(api, campaign_id, period="2026-08"):
    resp = api.get_billing_preview(campaign_id, FINANCE,
                                   params={"period_yyyy_mm": period})
    return validate_success(resp, expected_status=200)


class TestProvisionalVsFinalBilling:
    """Same campaign, same period, same flown data: the preview counts
    un-flown slots at planned hours and excludes penalties/credits; the
    final invoice counts only FLOWN slots and includes both."""

    def test_preview_counts_booked_slot_at_planned_hours(self, api):
        """PRD §3.8: "the billing preview for a period returns the same four
        figures — `flight_subtotal_cents`, `cancellation_penalty_cents`,
        `make_good_applied_cents`, and `total_cents` — but computed
        provisionally, counting slots still in `BOOKED` or `SCHEDULED` at
        their `planned_duration_hours` alongside the actual `hobbs_hours` of
        `FLOWN` slots, and never including penalties or credit applications.
        The final invoice, by contrast, counts only `FLOWN` slots and
        includes both penalties and credits."
        PRD §3.8: "when the period's total hobbs hours are twenty or fewer
        the discount is zero percent".

        Setup: S1 FLOWN with 1.5 hobbs hours at 30,000c/h (line 45,000),
        S2 still BOOKED at 2 planned hours (60,000). Preview subtotal is
        45,000 + 60,000 = 105,000 (3.5 hours, no discount); the final
        invoice counts only the FLOWN line: 45,000.

        Design: Difficulty/dual_variant_calc/flight_billing_provisional_vs_final
        """
        sc = setup_operation(base_code="KPV1")
        s1 = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                          planned_duration_hours=2)
        book_slot_in(sc, planned_start="2026-08-13T16:00:00Z",
                     planned_duration_hours=2)  # S2: stays BOOKED, never flown
        schedule_slot(s1["id"])
        file_flight_log(s1["id"], hobbs_out=100.0, hobbs_in=101.5)

        preview = _billing_preview(api, sc["campaign"]["id"])
        assert preview["flight_subtotal_cents"] == 105000, (
            f"preview must add S2's 2 planned hours at 30000c/h, got "
            f"{preview['flight_subtotal_cents']}"
        )
        assert preview["cancellation_penalty_cents"] == 0
        assert preview["make_good_applied_cents"] == 0
        assert preview["total_cents"] == 105000

        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["flight_subtotal_cents"] == 45000, (
            f"final invoice counts only FLOWN slots, got "
            f"{invoice['flight_subtotal_cents']}"
        )
        assert invoice["cancellation_penalty_cents"] == 0
        assert invoice["make_good_applied_cents"] == 0
        assert invoice["total_cents"] == 45000
        assert preview["flight_subtotal_cents"] != invoice["flight_subtotal_cents"]

    def test_preview_never_includes_penalties(self, api):
        """PRD §3.8: the preview is "computed provisionally, counting slots
        still in `BOOKED` or `SCHEDULED` at their `planned_duration_hours`
        alongside the actual `hobbs_hours` of `FLOWN` slots, and never
        including penalties or credit applications. The final invoice, by
        contrast, counts only `FLOWN` slots and includes both penalties and
        credits."
        PRD §3.8: "Notice under twenty-four hours incurs fifty percent,
        rounded the same way."

        Setup: S1 FLOWN (1.5 hobbs hours, 45,000c), S2 cancelled by the
        client 12 hours before takeoff (2 planned hours at 30,000c/h ->
        penalty 30,000). The preview reports penalty 0; the invoice reports
        30,000.

        Design: Difficulty/dual_variant_calc/flight_billing_provisional_vs_final
        """
        sc = setup_operation(base_code="KPV2", date_local="2026-08-15",
                             window_start="2026-08-15T14:00:00Z",
                             window_end="2026-08-15T18:00:00Z")
        s1 = book_slot_in(sc, planned_start="2026-08-15T14:00:00Z",
                          planned_duration_hours=1)
        s2 = book_slot_in(sc, planned_start="2026-08-15T16:00:00Z",
                          planned_duration_hours=2)
        schedule_slot(s1["id"])
        file_flight_log(s1["id"], hobbs_out=100.0, hobbs_in=101.5)
        set_clock("2026-08-15T04:00:00Z")  # 12h before S2's 16:00 start
        validate_success(
            api_client.cancel_slot_by_client(
                s2["id"], make_client_headers(sc["client"]["id"])),
            expected_status=200)

        preview = _billing_preview(api, sc["campaign"]["id"])
        assert preview["flight_subtotal_cents"] == 45000
        assert preview["cancellation_penalty_cents"] == 0, (
            "preview never includes penalties (PRD §3.8), got "
            f"{preview['cancellation_penalty_cents']}"
        )
        assert preview["make_good_applied_cents"] == 0
        assert preview["total_cents"] == 45000

        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["flight_subtotal_cents"] == 45000
        assert invoice["cancellation_penalty_cents"] == 30000, (
            f"12h notice incurs 50% of 60000 planned value, got "
            f"{invoice['cancellation_penalty_cents']}"
        )
        assert invoice["total_cents"] == 75000


class TestPinnedRoundingOrder:

    def test_fractional_cent_line_rounds_before_discount(self, api):
        """PRD §3.8: "each line is the log's `hobbs_hours` multiplied by the
        assigned aircraft's `hourly_rate_cents`, rounded half-up to a whole
        cent before any summation" and "The `flight_subtotal_cents` is the
        sum of the per-line amounts, multiplied by one minus the discount
        fraction, rounded half-up to a whole cent — the discount factor
        itself is never rounded, and the per-line rounding strictly precedes
        the discount rounding."
        PRD §3.8: "when the period's total hobbs hours are twenty or fewer
        the discount is zero percent".

        0.7 hours at 33,333c/h is 23,333.1 cents; the per-line round half-up
        yields 23,333 and no tier applies.

        Design: Difficulty/combinatorial_formula/flight_billing_nested_rounding_order
        """
        sc = setup_operation(base_code="KRND1", hourly_rate_cents=33333)
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=1)
        schedule_slot(slot["id"])
        file_flight_log(slot["id"], hobbs_out=100.0, hobbs_in=100.7)
        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["flight_subtotal_cents"] == 23333, (
            f"round_half_up(0.7 * 33333) = 23333, got "
            f"{invoice['flight_subtotal_cents']}"
        )
        assert invoice["total_cents"] == 23333

    def test_half_cent_line_rounds_up(self, api):
        """PRD §3.8: "each line is the log's `hobbs_hours` multiplied by the
        assigned aircraft's `hourly_rate_cents`, rounded half-up to a whole
        cent before any summation".

        0.5 hours at 33,333c/h is exactly 16,666.5 cents; half-up rounding
        yields 16,667 (half-even would yield 16,666).

        Design: Difficulty/combinatorial_formula/flight_billing_nested_rounding_order
        """
        sc = setup_operation(base_code="KRND2", hourly_rate_cents=33333)
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=1)
        schedule_slot(slot["id"])
        file_flight_log(slot["id"], hobbs_out=100.0, hobbs_in=100.5)
        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["flight_subtotal_cents"] == 16667, (
            f"round_half_up(0.5 * 33333 = 16666.5) must be 16667, got "
            f"{invoice['flight_subtotal_cents']}"
        )
        assert invoice["total_cents"] == 16667


class TestCancellationPenaltyBands:

    def test_partial_and_late_bands_sum_on_invoice(self, api):
        """PRD §3.8: "Notice of at least seventy-two hours incurs no penalty
        ... Notice of at least twenty-four hours but under seventy-two incurs
        twenty-five percent of the planned value, rounded half-up per slot,
        with the twenty-four-hour boundary also inclusive. Notice under
        twenty-four hours incurs fifty percent, rounded the same way. The
        `cancellation_penalty_cents` is the sum of these per-slot penalties."

        Two 2-hour slots at 30,000c/h (planned value 60,000 each): one
        cancelled at 48 hours notice (25% -> 15,000), one at 12 hours
        (50% -> 30,000); the invoice penalty total is 45,000.

        Design: Difficulty/combinatorial_formula/cancellation_penalty_partial_vs_late_band
        """
        sc = setup_operation(base_code="KPEN", date_local="2026-08-15",
                             window_start="2026-08-15T14:00:00Z",
                             window_end="2026-08-15T18:00:00Z")
        s1 = book_slot_in(sc, planned_start="2026-08-15T14:00:00Z",
                          planned_duration_hours=2)
        s2 = book_slot_in(sc, planned_start="2026-08-15T16:00:00Z",
                          planned_duration_hours=2)
        set_clock("2026-08-13T14:00:00Z")  # exactly 48h before S1
        validate_success(api_client.cancel_slot_by_client(
            s1["id"], make_client_headers(sc["client"]["id"])),
            expected_status=200)
        set_clock("2026-08-15T04:00:00Z")  # exactly 12h before S2
        validate_success(api_client.cancel_slot_by_client(
            s2["id"], make_client_headers(sc["client"]["id"])),
            expected_status=200)
        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["cancellation_penalty_cents"] == 45000, (
            f"25% of 60000 (48h notice) + 50% of 60000 (12h notice) = "
            f"45000, got {invoice['cancellation_penalty_cents']}"
        )
        assert invoice["flight_subtotal_cents"] == 0
        assert invoice["total_cents"] == 45000

    def test_exactly_24h_notice_incurs_partial_penalty(self, api):
        """PRD §3.8: "Notice of at least twenty-four hours but under
        seventy-two incurs twenty-five percent of the planned value, rounded
        half-up per slot, with the twenty-four-hour boundary also
        inclusive."

        Cancellation exactly 24 hours before takeoff lands in the 25% band.

        Design: Difficulty/combinatorial_formula/cancellation_penalty_partial_vs_late_band
        """
        sc = setup_operation(base_code="KP24")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=2)
        set_clock("2026-08-12T15:00:00Z")  # exactly 24h before
        validate_success(api_client.cancel_slot_by_client(
            slot["id"], make_client_headers(sc["client"]["id"])),
            expected_status=200)
        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["cancellation_penalty_cents"] == 15000, (
            f"24h notice is inclusive in the 25% band: 25% of 60000 = "
            f"15000, got {invoice['cancellation_penalty_cents']}"
        )

    def test_exactly_72h_notice_incurs_zero_penalty(self, api):
        """PRD §3.8: "Notice of at least seventy-two hours incurs no penalty,
        and the boundary is inclusive: exactly seventy-two hours means
        zero."

        Cancellation exactly 72 hours before takeoff bills nothing.

        Design: Difficulty/boundary_precision_check/cancellation_exactly_72h_notice_zero_penalty
        """
        sc = setup_operation(base_code="KP72")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=2)
        set_clock("2026-08-10T15:00:00Z")  # exactly 72h before
        validate_success(api_client.cancel_slot_by_client(
            slot["id"], make_client_headers(sc["client"]["id"])),
            expected_status=200)
        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["cancellation_penalty_cents"] == 0, (
            f"72h notice is inclusive in the zero band, got "
            f"{invoice['cancellation_penalty_cents']}"
        )
        assert invoice["total_cents"] == 0

    def test_one_second_under_72h_notice_incurs_partial_penalty(self, api):
        """PRD §3.8: "Notice of at least seventy-two hours incurs no penalty,
        and the boundary is inclusive: exactly seventy-two hours means zero.
        Notice of at least twenty-four hours but under seventy-two incurs
        twenty-five percent of the planned value, rounded half-up per slot".

        Cancellation 71h59m59s before takeoff falls under seventy-two hours
        and lands in the 25% band.

        Design: Difficulty/boundary_precision_check/cancellation_exactly_72h_notice_zero_penalty
        """
        sc = setup_operation(base_code="KP71")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=2)
        set_clock("2026-08-10T15:00:01Z")  # 71h59m59s before
        validate_success(api_client.cancel_slot_by_client(
            slot["id"], make_client_headers(sc["client"]["id"])),
            expected_status=200)
        invoice = issue_invoice(sc["campaign"]["id"])
        assert invoice["cancellation_penalty_cents"] == 15000, (
            f"under-72h notice incurs 25% of 60000 = 15000, got "
            f"{invoice['cancellation_penalty_cents']}"
        )
