"""Two contended timelines with deliberately opposite interval semantics.

A confirming bank's line is measured as peak concurrent occupancy over half-open windows
with an aggregate appetite, so a window that starts on the date another one ends inherits a
free line. A credit's amendment timeline is compared pairwise over closed windows widened
by a two-day cooling-off buffer, so a start that merely touches the buffered end collides.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    api_client,
    approved_credit,
    assert_facility_ledger,
    consent_to_amendment,
    create_bank,
    credit_officer_headers,
    draft_amendment,
    factories,
    issue_amendment,
    issue_credit,
    issued_credit,
    list_amendment_rows,
    request_confirmation,
    set_clock,
    setup_parties,
    trade_finance_officer_headers,
    TRADE_FINANCE_OFFICER_2,
)

SIGHT_TEN_MILLION = {
    "amount_cents": 10000000,
    "available_by": "SIGHT_PAYMENT",
    "tenor_days": 0,
    "tolerance_pct": 0,
    "presentation_period_days": 21,
}


def _read_bank(bank_id):
    return validate_success(api_client.get_bank(bank_id, credit_officer_headers()))


class TestConfirmingLinePeakOccupancyOverHalfOpenWindows:
    """One 20,000,000 line, four credits, and windows that touch but do not overlap."""

    def _four_credits(self):
        parties = setup_parties(
            facility={"limit_cents": 100000000},
            beneficiary={"country_code": "VN"},
        )
        confirming_bank = create_bank(
            country_code="SG",
            country_risk_score=35,
            credit_rating="A",
            confirmation_appetite_cents=20000000,
        )
        early = issued_credit(
            parties,
            None,
            expiry_date="2026-09-19",
            latest_shipment_date="2026-09-05",
            **SIGHT_TEN_MILLION,
        )
        middle = issued_credit(
            parties,
            None,
            expiry_date="2026-10-20",
            latest_shipment_date="2026-10-05",
            **SIGHT_TEN_MILLION,
        )
        third = issued_credit(
            parties,
            None,
            expiry_date="2026-10-20",
            latest_shipment_date="2026-10-05",
            **SIGHT_TEN_MILLION,
        )
        late = approved_credit(
            parties,
            None,
            expiry_date="2026-11-19",
            latest_shipment_date="2026-11-05",
            **SIGHT_TEN_MILLION,
        )
        return parties, confirming_bank["id"], early, middle, third, late

    def _attempt_request(self, credit_id, bank_id):
        return api_client.create_confirmation_request(
            credit_id,
            factories.confirmation_request_payload(bank_id),
            trade_finance_officer_headers(),
        )

    def test_two_overlapping_windows_may_fill_the_line_to_the_cent(self, clock):
        """The confirmation window is half-open, and a peak equal to the appetite is taken.

        PRD 3.4: "When the measurement is an admission check for a new request, the
        candidate credit's own occupation is included in the events before the sweep runs,
        and the request is refused with `ERR_CONFIRMING_LINE_WINDOW_FULL` (409) only when
        the resulting peak is **strictly greater** than the bank's
        `confirmation_appetite_cents`; a peak exactly equal to the appetite is admitted."

        Design: Difficulty/resource_temporal_overlap/confirming_line_peak_occupancy_half_open_window_with_capacity
        """
        _parties, bank_id, early, middle, _third, _late = self._four_credits()
        assert early.credit["confirmation_window_start"] == "2026-08-10"
        assert early.credit["confirmation_window_end"] == "2026-10-10"
        assert middle.credit["confirmation_window_end"] == "2026-11-10"

        validate_success(self._attempt_request(early.credit_id, bank_id), 200)
        validate_success(self._attempt_request(middle.credit_id, bank_id), 200)

        bank = _read_bank(bank_id)
        assert bank["confirming_line_used_cents"] == 20000000
        assert bank["confirmation_appetite_cents"] == 20000000
        assert early.refresh()["confirmation_status"] == "CONFIRMATION_REQUESTED"

    def test_a_third_overlapping_window_is_refused_on_peak_occupancy(self, clock):
        """The third window overlaps both of the first two, so the peak would reach 30,000,000.

        PRD 3.4: "The bank's appetite is measured as **peak concurrent occupancy** of its
        confirming line, not as a lifetime total and not by any pairwise comparison."

        Design: Difficulty/resource_temporal_overlap/confirming_line_peak_occupancy_half_open_window_with_capacity
        """
        _parties, bank_id, early, middle, third, _late = self._four_credits()
        request_confirmation(early.credit_id, bank_id)
        request_confirmation(middle.credit_id, bank_id)

        response = self._attempt_request(third.credit_id, bank_id)

        validate_error(response, "ERR_CONFIRMING_LINE_WINDOW_FULL", 409)
        refused = third.refresh()
        assert refused["confirmation_status"] == "UNCONFIRMED"
        assert refused["confirming_bank_id"] is None
        assert early.refresh()["status"] == "ISSUED"
        assert _read_bank(bank_id)["confirming_line_used_cents"] == 20000000

    def test_a_window_starting_on_another_window_end_date_inherits_a_free_line(self, clock):
        """The exclusive end frees the line on the very date the next window opens.

        PRD 3.4: "The reason subtractions sort before additions on a shared date is
        precisely that the intervals are half-open: an occupation ending on a given date
        frees the line before an occupation starting on that same date takes it."

        Design: Difficulty/resource_temporal_overlap/confirming_line_peak_occupancy_half_open_window_with_capacity
        """
        parties, bank_id, early, middle, _third, late = self._four_credits()
        request_confirmation(early.credit_id, bank_id)
        request_confirmation(middle.credit_id, bank_id)
        set_clock("2026-10-10T09:00:00Z")
        issue_credit(late.credit_id)
        late.refresh()
        assert late.credit["confirmation_window_start"] == "2026-10-10"
        assert late.credit["confirmation_window_end"] == "2026-12-10"

        validate_success(self._attempt_request(late.credit_id, bank_id), 200)

        assert late.refresh()["confirmation_status"] == "CONFIRMATION_REQUESTED"
        used = _read_bank(bank_id)["confirming_line_used_cents"]
        assert used == 20000000
        assert used != 30000000
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=40100000,
            utilisation_posture="OPEN",
        )


class TestAmendmentConsentWindowCoolingOffBuffer:
    """One credit's negotiation timeline, probed one day either side of the buffer."""

    def _rejected_round_then_a_draft(self):
        ctx = issued_credit(
            setup_parties(facility={"limit_cents": 50000000}),
            None,
            expiry_date="2026-11-30",
            latest_shipment_date="2026-10-31",
            **SIGHT_TEN_MILLION,
        )
        drafted = draft_amendment(ctx, {"latest_shipment_date": "2026-10-15"})
        # PRD 3.5: a draft's consent window is unset; issuance is what sets
        # `consent_window_start` to the clock date, so keep the issued snapshot.
        first = issue_amendment(drafted["id"])
        set_clock("2026-08-12T09:00:00Z")
        rejected = consent_to_amendment(
            first["id"], ctx.parties.beneficiary_id, "REJECT"
        )
        set_clock("2026-08-13T09:00:00Z")
        second = draft_amendment(ctx, {"presentation_period_days": 15})
        return ctx, first, rejected, second

    def _attempt_issue(self, amendment_id):
        return api_client.issue_amendment(
            amendment_id,
            factories.amendment_issue_payload(),
            trade_finance_officer_headers(TRADE_FINANCE_OFFICER_2),
        )

    def test_a_rejected_round_keeps_occupying_its_window_up_to_the_rejection_date(self, clock):
        """The first round's interval shrinks to the rejection date but does not vanish.

        PRD 3.5: "Terminal amendments keep occupying their window up to
        `window_end_effective` plus the buffer, which is what enforces a genuine cooling-off
        period between negotiation rounds."

        Design: Difficulty/resource_temporal_overlap/amendment_consent_window_closed_interval_with_cooling_off_buffer
        """
        _ctx, first, rejected, second = self._rejected_round_then_a_draft()

        assert first["consent_window_start"] == "2026-08-10"
        assert first["consent_deadline_date"] == "2026-08-20"
        assert rejected["status"] == "REJECTED"
        assert rejected["window_end_effective"] == "2026-08-12"
        assert second["status"] == "DRAFT"
        assert second["consent_window_start"] is None
        assert second["consent_deadline_date"] is None

    def test_a_start_touching_the_buffered_end_collides(self, clock):
        """Two days after a 2026-08-12 end is 2026-08-14, and touching endpoints collide.

        PRD 3.5: "The intervals collide, and the issue is refused with
        `ERR_AMENDMENT_WINDOW_CONFLICT` (409), when the new start is on or before the
        neighbour's end plus two days **and** the new end is on or after the neighbour's
        start minus two days."

        Design: Difficulty/resource_temporal_overlap/amendment_consent_window_closed_interval_with_cooling_off_buffer
        """
        ctx, _first, _rejected, second = self._rejected_round_then_a_draft()
        set_clock("2026-08-14T09:00:00Z")

        response = self._attempt_issue(second["id"])

        validate_error(response, "ERR_AMENDMENT_WINDOW_CONFLICT", 409)
        rows = {row["id"]: row for row in list_amendment_rows(ctx.credit_id)}
        assert rows[second["id"]]["status"] == "DRAFT"
        assert rows[second["id"]]["consent_window_start"] is None
        assert ctx.refresh()["status"] == "ISSUED"

    def test_one_day_past_the_buffer_the_same_amendment_issues(self, clock):
        """On 2026-08-15 the cooling-off period is over and the window opens that day.

        PRD 3.5: "The comparison is **pairwise and over closed intervals widened by a
        symmetric two-day cooling-off buffer**; one conflicting neighbour is enough, and
        there is no capacity to aggregate."

        Design: Difficulty/resource_temporal_overlap/amendment_consent_window_closed_interval_with_cooling_off_buffer
        """
        ctx, _first, _rejected, second = self._rejected_round_then_a_draft()
        set_clock("2026-08-14T09:00:00Z")
        validate_error(self._attempt_issue(second["id"]), "ERR_AMENDMENT_WINDOW_CONFLICT", 409)
        set_clock("2026-08-15T09:00:00Z")

        issued = validate_success(self._attempt_issue(second["id"]), 200)

        assert issued["status"] == "PENDING_CONSENT"
        assert issued["consent_window_start"] == "2026-08-15"
        assert issued["consent_deadline_date"] == "2026-08-25"
        assert issued["requires_beneficiary_consent"] is True
        credit = ctx.refresh()
        assert credit["status"] == "AMENDMENT_PENDING"
        assert credit["latest_shipment_date"] == "2026-10-31"
        assert credit["presentation_period_days"] == 21
