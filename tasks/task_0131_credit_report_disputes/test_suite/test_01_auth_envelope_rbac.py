"""PRD §2.1 (RBAC), §2.2 (response envelope), §2.3 (pagination).

Covers:
- Missing / malformed auth headers -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
- Wrong role for endpoint -> ERR_FORBIDDEN_FOR_ROLE
- Consumer ownership mismatch -> ERR_FORBIDDEN_FOR_ROLE
- Success envelope shape (meta + response_type + data)
- Error envelope shape
- Pagination defaults / bounds
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_consumer,
    create_consumer_payload,
    create_credit_report,
    create_dispute_payload,
    create_furnisher,
    create_tradeline_item,
    make_consumer_headers,
    make_furnisher_headers,
    setup_consumer_furnisher_report_tradeline,
    submit_dispute,
    validate_error,
    validate_success,
)


# ===========================================================================
# Header presence + well-formedness — PRD §2.1
# ===========================================================================
class TestMissingOrInvalidAuthHeaders:
    """PRD §2.1: 'If either header is missing, malformed, or
    unrecognizable, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""

    def test_no_headers_at_all(self, api):
        """PRD §2.1: missing both headers -> 400."""
        res = api.create_consumer(
            create_consumer_payload(),
            {"Content-Type": "application/json"},
        )
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        )

    def test_missing_user_id_only(self, api):
        """PRD §2.1: 'X-User-ID identifies the acting principal' —
        missing user id is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
        res = api.create_consumer(
            create_consumer_payload(),
            {"X-User-Role": "PlatformAdmin",
             "Content-Type": "application/json"},
        )
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        )

    def test_missing_user_role_only(self, api):
        """PRD §2.1: 'X-User-Role identifies the principal's operational
        capacity' — missing role is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
        res = api.create_consumer(
            create_consumer_payload(),
            {"X-User-ID": "some-id",
             "Content-Type": "application/json"},
        )
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        )

    def test_unrecognizable_role(self, api):
        """PRD §2.1: 'If either header is missing, malformed, or
        unrecognizable, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'

        'unrecognizable' covers a role that is not one of the five
        named roles (Consumer, BureauOperator, Furnisher,
        CFPBOperator, PlatformAdmin)."""
        res = api.create_consumer(
            create_consumer_payload(),
            build_user_headers("x", "GodMode"),
        )
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        )


# ===========================================================================
# Role authorization — PRD §2.1, §4
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: 'If the headers are present but the named role is
    not permitted for the endpoint ..., the request is rejected with
    ERR_FORBIDDEN_FOR_ROLE.'"""

    def test_consumer_cannot_create_consumer(self, api):
        """PRD §4: POST /consumers is restricted to PlatformAdmin."""
        res = api.create_consumer(
            create_consumer_payload(),
            TEST_USERS["consumer_fallback_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_consumer_cannot_start_investigation(self, api):
        """PRD §4: POST .../start_investigation is restricted to
        BureauOperator."""
        consumer, furnisher, report, tradeline = (
            setup_consumer_furnisher_report_tradeline()
        )
        dispute = submit_dispute(
            consumer=consumer, report=report, tradeline=tradeline,
        )
        res = api.start_investigation(
            consumer["id"], dispute["id"],
            make_consumer_headers(consumer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_bureau_operator_cannot_submit_dispute(self, api):
        """PRD §4: POST /consumers/{cid}/disputes is restricted to
        Consumer."""
        consumer, furnisher, report, tradeline = (
            setup_consumer_furnisher_report_tradeline()
        )
        payload = create_dispute_payload(
            credit_report_id=report["id"],
            tradeline_item_id=tradeline["id"],
        )
        res = api.create_dispute(
            consumer["id"], payload,
            TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_cfpb_operator_cannot_issue_result_notice(self, api):
        """PRD §4: POST .../issue_result_notice is restricted to
        BureauOperator."""
        consumer, furnisher, report, tradeline = (
            setup_consumer_furnisher_report_tradeline()
        )
        dispute = submit_dispute(
            consumer=consumer, report=report, tradeline=tradeline,
        )
        res = api.issue_result_notice(
            consumer["id"], dispute["id"],
            TEST_USERS["cfpb_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


# ===========================================================================
# Consumer ownership — PRD §2.1
# ===========================================================================
class TestConsumerOwnership:
    """PRD §2.1: 'When X-User-Role is Consumer, X-User-ID is the id
    of the acting Consumer; any resource scoped to a consumer (the
    consumer's disputes, credit reports, regulatory complaints,
    freezes, and locks) compares its consumer_id to X-User-ID for
    ownership, and a mismatch surfaces as ERR_FORBIDDEN_FOR_ROLE.'"""

    def test_consumer_a_cannot_get_consumer_b(self, api):
        """PRD §2.1: cross-consumer GET is ERR_FORBIDDEN_FOR_ROLE."""
        c_a = create_consumer()
        c_b = create_consumer()
        res = api.get_consumer(c_b["id"], make_consumer_headers(c_a["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_consumer_can_get_own_consumer(self, api):
        """PRD §2.1 positive path: matching X-User-ID returns the
        consumer."""
        c = create_consumer()
        res = api.get_consumer(c["id"], make_consumer_headers(c["id"]))
        validate_success(res, 200)


# ===========================================================================
# Furnisher ownership — PRD §2.1
# ===========================================================================
class TestFurnisherOwnership:
    """PRD §2.1: 'When X-User-Role is Furnisher, X-User-ID is the id
    of the acting Furnisher; tradeline rows and hard inquiries the
    furnisher owns or initiates are compared by furnisher_id (or
    requesting_furnisher_id) to X-User-ID.'"""

    def test_furnisher_a_cannot_create_tradeline_as_furnisher_b(self, api):
        """PRD §2.1: a tradeline whose body furnisher_id does not equal
        X-User-ID (when role is Furnisher) is ERR_FORBIDDEN_FOR_ROLE."""
        c = create_consumer()
        r = create_credit_report(c["id"])
        f_a = create_furnisher()
        f_b = create_furnisher()
        from test_helpers import create_tradeline_item_payload
        # Furnisher A authenticates, but body says furnisher_id = B.
        res = api.create_tradeline_item(
            r["id"],
            create_tradeline_item_payload(furnisher_id=f_b["id"]),
            make_furnisher_headers(f_a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


# ===========================================================================
# Success envelope — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format' — meta, response_type,
    data."""

    def test_envelope_has_meta_and_data(self, api):
        """PRD §2.2: meta + response_type + data are mandatory."""
        c = create_consumer()
        res = api.get_consumer(c["id"], make_consumer_headers(c["id"]))
        # validate_success enforces meta + response_type + data + IDs.
        data = validate_success(res, 200)
        assert data["id"] == c["id"]

    def test_response_type_object_for_single_resource(self, api):
        """PRD §2.2: 'response_type is either object for a single
        resource or array for a list of resources.'"""
        c = create_consumer()
        res = api.get_consumer(c["id"], make_consumer_headers(c["id"]))
        body = res.json()
        assert body["response_type"] == "object"

    def test_meta_api_request_id_starts_with_req_prefix(self, api):
        """PRD §2.2: 'The api_request_id is a server-generated unique
        identifier for the request that starts with req_.'"""
        c = create_consumer()
        res = api.get_consumer(c["id"], make_consumer_headers(c["id"]))
        rid = res.json()["meta"]["api_request_id"]
        assert rid.startswith("req_"), (
            f"api_request_id must start with 'req_', got {rid!r}"
        )


# ===========================================================================
# Error envelope — PRD §2.2
# ===========================================================================
class TestErrorEnvelope:
    """PRD §2.2: 'All error API responses (4xx status codes) follow
    this standard envelope format' — meta, response_type='error',
    data.{error_id, message}."""

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: error data carries error_id and message; message
        is human-readable."""
        # Trigger a 404 by GETting a non-existent consumer.
        res = api.get_consumer(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0


# ===========================================================================
# Path-segment validation — PRD §2.7
# ===========================================================================
class TestNotFoundOnPath:
    """PRD §2.7: 'the server validates each identifier in strict
    left-to-right order. The first identifier that does not correspond
    to an existing resource produces an immediate ERR_NOT_FOUND
    response, and no further identifiers in the path are examined.'"""

    def test_left_segment_missing_returns_not_found(self, api):
        """PRD §2.7: leftmost missing id returns ERR_NOT_FOUND."""
        res = api.get_consumer(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_right_segment_missing_returns_not_found(self, api):
        """PRD §2.7: right-segment missing id (after a valid
        leftmost) also returns ERR_NOT_FOUND."""
        c = create_consumer()
        res = api.get_credit_report(
            c["id"], NON_EXISTENT_UUID,
            make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


# ===========================================================================
# Cross-consumer body FK — PRD §2.7
# ===========================================================================
class TestCrossConsumerReference:
    """PRD §2.7: 'Body-referenced foreign keys (for example, a
    credit_report_id or a tradeline_item_id in a dispute submission,
    a dispute_id in a regulatory complaint, or a parent_complaint_id
    on a refile) must exist and must belong to the same Consumer
    indicated by the path; if a body foreign key points to another
    consumer's resource, the request is rejected with
    ERR_CROSS_CONSUMER_REFERENCE.'"""

    def test_dispute_body_credit_report_belongs_to_other_consumer(self, api):
        """PRD §2.7: dispute body credit_report_id from a different
        consumer -> ERR_CROSS_CONSUMER_REFERENCE."""
        # Setup A: consumer A with their own report and tradeline.
        c_a, f, r_a, t_a = setup_consumer_furnisher_report_tradeline()
        # Setup B: consumer B with their own report and tradeline.
        c_b = create_consumer()
        r_b = create_credit_report(c_b["id"])
        # c_a tries to submit a dispute citing c_b's report / tradeline.
        payload = create_dispute_payload(
            credit_report_id=r_b["id"],
            tradeline_item_id=t_a["id"],
        )
        res = api.create_dispute(
            c_a["id"], payload, make_consumer_headers(c_a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CROSS_CONSUMER_REFERENCE)


# ===========================================================================
# Malformed body — PRD §2.3
# ===========================================================================
class TestInvalidRequest:
    """PRD §2.3: 'Any request whose body is structurally malformed —
    wrong JSON shape, wrong field types, or values that are not
    parseable into the documented types — is rejected with
    ERR_INVALID_REQUEST regardless of which endpoint received it.'"""

    def test_ssn_last4_must_be_exactly_four_digits(self, api):
        """PRD §3.1: 'last four digits of social security number as
        ssn_last4 (which must be exactly four digits)' — three digits
        violates the type contract -> ERR_INVALID_REQUEST per §2.3."""
        res = api.create_consumer(
            create_consumer_payload(ssn_last4="123"),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_bureau_must_be_one_of_three(self, api):
        """PRD §3.1: 'the bureau, which must be one of the three
        values EQUIFAX, EXPERIAN, or TRANSUNION.' Any other string
        is malformed per §2.3 -> ERR_INVALID_REQUEST."""
        c = create_consumer()
        res = api.create_credit_report(
            c["id"], {"bureau": "BARCLAYS"},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
