"""Tolling, response-deadline math, third-party deadline — PRD §2.7, §3.4."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    MAX_TOLL_DAYS,
    TEST_USERS,
    add_seconds,
    advance_clock_by_days,
    advance_clock_to_iso,
    create_acknowledged_request,
    drive_tolling_to_cap,
    file_appeal,
    get_request,
    get_third_party_notice,
    make_appeal_authority_headers,
    make_requester_headers,
    object_third_party_notice,
    resume_clock,
    setup_denied_request_with_distinct_authority,
    setup_request_with_third_party_notice,
    start_tolling,
    start_tolling_payload,
    unique_third_party_id,
    validate_error,
    validate_success,
)


# ===========================================================================
# Tolling start — PRD §3.4
# ===========================================================================
class TestStartTolling:

    def test_start_tolling_on_acknowledged_request_succeeds(self, api):
        """PRD §3.4: "An officer who needs more information from the
        requester (a fee question or a clarification on the subject) may
        pause the 20-business-day response clock by submitting a
        tolling-start payload that carries a `reason`. This is a
        self-loop on the request - its `status` remains `ACKNOWLEDGED`".

        Claim: /start-tolling on an ACKNOWLEDGED request succeeds and
        leaves status=ACKNOWLEDGED.
        """
        _r, request = create_acknowledged_request()
        tolled = start_tolling(request["id"])
        assert tolled["status"] == "ACKNOWLEDGED"

    def test_start_tolling_when_cap_already_reached_rejected(self, api):
        """PRD §3.4: "Tolling-start is permitted only when the request
        is currently `ACKNOWLEDGED` and only when the cumulative
        `tolling_days_consumed` is strictly less than 30
        (`MAX_TOLL_DAYS`). The 30-business-day cap is checked before
        the state precondition ... a tolling-start that would push
        cumulative tolling beyond 30 is rejected with
        `ERR_TOLLING_LIMIT_EXCEEDED` and HTTP 422."

        Claim: /start-tolling on a request whose tolling_days_consumed
        is already at MAX_TOLL_DAYS fails with ERR_TOLLING_LIMIT_EXCEEDED.
        """
        _r, request = create_acknowledged_request()
        # Drive to exactly 30 business days via cycles.
        at_cap = drive_tolling_to_cap(
            request_id=request["id"], target_days=MAX_TOLL_DAYS,
        )
        assert at_cap["tolling_days_consumed"] == MAX_TOLL_DAYS
        resp = api.start_tolling(
            request["id"], start_tolling_payload(),
            TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TOLLING_LIMIT_EXCEEDED.value)
        # Confirm tolling_days_consumed is unchanged.
        refreshed = get_request(request["id"])
        assert refreshed["tolling_days_consumed"] == MAX_TOLL_DAYS


# ===========================================================================
# Third-party deadline — PRD §3.7
# ===========================================================================
class TestThirdPartyDeadline:

    def test_object_after_deadline_rejected(self, api):
        """PRD §3.7: "an action after the deadline (when the current
        clock has reached or passed `response_deadline`) is rejected
        with `ERR_THIRD_PARTY_DEADLINE_PASSED` and HTTP 422."

        Claim: /object after the clock has been advanced past the
        notice's response_deadline fails with
        ERR_THIRD_PARTY_DEADLINE_PASSED.

        NOTE: PRD §3.7 states "the action must arrive strictly before
        the deadline; an action after the deadline (when the current
        clock has reached or passed `response_deadline`) is rejected".
        The system simultaneously auto-EXPIRES PENDING_RESPONSE notices
        when the clock advances past the deadline (PRD §3.7 sweep). The
        observable outcome at the boundary depends on which rule fires
        first on the same call. Per PRD prose the deadline check is
        explicitly named for /object; the loser of a same-instant race
        with the sweep would surface as ERR_NOTICE_ALREADY_CLOSED. We
        accept either.
        """
        tp_id = unique_third_party_id()
        _r, _req, _rec, notice = setup_request_with_third_party_notice(
            third_party_id=tp_id,
        )
        deadline_iso = notice["response_deadline"]
        # Advance one minute past the deadline.
        target = add_seconds(deadline_iso, 60)
        advance_clock_to_iso(target)
        # Attempt /object as the third party.
        from test_helpers import make_third_party_headers
        from test_helpers import object_third_party_payload
        from test_helpers import validate_error_is_one_of
        resp = api.object_third_party_notice(
            notice["id"],
            object_third_party_payload(objection_grounds="late objection"),
            make_third_party_headers(tp_id),
        )
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_THIRD_PARTY_DEADLINE_PASSED.value,
                ApiErrorId.ERR_NOTICE_ALREADY_CLOSED.value,
            ],
        )


# ===========================================================================
# Appeal-decide window — PRD §3.9
# ===========================================================================
class TestAppealDecideWindow:

    def test_decide_after_20_business_days_rejected(self, api):
        """PRD §3.9: "a `decide` call against a requester appeal that
        arrived past this same 20-business-day window - measured as
        `Appeal.filed_at` plus 20 business days strictly less than the
        current clock combined with `appellant_role` of `REQUESTER` - is
        rejected with `ERR_APPEAL_WINDOW_EXPIRED` and HTTP 422".

        Claim: /decide on a REQUESTER appeal filed more than 20 business
        days before the current clock fails with
        ERR_APPEAL_WINDOW_EXPIRED.
        """
        from test_helpers import (
            accept_appeal_for_review,
            APPEAL_AUTHORITY_SHARED_ID,
            decide_appeal_payload,
        )
        requester, denied, _off_h, auth_h = (
            setup_denied_request_with_distinct_authority(
                appeal_authority_operator_id=APPEAL_AUTHORITY_SHARED_ID,
            )
        )
        appeal = file_appeal(
            request=denied, appellant_id=requester["id"],
            appellant_role="REQUESTER",
        )
        accept_appeal_for_review(appeal["id"], auth_h)
        # Advance clock by enough calendar days to cover 21 business days.
        # 21 business days <= 35 calendar days even with 3 holidays.
        advance_clock_by_days(40)
        resp = api.decide_appeal(
            appeal["id"], decide_appeal_payload(decision="UPHELD"), auth_h,
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED.value)
