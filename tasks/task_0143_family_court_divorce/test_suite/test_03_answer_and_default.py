"""Answer / Default / Dismiss workflow on the AWAITING_ANSWER case.

PRD §3.1 — the answer window, default-after-expiry, dismiss-by-judge.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_safe,
    advance_clock_to,
    api_client,
    create_case,
    default_case,
    dismiss_case_payload,
    iso_utc,
    make_petitioner_headers,
    make_respondent_headers,
    parse_iso,
    re_get_case,
    server_offset_iso,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Answer happy path — PRD §3.1
# ===========================================================================
class TestAnswerHappyPath:

    def test_respondent_can_file_answer_within_window(self, api):
        """PRD §3.1: 'The Respondent (or their AttorneyOfRecord) can
        file an answer, provided now is at or before
        Case.answer_deadline_at and Respondent.has_filed_answer is
        currently false.'

        Claim: a Respondent files Answer before the deadline; case
        transitions to ANSWERED.
        """
        case = create_case()
        headers = make_respondent_headers(case["respondent_party_id"])
        res = api.answer_case(case["id"], headers)
        updated = validate_success(res, 200)
        assert updated["status"] == "ANSWERED"

    def test_answer_sets_respondent_has_filed_answer_true(self, api):
        """PRD §3.1: 'On a successful answer the server sets
        Respondent.has_filed_answer to true'.

        Claim: after answer, the respondent party's has_filed_answer
        is True.
        """
        case = create_case()
        headers = make_respondent_headers(case["respondent_party_id"])
        api.answer_case(case["id"], headers)
        parties = api.list_parties(
            case["id"], TEST_USERS["judge_headers"],
        ).json()["data"]
        respondent = next(p for p in parties if p["role"] == "RESPONDENT")
        assert respondent["has_filed_answer"] is True

    def test_answer_sets_response_received_at(self, api):
        """PRD §3.1: 'sets Case.response_received_at = now()'.

        Claim: after answer, case.response_received_at is non-null.
        """
        case = create_case()
        headers = make_respondent_headers(case["respondent_party_id"])
        api.answer_case(case["id"], headers)
        case_after = re_get_case(case["id"])
        assert case_after.get("response_received_at"), (
            "response_received_at must be set after Answer; got "
            f"{case_after.get('response_received_at')!r}"
        )


# ===========================================================================
# Answer past deadline — PRD §3.1
# ===========================================================================
class TestAnswerExpired:

    def test_answer_past_deadline_rejected(self, api):
        """PRD §3.1: 'If now is past the deadline, the answer attempt
        is rejected with ERR_ANSWER_WINDOW_EXPIRED (HTTP 409).'

        Claim: advancing clock past answer_deadline_at and then
        attempting Answer is rejected ERR_ANSWER_WINDOW_EXPIRED.
        """
        case = create_case()
        # Advance to 1 second past the deadline.
        deadline_dt = parse_iso(case["answer_deadline_at"])
        past_dt = deadline_dt.replace(microsecond=0)
        from datetime import timedelta
        target_iso = iso_utc(past_dt + timedelta(seconds=1))
        advance_clock_to(target_iso)
        headers = make_respondent_headers(case["respondent_party_id"])
        res = api.answer_case(case["id"], headers)
        validate_error(
            res, "ERR_ANSWER_WINDOW_EXPIRED",
            expected_status=409,
        )


# ===========================================================================
# Default — PRD §3.1
# ===========================================================================
class TestDefault:

    def test_default_while_window_open_rejected(self, api):
        """PRD §3.1: 'this is only allowed when now is strictly after
        Case.answer_deadline_at and the respondent has not filed an
        answer. Requesting default while the window is still open is
        rejected with ERR_ANSWER_WINDOW_OPEN (HTTP 409).'

        Claim: requesting default before the deadline (within window)
        is rejected ERR_ANSWER_WINDOW_OPEN.
        """
        case = create_case()
        headers = make_petitioner_headers(case["petitioner_party_id"])
        res = api.default_case(case["id"], headers)
        validate_error(
            res, "ERR_ANSWER_WINDOW_OPEN",
            expected_status=409,
        )

    def test_default_after_deadline_succeeds(self, api):
        """PRD §3.1: 'On a successful default request the case
        transitions from AWAITING_ANSWER to DEFAULTED.'

        Claim: after the deadline, default succeeds and the case is
        DEFAULTED.
        """
        case = create_case()
        # Advance clock past deadline.
        from datetime import timedelta
        deadline_dt = parse_iso(case["answer_deadline_at"])
        target_iso = iso_utc(deadline_dt + timedelta(seconds=1))
        advance_clock_to(target_iso)
        headers = make_petitioner_headers(case["petitioner_party_id"])
        res = api.default_case(case["id"], headers)
        updated = validate_success(res, 200)
        assert updated["status"] == "DEFAULTED"


# ===========================================================================
# Dismiss — PRD §3.1
# ===========================================================================
class TestDismiss:

    def test_judge_can_dismiss_filed_case(self, api, judge_headers):
        """PRD §3.1: 'A Judge may also dismiss the case while it is in
        FILED or AWAITING_ANSWER, supplying a free-text reason; the
        case transitions to DISMISSED and the workflow terminates
        there.'

        Claim: judge dismiss on AWAITING_ANSWER case transitions it to
        DISMISSED.
        """
        case = create_case()
        res = api.dismiss_case(
            case["id"], dismiss_case_payload(reason="settled"),
            judge_headers,
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "DISMISSED"
