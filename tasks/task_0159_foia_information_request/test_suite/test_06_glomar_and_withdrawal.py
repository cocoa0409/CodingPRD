"""Glomar response, withdrawal, no-records rules — PRD §3.5."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_acknowledged_request,
    create_responsive_record,
    create_responsive_record_payload,
    file_request,
    issue_glomar_payload,
    make_requester_headers,
    setup_glomar_issued_request,
    setup_request_in_search,
    validate_error,
    validate_success,
)


# ===========================================================================
# Glomar — PRD §3.5
# ===========================================================================
class TestGlomar:

    def test_issue_glomar_with_valid_basis_transitions_to_glomar_issued(self, api):
        """PRD §3.5: "on success transitions the request to
        `GLOMAR_ISSUED`, sets `determination_at` to the current time,
        and appends a `GLOMAR_ISSUED` audit entry."

        Claim: /issue-glomar with basis=['B1'] on a zero-records request
        transitions to GLOMAR_ISSUED with glomar_invoked=true.
        """
        _r, glomar_req = setup_glomar_issued_request(glomar_basis=["B1"])
        assert glomar_req["status"] == "GLOMAR_ISSUED"
        assert glomar_req["glomar_invoked"] is True
        assert glomar_req["glomar_exemption_basis"] == ["B1"]
        assert glomar_req["determination_at"] is not None

    @pytest.mark.parametrize("bad_basis", [
        ["B4"],
        ["B5"],
        ["B2"],
        ["B1", "B4"],
    ])
    def test_issue_glomar_with_invalid_basis_rejected(self, api, bad_basis):
        """PRD §3.5: "validates each member against the allowed set
        (rejecting with `ERR_INVALID_GLOMAR_BASIS` and HTTP 422 if any
        member is outside `B1`, `B6`, `B7C` or if the array is empty)".

        Claim: any glomar_exemption_basis containing a code outside
        {B1, B6, B7C} fails with ERR_INVALID_GLOMAR_BASIS.
        """
        # Walk to DETERMINATION_PENDING without records.
        _r, request = create_acknowledged_request()
        from test_helpers import (
            close_search,
            create_fee_assessment,
            estimate_fee_assessment,
            start_search,
        )
        fa = create_fee_assessment(
            request_id=request["id"],
            estimated_pages=1,
            estimated_search_hours=0,
            estimated_review_hours=0,
        )
        estimate_fee_assessment(fa["id"])
        start_search(request["id"])
        close_search(request["id"])
        payload = issue_glomar_payload(glomar_exemption_basis=bad_basis)
        resp = api.issue_glomar(
            request["id"], payload, TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_GLOMAR_BASIS.value)

    def test_issue_glomar_with_empty_basis_rejected(self, api):
        """PRD §3.5: "rejecting with `ERR_INVALID_GLOMAR_BASIS` and HTTP
        422 if any member is outside `B1`, `B6`, `B7C` or if the array
        is empty".

        Claim: glomar_exemption_basis=[] fails with
        ERR_INVALID_GLOMAR_BASIS.
        """
        from test_helpers import (
            close_search,
            create_fee_assessment,
            estimate_fee_assessment,
            start_search,
        )
        _r, request = create_acknowledged_request()
        fa = create_fee_assessment(
            request_id=request["id"],
            estimated_pages=1,
            estimated_search_hours=0,
            estimated_review_hours=0,
        )
        estimate_fee_assessment(fa["id"])
        start_search(request["id"])
        close_search(request["id"])
        payload = issue_glomar_payload(glomar_exemption_basis=[])
        resp = api.issue_glomar(
            request["id"], payload, TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_GLOMAR_BASIS.value)

    def test_issue_glomar_with_existing_records_rejected(self, api):
        """PRD §3.5: "verifies that no `ResponsiveRecord`s exist
        (rejecting with `ERR_GLOMAR_WITH_RECORDS` and HTTP 422 if any
        exist)".

        Claim: /issue-glomar on a request with at least one
        ResponsiveRecord fails with ERR_GLOMAR_WITH_RECORDS.
        """
        # Drive to DETERMINATION_PENDING with one RELEASED_FULL record.
        from test_helpers import setup_request_in_determination_pending
        _r, request, _fa, _records = setup_request_in_determination_pending(
            dispositions=[(5, "RELEASED_FULL", None)],
        )
        payload = issue_glomar_payload(glomar_exemption_basis=["B1"])
        resp = api.issue_glomar(
            request["id"], payload, TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GLOMAR_WITH_RECORDS.value)

    def test_create_record_on_glomar_request_rejected(self, api):
        """PRD §3.5: "A consequence of the no-records rule on Glomar is
        that attempting to create a `ResponsiveRecord` for a request
        with `glomar_invoked` of true is rejected with
        `ERR_RECORDS_FORBIDDEN_ON_GLOMAR` and HTTP 422."

        Claim: POST /foia/responsive-records targeting a GLOMAR_ISSUED
        request fails with ERR_RECORDS_FORBIDDEN_ON_GLOMAR.
        """
        _r, glomar_req = setup_glomar_issued_request(glomar_basis=["B1"])
        payload = create_responsive_record_payload(
            request_id=glomar_req["id"], page_count=3,
        )
        resp = api.create_responsive_record(
            payload, TEST_USERS["officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_RECORDS_FORBIDDEN_ON_GLOMAR.value,
        )


# ===========================================================================
# Withdrawal — PRD §3.5
# ===========================================================================
class TestWithdraw:

    def test_withdraw_from_intake_transitions_to_withdrawn(self, api):
        """PRD §3.5: "A requester may withdraw their own request at any
        point before determination - from `INTAKE`, `ACKNOWLEDGED`, or
        `SEARCH`, transitioning it to the terminal `WITHDRAWN` state."

        Claim: /withdraw on an INTAKE request transitions to WITHDRAWN.
        """
        from test_helpers import create_requester
        requester = create_requester()
        request = file_request(requester=requester)
        resp = api.withdraw_request(
            request["id"], make_requester_headers(requester["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_from_acknowledged_transitions_to_withdrawn(self, api):
        """PRD §3.5: "A requester may withdraw their own request at any
        point before determination - from `INTAKE`, `ACKNOWLEDGED`, or
        `SEARCH`, transitioning it to the terminal `WITHDRAWN` state."

        Claim: /withdraw on an ACKNOWLEDGED request transitions to
        WITHDRAWN.
        """
        requester, request = create_acknowledged_request()
        resp = api.withdraw_request(
            request["id"], make_requester_headers(requester["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_by_wrong_requester_rejected(self, api):
        """PRD §3.5: "The withdrawal action requires that the calling
        `X-User-ID` matches the request's `requester_id`."

        Claim: /withdraw invoked by a Requester whose id != the request's
        requester_id is rejected (ERR_FORBIDDEN per PRD §2.1 role-gate
        cascade).
        """
        from test_helpers import create_requester
        owning = create_requester()
        intruder = create_requester()
        request = file_request(requester=owning)
        resp = api.withdraw_request(
            request["id"], make_requester_headers(intruder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_withdraw_after_determination_rejected_invalid_state(self, api):
        """PRD §3.5: "A requester may withdraw their own request at any
        point before determination - from `INTAKE`, `ACKNOWLEDGED`, or
        `SEARCH`".

        Claim: /withdraw after the request has reached a terminal
        determination state (e.g., RELEASED) fails with ERR_INVALID_STATE.
        """
        from test_helpers import determine_request
        from test_helpers import setup_request_in_determination_pending
        requester, request, _fa, _records = (
            setup_request_in_determination_pending(
                dispositions=[(5, "RELEASED_FULL", None)],
            )
        )
        determined = determine_request(request["id"])
        assert determined["status"] == "RELEASED"
        resp = api.withdraw_request(
            request["id"], make_requester_headers(requester["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
