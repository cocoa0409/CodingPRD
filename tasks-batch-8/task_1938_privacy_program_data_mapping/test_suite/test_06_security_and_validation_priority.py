"""Authentication, authorization, ownership, segregation of duties, and
validation priority ordering (PRD §2.1, §2.8, §3.5)."""
from test_helpers import (
    ApiErrorId,
    BO1,
    DS,
    LC1,
    LC9,
    NON_EXISTENT_UUID,
    PA,
    TEST_USERS,
    VM,
    assert_vendor,
    create_activity_with_manual_assessment,
    create_consumer,
    create_consumer_and_request,
    create_notice_payload,
    create_retention_policy_payload,
    create_rights_request_payload,
    create_vendor_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_consumer_headers,
    make_legal_counsel_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestValidationPriorityAuth:
    def test_unauthenticated_beats_not_found(self, api):
        """PRD §2.8: "Authentication (ERR_UNAUTHENTICATED) is checked first, then
        authorization (ERR_FORBIDDEN_ROLE). Path-id and body-supplied
        foreign-key existence (ERR_NOT_FOUND) comes next, with path identifiers
        validated left-to-right."

        Design: Corner/validations/unauthenticated_beats_not_found
        """
        resp = api.get_vendor(NON_EXISTENT_UUID, headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_role_check_beats_existence(self, api):
        """PRD §2.8: "Authentication (ERR_UNAUTHENTICATED) is checked first, then
        authorization (ERR_FORBIDDEN_ROLE). Path-id and body-supplied
        foreign-key existence (ERR_NOT_FOUND) comes next"

        Design: Corner/validations/role_check_beats_existence
        """
        consumer = create_consumer(email="tx@x.com", state_code="TX")
        resp = api.approve_vendor(NON_EXISTENT_UUID,
                                  headers=make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_err_unauthenticated_missing_headers(self, api):
        """PRD §2.1: "If either header is missing, or if the role value is not
        one of the declared roles, the server rejects the request with
        ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/errors/err_unauthenticated_missing_headers
        """
        resp = api.create_retention_policy(
            create_retention_policy_payload(policy_code="RP-X", duration_days=10),
            headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_err_forbidden_role_on_admin_endpoint(self, api):
        """PRD §2.1: "If the caller's role is not in the endpoint's authorized
        role list, or if a Consumer attempts to act on another consumer's
        resources, the server rejects the request with ERR_FORBIDDEN_ROLE (HTTP
        403)."

        Design: Corner/errors/err_forbidden_role_on_admin_endpoint
        """
        resp = api.create_notice(create_notice_payload(title="t"), DS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestRbacExclusiveOperations:
    def test_rbac_business_owner_cannot_approve_assessment(self, api):
        """PRD §2.1: "BusinessOwner is the business unit owner who submits
        privacy impact assessments for review. LegalCounsel is the legal reviewer
        who decides PIAs, verifies contracts, assesses transfers, and denies
        rights requests."
        PRD §2.1: "If the caller's role is not in the endpoint's authorized role
        list, or if a Consumer attempts to act on another consumer's resources,
        the server rejects the request with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/rbac_business_owner_cannot_approve_assessment
        """
        _activity, pia = create_activity_with_manual_assessment()
        # pia is IN_REVIEW (submitted by bo-1); approval is LegalCounsel-only
        resp = api.approve_assessment(pia["id"], BO1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_consumer_cannot_create_vendor(self, api):
        """PRD §2.1: "VendorManager owns the vendor register and the contract
        lifecycle."
        PRD §2.1: "If the caller's role is not in the endpoint's authorized role
        list, or if a Consumer attempts to act on another consumer's resources,
        the server rejects the request with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/rbac_consumer_cannot_create_vendor
        """
        consumer = create_consumer(email="tx@x.com", state_code="TX")
        resp = api.create_vendor(
            create_vendor_payload(vendor_name="Sneaky", home_region="US",
                                  processes_categories=[]),
            headers=make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_consumer_cannot_read_other_consumers_requests(self, api):
        """PRD §2.1: "When X-User-Role is Consumer, X-User-ID is the id of the
        acting Consumer; ownership checks on any resource that references a
        Consumer compare the resource's foreign-key field to X-User-ID, so a
        consumer may file requests only for itself and may read only its own
        requests."

        Design: Corner/rbac/rbac_consumer_cannot_read_other_consumers_requests
        """
        cons_a, req_a = create_consumer_and_request(
            email="a@x.com", state_code="TX", request_type="ACCESS",
            requested_categories=["BASIC_CONTACT"])
        cons_b = create_consumer(email="b@x.com", full_name="B One", state_code="TX")

        resp = api.list_consumer_requests(cons_a["id"],
                                          headers=make_consumer_headers(cons_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        own = validate_success(
            api.list_consumer_requests(cons_a["id"],
                                       headers=make_consumer_headers(cons_a["id"])))
        assert len(own) == 1
        assert own[0]["id"] == req_a["id"]

    def test_rbac_legal_cannot_publish_notice(self, api):
        """PRD §2.1: "PrivacyAdmin is the privacy office administrator and owns
        configuration, notices, vendor approval, transfers, applicability runs,
        and the logical clock."
        PRD §2.1: "If the caller's role is not in the endpoint's authorized role
        list, or if a Consumer attempts to act on another consumer's resources,
        the server rejects the request with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/rbac_legal_cannot_publish_notice
        """
        notice = get_success_data(api.create_notice(create_notice_payload(title="t"), PA))
        resp = api.publish_notice(notice["id"], LC1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = get_success_data(api.get_notice(notice["id"], PA))
        assert after["status"] == "DRAFT"

    def test_rbac_shared_reads_allowed_for_all_staff(self, api):
        """PRD §2.1: "For PrivacyAdmin, DataSteward, BusinessOwner, LegalCounsel,
        and VendorManager, X-User-ID is an opaque operator identifier not tied to
        any persisted entity."
        PRD §4: the authorized roles for GET /privacy/vendors/{id} are
        "PrivacyAdmin, DataSteward, LegalCounsel, VendorManager, BusinessOwner".
        PRD §2.1: "If the caller's role is not in the endpoint's authorized role
        list, or if a Consumer attempts to act on another consumer's resources,
        the server rejects the request with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/rbac/rbac_shared_reads_allowed_for_all_staff
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=[]), VM))
        consumer = create_consumer(email="tx@x.com", state_code="TX")

        for role_headers in (PA, DS, LC1, VM, TEST_USERS["business_owner_headers"]):
            data = validate_success(api.get_vendor(vendor["id"], headers=role_headers))
            assert data["id"] == vendor["id"]

        resp = api.get_vendor(vendor["id"], headers=make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestSegregationOfDutiesEnforcement:
    def test_rbac_sod_submitter_cannot_approve_own(self, api):
        """PRD §3.5: "All three reviewer actions require that the reviewer's
        X-User-ID differ from the assessment's submitted_by_user_id; a reviewer
        who is also the most recent submitter is rejected with
        ERR_SEGREGATION_OF_DUTIES."
        PRD §3.5: "A BusinessOwner submits an assessment in TRIGGERED or
        CHANGES_REQUESTED status; the assessment moves to IN_REVIEW and its
        submitted_by_user_id is set to the caller's X-User-ID."

        Design: Corner/rbac/rbac_sod_submitter_cannot_approve_own
        """
        _activity, pia = create_activity_with_manual_assessment(submitter_headers=BO1)
        assert pia["submitted_by_user_id"] == "bo-1"

        # a LegalCounsel whose X-User-ID equals the submitter's id is rejected
        resp = api.approve_assessment(pia["id"], make_legal_counsel_headers("bo-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        # a different reviewer id passes the SoD check
        approved = get_success_data(api.approve_assessment(pia["id"], LC9))
        assert approved["status"] == "APPROVED"

    def test_state_vs_sod_on_approve(self, api):
        """PRD §2.8: "Lifecycle-state permission (ERR_INVALID_STATE_TRANSITION)
        is then checked on every state-transition endpoint, covering both
        invalid-from and terminal lockdown. Cross-dimension and parent-state
        gates — routing while unverified, creating a purpose or assessment on a
        retired activity, responding before tasks are done — come after that,
        surfacing ERR_REQUEST_NOT_VERIFIED, ERR_ACTIVITY_RETIRED, or
        ERR_TASKS_OUTSTANDING. Segregation of duties (ERR_SEGREGATION_OF_DUTIES)
        is checked next"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_sod_on_approve
        """
        _activity, pia = create_activity_with_manual_assessment(submitter_headers=BO1)
        # IN_REVIEW, submitted_by bo-1 -> request changes -> CHANGES_REQUESTED
        get_success_data(api.request_changes_assessment(pia["id"], LC1))

        # Caller IS the submitter (SoD fails) AND the state is CHANGES_REQUESTED
        # (approve is IN_REVIEW-only, so the state gate fails too); the
        # lifecycle-state check outranks segregation of duties.
        resp = api.approve_assessment(pia["id"], make_legal_counsel_headers("bo-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = get_success_data(api.get_assessment(pia["id"], LC1))
        assert after["status"] == "CHANGES_REQUESTED"
        assert after["final_score"] is None

    def test_state_gate_on_reject_from_changes_requested(self, api):
        """PRD §2.8: "Lifecycle-state permission (ERR_INVALID_STATE_TRANSITION)
        is then checked on every state-transition endpoint, covering both
        invalid-from and terminal lockdown."
        PRD §3.5: "From IN_REVIEW, a LegalCounsel reviewer may request changes,
        approve, or reject."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_sod_on_approve
        """
        _activity, pia = create_activity_with_manual_assessment(submitter_headers=BO1)
        get_success_data(api.request_changes_assessment(pia["id"], LC1))

        # Reject is defined only from IN_REVIEW; from CHANGES_REQUESTED the state
        # gate rejects — even for a caller whose id differs from the submitter's.
        resp = api.reject_assessment(pia["id"], make_legal_counsel_headers("bo-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_assessment(pia["id"], LC1))
        assert after["status"] == "CHANGES_REQUESTED"


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success_and_error(self, api):
        """PRD §2.2: "The api_request_id is a server-generated unique identifier
        for the request that starts with req_. The api_request_timestamp is a
        server-generated ISO 8601 UTC timestamp with three fractional digits. The
        response_type is either "object" for a single resource or "array" for a
        list of resources."
        PRD §2.2: "The meta object for error responses contains only
        api_request_id and api_request_timestamp. The error_id is a unique,
        machine-readable string that identifies the specific error. The message
        provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="DataPro", home_region="US",
                                  processes_categories=[]), VM))

        ok_resp = api.get_vendor(vendor["id"], DS)
        assert ok_resp.status_code == 200
        body = ok_resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == vendor["id"]
        assert_vendor(body["data"])

        err_resp = api.get_vendor(NON_EXISTENT_UUID, DS)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert set(err_body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]
