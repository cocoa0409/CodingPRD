"""Endpoint/envelope corners: pagination envelope, error envelope shape,
status filter (PRD 2.2, 2.3, 3.2)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_case_payload,
    create_landlord_payload,
    create_notice,
    create_tenancy_payload,
    create_unit_payload,
    make_landlord_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


def _two_cases_one_landlord(api):
    landlord = validate_success(api.create_landlord(
        create_landlord_payload(), TEST_USERS["admin_headers"]), 201)
    ll = make_landlord_headers(landlord["id"])
    cases = []
    for label in ("A", "B"):
        unit = validate_success(api.create_unit(
            create_unit_payload(landlord["id"], "CA", unit_label=label), ll),
            201)
        tenancy = validate_success(api.create_tenancy(
            create_tenancy_payload(unit["id"], tenant_full_name=f"T{label}"),
            ll), 201)
        case = validate_success(api.create_case(
            create_case_payload(tenancy["id"], "NONPAYMENT"), ll), 201)
        cases.append(case)
    return landlord, ll, cases


class TestCaseListPaginationEnvelope:
    """Corner instance: limit=1 over two cases returns total_count 2,
    has_more true; offset=1 returns the second."""

    def test_pagination_envelope(self, api):
        """PRD 2.3: "The limit parameter caps the number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of
        100. The offset parameter specifies how many items to skip and
        defaults to 0." and "The meta object of a list response carries the
        pagination fields limit, offset, total_count, and has_more."

        Design: Corner/endpoints/case_list_pagination_envelope
        """
        landlord, ll, cases = _two_cases_one_landlord(api)
        first = api.list_cases(
            CLERK_A, params={"landlord_id": landlord["id"], "limit": 1,
                             "offset": 0})
        data1, meta1 = validate_paginated(first)
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert len(data1) == 1

        second = api.list_cases(
            CLERK_A, params={"landlord_id": landlord["id"], "limit": 1,
                             "offset": 1})
        data2, meta2 = validate_paginated(second)
        assert meta2["has_more"] is False
        assert len(data2) == 1
        assert data1[0]["id"] != data2[0]["id"]


class TestErrorEnvelopeShape:
    """Corner instance: GET on a nonexistent case id returns the error
    envelope with ERR_NOT_FOUND, HTTP 404."""

    def test_not_found_envelope(self, api):
        """PRD 2.2: "The meta object for error responses contains only
        api_request_id and api_request_timestamp." and the error data object
        carries the error_id and message fields per the same section. PRD 2.7
        rung 3: "the first missing identifier yields ERR_NOT_FOUND".

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_case(NON_EXISTENT_UUID, CLERK_A)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert body["data"]["message"]
        assert body["meta"]["api_request_id"].startswith("req_")


class TestCaseListStatusFilter:
    """Corner instance: the status filter returns only matching cases."""

    def test_status_filter_excludes_non_matching(self, api):
        """PRD 3.2: "A landlord can review their docket through the case
        list, optionally filtered by landlord_id, tenancy_id, or status."

        Design: Corner/endpoints/case_list_status_filter
        """
        landlord, ll, cases = _two_cases_one_landlord(api)
        set_clock("2026-05-02T08:00:00Z")
        # Move only the first case to NOTICE_ACTIVE.
        create_notice(landlord, cases[0])

        resp = api.list_cases(
            CLERK_A, params={"landlord_id": landlord["id"],
                             "status": "NOTICE_ACTIVE"})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == cases[0]["id"]
        assert data[0]["status"] == "NOTICE_ACTIVE"
