"""Examination begin, Office Action cycles, response, action_number,
and allow.

Covers PRD §3.3 in full plus the OFFICE_ACTION_PENDING <-> UNDER_EXAMINATION
cycle.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    OFFICE_ACTION_EXTENDED_DEADLINE_DAYS,
    OFFICE_ACTION_RESPONSE_DEADLINE_DAYS,
    advance_clock_to,
    allow_application,
    assert_office_action,
    assert_response,
    begin_examination_full,
    create_applicant,
    create_draft_application,
    create_office_action_payload,
    get_application,
    get_office_action,
    issue_office_action,
    list_office_actions,
    make_applicant_headers,
    pay_fee,
    pay_filing_fees,
    reset_clock_to_base,
    setup_filed_application,
    setup_office_action_at_clock,
    setup_office_action_pending,
    setup_under_examination,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# FILED -> UNDER_EXAMINATION (PRD §3.3)
# ===========================================================================
class TestBeginExamination:

    def test_begin_examination_on_filed_utility_succeeds(self, api, examiner_headers):
        """PRD §3.3: "Once an application is in FILED and is either
        UTILITY or DESIGN, an examiner may begin examination,
        transitioning the application to UNDER_EXAMINATION."
        """
        a, app = setup_filed_application(application_type="UTILITY")
        begin_examination_full(a, app)
        data = get_application(app["id"])
        assert data["status"] == "UNDER_EXAMINATION"

    def test_begin_examination_on_provisional_rejected_invalid_state(self, api, examiner_headers):
        """PRD §3.3: "The examiner cannot begin examination on a
        PROVISIONAL filing — provisional applications never enter
        examination — and any such attempt is reported as an invalid
        state."
        """
        a, prov = setup_filed_application(application_type="PROVISIONAL")
        from test_helpers import examination_fee_cents
        # Pay an examination fee anyway — the state precondition wins.
        pay_fee(a, prov, "EXAMINATION", examination_fee_cents(a["entity_size"]))
        res = api.begin_examination(prov["id"], examiner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_begin_examination_without_examination_fee_rejected(self, api, examiner_headers):
        """PRD §3.3: "The transition requires that an
        EXAMINATION-category fee transaction already exists for the
        application at the scaffold-computed examination amount for the
        applicant's entity_size; otherwise the request is rejected
        with ERR_FEE_AMOUNT_MISMATCH."
        """
        a, app = setup_filed_application(application_type="UTILITY")
        res = api.begin_examination(app["id"], examiner_headers)
        validate_error(res, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)


# ===========================================================================
# Issuing Office Actions (PRD §3.3)
# ===========================================================================
class TestIssueOfficeAction:

    def test_issue_first_office_action_sets_action_number_to_one(self, api):
        """PRD §3.3: "The server assigns a sequential action_number per
        application starting at 1 and incrementing by 1 for each
        subsequent Office Action on the same application".
        """
        a, app = setup_under_examination()
        oa = issue_office_action(app, action_type="NON_FINAL")
        assert_office_action(oa)
        assert oa["action_number"] == 1, (
            f"PRD §3.3: first action_number must be 1, got {oa['action_number']!r}"
        )
        assert oa["status"] == "PENDING"

    def test_issue_office_action_transitions_to_oa_pending(self, api):
        """PRD §3.3: "While in UNDER_EXAMINATION the examiner may issue
        an Office Action, moving the application to
        OFFICE_ACTION_PENDING."
        """
        a, app = setup_under_examination()
        issue_office_action(app)
        app_state = get_application(app["id"])
        assert app_state["status"] == "OFFICE_ACTION_PENDING"

    def test_office_action_deadlines_relative_to_issued_at(self, api):
        """PRD §3.3: "computes response_deadline_at as issued_at plus
        90 days, computes extended_deadline_at as issued_at plus 180
        days".
        """
        from datetime import datetime, timedelta, timezone
        a, app, oa = setup_office_action_at_clock(
            issued_at_dt=DEFAULT_BASE_CLOCK,
        )
        issued = datetime.fromisoformat(oa["issued_at"].replace("Z", "+00:00"))
        rd = datetime.fromisoformat(oa["response_deadline_at"].replace("Z", "+00:00"))
        ed = datetime.fromisoformat(oa["extended_deadline_at"].replace("Z", "+00:00"))
        assert rd == issued + timedelta(days=OFFICE_ACTION_RESPONSE_DEADLINE_DAYS), (
            "PRD §3.3: response_deadline_at must equal issued_at + 90 days"
        )
        assert ed == issued + timedelta(days=OFFICE_ACTION_EXTENDED_DEADLINE_DAYS), (
            "PRD §3.3: extended_deadline_at must equal issued_at + 180 days"
        )


# ===========================================================================
# Filing a Response (PRD §3.3)
# ===========================================================================
class TestFileResponse:

    def test_timely_response_succeeds_and_returns_to_under_examination(self, api):
        """PRD §3.3: "On success the server creates a Response row
        whose office_action_id points back at the Office Action,
        copies the Office Action's application_id into the
        Response.application_id field, stamps the response instant as
        filed_at, sets the Office Action's status to RESPONDED,
        transitions the application from OFFICE_ACTION_PENDING back to
        UNDER_EXAMINATION".
        """
        a, app, oa = setup_office_action_pending()
        res = api.file_response(oa["id"], make_applicant_headers(a["id"]))
        data = validate_success(res, 201)
        assert_response(data)
        assert data["office_action_id"] == oa["id"]
        assert data["application_id"] == app["id"]
        assert data["months_extension"] == 0, (
            "PRD §3.3: timely response (clock <= response_deadline_at) has months_extension == 0"
        )
        assert data["extension_fee_cents"] == 0, (
            "PRD §3.3: \"If the result is zero ... extension_fee_cents is exactly zero\""
        )
        # OA flipped to RESPONDED.
        oa2 = get_office_action(oa["id"])
        assert oa2["status"] == "RESPONDED"
        # App back to UNDER_EXAMINATION.
        app2 = get_application(app["id"])
        assert app2["status"] == "UNDER_EXAMINATION"

    def test_response_past_extended_deadline_rejected(self, api):
        """PRD §3.3: "A response filed after the extended deadline is
        rejected with ERR_OFFICE_ACTION_DEADLINE_PASSED."

        Per PRD §2.8 the clock-advance sweep flips the OA to
        ABANDONED_BY_DEFAULT synchronously, so the §2.11 priority order
        may surface ERR_INVALID_STATE (priority 6) before the temporal
        check (priority 10). Both outcomes are PRD-faithful readings.
        """
        from datetime import datetime, timedelta
        a, app, oa = setup_office_action_at_clock(issued_at_dt=DEFAULT_BASE_CLOCK)
        # Move clock to 1 second past extended_deadline_at — sweep
        # flips the OA to ABANDONED_BY_DEFAULT synchronously.
        ed = datetime.fromisoformat(oa["extended_deadline_at"].replace("Z", "+00:00"))
        advance_clock_to(ed + timedelta(seconds=1))
        res = api.file_response(oa["id"], make_applicant_headers(a["id"]))
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_OFFICE_ACTION_DEADLINE_PASSED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


# ===========================================================================
# OA cycle: UNDER_EX <-> OFFICE_ACTION_PENDING (PRD §3.3)
# ===========================================================================
class TestOfficeActionCycle:

    def test_action_number_increments_across_cycle(self, api):
        """PRD §3.3: "incrementing by 1 for each subsequent Office
        Action on the same application — listing Office Actions for an
        application surfaces them in order".
        """
        a, app = setup_under_examination()
        oa1 = issue_office_action(app, action_type="NON_FINAL")
        api.file_response(oa1["id"], make_applicant_headers(a["id"]))
        oa2 = issue_office_action(app, action_type="NON_FINAL")
        api.file_response(oa2["id"], make_applicant_headers(a["id"]))
        oa3 = issue_office_action(app, action_type="FINAL")
        assert oa1["action_number"] == 1
        assert oa2["action_number"] == 2
        assert oa3["action_number"] == 3
        # Sequence is dense [1..N] with no gaps.
        rows = list_office_actions(app["id"])
        nums = sorted(r["action_number"] for r in rows)
        assert nums == [1, 2, 3], (
            f"PRD §3.3: action_number must be dense [1..N]; got {nums}"
        )


# ===========================================================================
# UNDER_EXAMINATION -> ALLOWED (PRD §3.3)
# ===========================================================================
class TestAllow:

    def test_allow_after_response_succeeds(self, api):
        """PRD §3.3: "Once every Office Action for the application has
        been resolved — that is, no Office Action with status PENDING
        remains — an examiner may allow the application, transitioning
        it from UNDER_EXAMINATION to ALLOWED."
        """
        a, app, oa = setup_office_action_pending()
        api.file_response(oa["id"], make_applicant_headers(a["id"]))
        result = allow_application(app)
        assert result["status"] == "ALLOWED"

    def test_allow_while_oa_still_pending_rejected_invalid_state(self, api, examiner_headers):
        """PRD §3.3: "Once every Office Action for the application has
        been resolved — that is, no Office Action with status PENDING
        remains — an examiner may allow the application, transitioning
        it from UNDER_EXAMINATION to ALLOWED."

        Equivalently, while a PENDING OA exists the application is in
        OFFICE_ACTION_PENDING (not UNDER_EXAMINATION) and /allow must
        return ERR_INVALID_STATE.
        """
        a, app, oa = setup_office_action_pending()
        res = api.allow_application(app["id"], examiner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
