"""Submission window and dispute-grace temporal boundaries (PRD §3.6)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_booth_scenario, issue_tokens, redeem_serials, create_submission,
    close_day, verify_submission,
    make_vendor_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]

_WINDOW_QUOTE = (
    "The claim is also temporal: it may be lodged while the market day is "
    "still `OPEN`, or after close within a grace of seven days measured from "
    "the day's `closes_at`; outside that window the attempt is rejected with "
    "`ERR_SUBMISSION_WINDOW_CLOSED`."
)
_GRACE_QUOTE = (
    "The cure is accepted while the claim remains inside the ordinary "
    "submission window, or within a seventy-two-hour grace measured from "
    "`disputed_at` even after that window has closed; past both limits the "
    "resubmission fails with `ERR_SUBMISSION_WINDOW_CLOSED`."
)


def _setup_redeemed_closed_day(api):
    """Charge 100; vendor redeems serial 200001 (tokens[0]); day CLOSED."""
    sc = setup_booth_scenario()
    issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 100)
    vend_id = sc["vendor"]["id"]
    t0 = tokens[0]
    assert t0["serial_number"] == 200001
    redeem_serials(vend_id, [200001])
    close_day(sc["market_day"]["id"])
    sc.update({"issuance": issuance, "tokens": tokens, "t0": t0})
    return sc


class TestSubmissionWindowBoundary:
    def test_submission_at_exact_deadline_accepted(self, api):
        """PRD §3.6: "The claim is also temporal: it may be lodged while the
        market day is still `OPEN`, or after close within a grace of seven days
        measured from the day's `closes_at`; outside that window the attempt is
        rejected with `ERR_SUBMISSION_WINDOW_CLOSED`."

        Design: Corner/validations/c_val_submission_window_deadline_inclusive
        """
        sc = _setup_redeemed_closed_day(api)
        # closes_at 2026-08-01T14:00:00Z + 7 days -> 2026-08-08T14:00:00Z exactly
        validate_success(api.set_clock("2026-08-08T14:00:00Z", ADMIN))

        resp = api.create_submission(
            {"market_day_id": sc["market_day"]["id"], "token_ids": [sc["t0"]["id"]]},
            make_vendor_headers(sc["vendor"]["id"]))
        submission = validate_success(resp, expected_status=201)
        assert submission["status"] == "SUBMITTED", "inclusive deadline admits the claim"

    def test_submission_one_second_past_deadline_rejected(self, api):
        """PRD §3.6: "The claim is also temporal: it may be lodged while the
        market day is still `OPEN`, or after close within a grace of seven days
        measured from the day's `closes_at`; outside that window the attempt is
        rejected with `ERR_SUBMISSION_WINDOW_CLOSED`."

        Design: Corner/validations/c_val_submission_window_deadline_plus_one_second_rejected
        """
        sc = _setup_redeemed_closed_day(api)
        validate_success(api.set_clock("2026-08-08T14:00:01Z", ADMIN))

        resp = api.create_submission(
            {"market_day_id": sc["market_day"]["id"], "token_ids": [sc["t0"]["id"]]},
            make_vendor_headers(sc["vendor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED)


class TestDisputeGraceBoundary:
    def _setup_disputed_at_0806(self, api):
        """Claim created on the OPEN day, day closed, then DISPUTED with the
        clock pinned at 2026-08-06T12:00:00Z (grace deadline 2026-08-09T12:00)."""
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 100)
        vend_id = sc["vendor"]["id"]
        t0 = tokens[0]
        redeem_serials(vend_id, [200001])
        submission = create_submission(vend_id, sc["market_day"]["id"], [t0["id"]])
        close_day(sc["market_day"]["id"])
        validate_success(api.set_clock("2026-08-06T12:00:00Z", ADMIN))
        verify_submission(submission["id"], "DISPUTED")
        sc.update({"issuance": issuance, "tokens": tokens, "t0": t0,
                   "submission": submission})
        return sc

    def test_resubmit_at_grace_deadline_accepted(self, api):
        """PRD §3.6: "The cure is accepted while the claim remains inside the
        ordinary submission window, or within a seventy-two-hour grace measured
        from `disputed_at` even after that window has closed; past both limits
        the resubmission fails with `ERR_SUBMISSION_WINDOW_CLOSED`."

        Design: Corner/validations/c_val_resubmit_grace_72h_inclusive_boundary
        """
        sc = self._setup_disputed_at_0806(api)
        # disputed_at + 72h exactly; the seven-day post-close window has expired
        validate_success(api.set_clock("2026-08-09T12:00:00Z", ADMIN))

        resp = api.resubmit_submission(sc["submission"]["id"], [sc["t0"]["id"]],
                                       make_vendor_headers(sc["vendor"]["id"]))
        resubmitted = validate_success(resp)
        assert resubmitted["status"] == "SUBMITTED", "grace deadline is inclusive"

    def test_resubmit_one_second_past_grace_rejected(self, api):
        """PRD §3.6: "The cure is accepted while the claim remains inside the
        ordinary submission window, or within a seventy-two-hour grace measured
        from `disputed_at` even after that window has closed; past both limits
        the resubmission fails with `ERR_SUBMISSION_WINDOW_CLOSED`."

        Design: Corner/validations/c_val_resubmit_grace_72h_plus_one_second_rejected
        """
        sc = self._setup_disputed_at_0806(api)
        validate_success(api.set_clock("2026-08-09T12:00:01Z", ADMIN))

        resp = api.resubmit_submission(sc["submission"]["id"], [sc["t0"]["id"]],
                                       make_vendor_headers(sc["vendor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED)

        submission = get_success_data(api.get_submission(sc["submission"]["id"], ADMIN))
        assert submission["status"] == "DISPUTED", "rejected resubmit leaves the claim DISPUTED"
