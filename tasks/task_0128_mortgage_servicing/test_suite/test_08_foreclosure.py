"""Foreclosure: NOI, filing, auction scheduling, reinstatement.

Coverage targets (PRD §3.6):
- Open a case: at most one open per loan (ERR_FORECLOSURE_CASE_EXISTS).
- /file before 30d NOI window -> ERR_NOI_WINDOW_NOT_ELAPSED.
- /file when MediationCase active -> ERR_INVALID_STATE.
- /schedule-auction before 60d after filed_at -> ERR_AUCTION_NOTICE_VIOLATION.
- /schedule-auction with auction_date < now + 30d -> ERR_AUCTION_NOTICE_VIOLATION.
- /reinstate within 5d of auction_date -> ERR_REINSTATEMENT_CUTOFF.
- /reinstate amount < quote -> ERR_REINSTATEMENT_INSUFFICIENT.
- /reinstate success -> case.status=CLOSED_REINSTATED, posture=REINSTATED.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NOI_WINDOW_DAYS,
    advance_clock,
    assert_foreclosure_case,
    file_foreclosure,
    get_loan,
    iso_datetime_utc_midnight,
    open_foreclosure_case,
    reinstate_foreclosure,
    request_mediation,
    schedule_auction,
    setup_borrower_and_current_loan,
    setup_foreclosure_case_at_noi_issued,
    setup_foreclosure_case_auction_scheduled,
    setup_foreclosure_case_filed,
    setup_loan_in_default,
    today_utc,
    validate_error,
    validate_success,
)


class TestForeclosureOpen:
    def test_second_open_case_on_same_loan_rejected(
        self, api, foreclosure_attorney_headers,
    ):
        """PRD §3.6: "At most one open case per loan is permitted ...
        a second-opening attempt is rejected with
        ERR_FORECLOSURE_CASE_EXISTS."

        Claim: opening a second ForeclosureCase on the same loan ->
        ERR_FORECLOSURE_CASE_EXISTS.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        resp = api.create_foreclosure_case(
            {"loan_id": loan["id"]},
            foreclosure_attorney_headers,
        )
        validate_error(resp,
                       ApiErrorId.ERR_FORECLOSURE_CASE_EXISTS.value)

    def test_open_case_sets_posture_foreclosure_and_status_noi(
        self, api,
    ):
        """PRD §3.6: "The case is created in status NOI_ISSUED,
        noi_sent_at is stamped to now (starting the regulatory clock),
        and Loan.posture cascades to FORECLOSURE."

        Claim: created ForeclosureCase has status=NOI_ISSUED and the
        loan posture becomes FORECLOSURE.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        assert_foreclosure_case(fc)
        assert fc["status"] == "NOI_ISSUED"
        assert isinstance(fc["noi_sent_at"], str)
        loan_after = get_loan(loan["id"])
        assert loan_after["posture"] == "FORECLOSURE"


class TestForeclosureFile:
    def test_file_before_noi_window_rejected(
        self, api, foreclosure_attorney_headers,
    ):
        """PRD §3.6: "Filing requires ... at least 30 days to have
        elapsed since noi_sent_at (an earlier attempt is rejected with
        ERR_NOI_WINDOW_NOT_ELAPSED)".

        Claim: /file immediately after open (noi_sent_at ~ now) ->
        ERR_NOI_WINDOW_NOT_ELAPSED.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        resp = api.file_foreclosure(fc["id"],
                                    foreclosure_attorney_headers)
        validate_error(resp,
                       ApiErrorId.ERR_NOI_WINDOW_NOT_ELAPSED.value)

    def test_file_after_noi_window_succeeds(
        self, api,
    ):
        """PRD §3.6: "On filing, the case status becomes FILED and
        filed_at is stamped."

        Claim: after 30+ days, /file -> status=FILED with filed_at
        stamped.
        """
        b, loan, fc = setup_foreclosure_case_filed()
        # The fixture already ran /file after advancing 31d.
        assert fc["status"] == "FILED"
        assert isinstance(fc["filed_at"], str)

    def test_file_with_active_mediation_rejected(
        self, api, foreclosure_attorney_headers,
    ):
        """PRD §3.6: "Filing requires ... that no mediation case in a
        non-terminal status (anything other than FAILED, OFFER_REJECTED,
        or COMPLETED) currently exists on the case."

        Claim: open mediation REQUESTED on a case and attempt /file
        after 30d -> ERR_INVALID_STATE (PRD validations priority 8:
        state precondition).
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        request_mediation(fc["id"])
        # NOTE: case status now MEDIATION_OPEN, so /file fails on
        # source-state precondition (must be NOI_ISSUED).
        advance_clock(31)
        resp = api.file_foreclosure(fc["id"],
                                    foreclosure_attorney_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestScheduleAuction:
    def test_schedule_auction_within_60d_filed_rejected(
        self, api, foreclosure_attorney_headers,
    ):
        """PRD §3.6: "After the case has been on file for at least 60
        days, the attorney may schedule an auction ... failure of
        either the 60-day or the 30-day rule is rejected with
        ERR_AUCTION_NOTICE_VIOLATION."

        Claim: /schedule-auction before 60d after filed_at ->
        ERR_AUCTION_NOTICE_VIOLATION.
        """
        b, loan, fc = setup_foreclosure_case_filed()
        # Attempt scheduling immediately; auction_date far in the future.
        far_future = iso_datetime_utc_midnight(
            today_utc() + timedelta(days=120),
        )
        resp = api.schedule_auction(
            fc["id"], {"auction_date": far_future},
            foreclosure_attorney_headers,
        )
        validate_error(resp,
                       ApiErrorId.ERR_AUCTION_NOTICE_VIOLATION.value)

    def test_schedule_auction_with_short_notice_rejected(
        self, api, foreclosure_attorney_headers,
    ):
        """PRD §3.6: "The proposed auction_date must be at least 30
        days in the future (statutory notice); failure of either the
        60-day or the 30-day rule is rejected with
        ERR_AUCTION_NOTICE_VIOLATION."

        Claim: auction_date < now + 30d ->
        ERR_AUCTION_NOTICE_VIOLATION.
        """
        b, loan, fc = setup_foreclosure_case_filed()
        # Wait 60 days so the filed-at gate is satisfied; then try a
        # short auction_date.
        advance_clock(61)
        short = iso_datetime_utc_midnight(
            today_utc() + timedelta(days=25),
        )
        resp = api.schedule_auction(
            fc["id"], {"auction_date": short},
            foreclosure_attorney_headers,
        )
        validate_error(resp,
                       ApiErrorId.ERR_AUCTION_NOTICE_VIOLATION.value)


class TestReinstatement:
    def test_reinstate_within_cutoff_rejected(self, api, servicer_headers):
        """PRD §3.6: "If the case is already AUCTION_SCHEDULED,
        reinstatement must be attempted strictly more than 5 days
        before auction_date; an attempt inside the 5-day cut-off is
        rejected with ERR_REINSTATEMENT_CUTOFF."

        Claim: with auction_date now+30d, advance clock to now+26d
        (=auction_date - 4d, inside the 5-day backward buffer);
        /reinstate -> ERR_REINSTATEMENT_CUTOFF.
        """
        b, loan, fc = setup_foreclosure_case_auction_scheduled(
            auction_offset_days=30,
        )
        # Now advance 26 days so today = auction_date - 4d.
        advance_clock(26)
        resp = api.reinstate_foreclosure(
            fc["id"], {"payment_amount_cents": 100_000_000_000},
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_CUTOFF.value)

    def test_reinstate_with_insufficient_payment_rejected(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "if it is less than reinstatement_quote_cents
        (re-checked at commit time so racing late fees and freshly-
        failed disbursements are correctly reflected), the request is
        rejected with ERR_REINSTATEMENT_INSUFFICIENT."

        Claim: payment_amount_cents = 1 (clearly less than any positive
        quote) -> ERR_REINSTATEMENT_INSUFFICIENT.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        resp = api.reinstate_foreclosure(
            fc["id"], {"payment_amount_cents": 1},
            servicer_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REINSTATEMENT_INSUFFICIENT.value,
        )

    def test_reinstate_with_sufficient_payment_closes_case(
        self, api, servicer_headers,
    ):
        """PRD §3.6: "On a successful reinstatement, ... the case
        status becomes CLOSED_REINSTATED, Loan.posture becomes
        REINSTATED, delinquency_days is set to zero".

        Claim: reinstate with a payment >= quote -> case.status =
        CLOSED_REINSTATED, loan.posture = REINSTATED,
        delinquency_days = 0.
        """
        b, loan, fc = setup_foreclosure_case_at_noi_issued()
        # Read the quote first.
        quote = int(
            api.get_foreclosure_quote(
                fc["id"], servicer_headers,
            ).json()["data"]["reinstatement_quote_cents"]
        )
        result = reinstate_foreclosure(
            fc["id"], payment_amount_cents=quote,
        )
        assert result["status"] == "CLOSED_REINSTATED"
        loan_after = get_loan(loan["id"])
        assert loan_after["posture"] == "REINSTATED"
        assert loan_after["delinquency_days"] == 0
