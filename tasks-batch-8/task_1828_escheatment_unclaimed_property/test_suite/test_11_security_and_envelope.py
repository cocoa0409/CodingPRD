"""Authentication, role gates, segregation of duties, claimant scoping,
envelope and pagination shape, and per-resource 404s (PRD §2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    get_success_data,
    make_claimant_headers,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.factories import create_owner_payload, create_dormancy_rule_payload
from test_helpers.fixtures import (
    CO,
    READER,
    SA,
    add_line_item,
    create_owner,
    create_report,
    create_reportable_property,
    create_rule,
    get_property,
    get_report,
    setup_remitted_cash_property,
    setup_under_review_claim,
    submit_report,
)

CO_H = TEST_USERS["compliance_officer_headers"]
SA_H = TEST_USERS["state_auditor_headers"]
TO_H = TEST_USERS["treasury_ops_headers"]
HA_H = TEST_USERS["holder_admin_headers"]
AP_H = TEST_USERS["claims_approver_headers"]


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing, or the role supplied is not
        one of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.create_owner(
            create_owner_payload(full_name="No Head"), headers={}
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400
        )

    def test_schema_error_beats_not_found(self, api):
        """PRD §2.10: "The layers, in order, are: first, the presence and
        validity of the authentication headers
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role
        authorization on the endpoint (`ERR_UNAUTHORIZED_ROLE`); third,
        request-body well-formedness — required fields present, types matching,
        enum values in range, date strings parseable, integers inside their
        declared ranges — with any violation rejected as `ERR_INVALID_REQUEST`
        (HTTP 400); fourth, left-to-right path existence per §2.9"

        Design: Corner/validations/schema_validation_priority_beats_not_found
        """
        resp = api.create_contact_event(NON_EXISTENT_UUID, {}, CO_H)
        # Body fails schema (missing contact_type/contact_date/evidence_ref);
        # the third layer fires before the fourth's not-found check.
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestRoleGates:
    def test_state_auditor_cannot_create_owner(self, api):
        """PRD §2.1: "Access to each operation is restricted by role per the
        endpoint table in §4; a caller whose role is not permitted on an
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §3.1: "A `ComplianceOfficer` registers an owner by supplying the
        `full_name`, the `last_known_address` as a free-form single line, and
        the `state_code`"

        Design: Corner/rbac/state_auditor_cannot_create_owner_unauthorized
        """
        resp = api.create_owner(create_owner_payload(full_name="Role Deny"), SA_H)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_treasury_cannot_accept_report(self, api):
        """PRD §2.1: "Access to each operation is restricted by role per the
        endpoint table in §4; a caller whose role is not permitted on an
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §3.4: "A `StateAuditor` accepts a report that is `SUBMITTED` (else
        `ERR_REPORT_NOT_SUBMITTED`)"

        Design: Corner/rbac/treasury_cannot_accept_report_unauthorized
        """
        _, _, prop, _ = create_reportable_property(original_value_cents=80000)
        report = create_report()
        add_line_item(report["id"], prop["id"])
        submit_report(report["id"])
        resp = api.accept_report(report["id"], TO_H)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        assert get_report(report["id"])["status"] == "SUBMITTED"

    def test_examiner_cannot_approve(self, api):
        """PRD §2.1: "`ClaimsExaminer` opens claim review and requests
        information but is forbidden from approving or denying, under
        segregation of duties."
        PRD §2.1: "Access to each operation is restricted by role per the
        endpoint table in §4; a caller whose role is not permitted on an
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/examiner_cannot_approve_unauthorized
        """
        chain = setup_under_review_claim(original_value_cents=90000)
        other_examiner = build_user_headers("ce-2", "ClaimsExaminer")
        resp = api.approve_claim(chain["claim"]["id"], other_examiner)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        still = get_success_data(api.get_claim(chain["claim"]["id"], READER), 200)
        assert still["status"] == "UNDER_REVIEW"


class TestSegregationOfDuties:
    def test_acceptor_must_differ_from_submitter(self, api):
        """PRD §2.1: "Segregation of duties is enforced wherever one officer's
        work must be checked by another: the operator who accepts a submitted
        report must not be the operator recorded as its `submitted_by_user_id`,
        and the approver or denier of a claim must not be the examiner recorded
        as its `reviewed_by_user_id`. A violation of either rule is rejected
        with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_report_accept_by_submitter_rejected
        """
        _, _, prop, _ = create_reportable_property(original_value_cents=80000)
        report = create_report()
        add_line_item(report["id"], prop["id"])
        submitted = submit_report(report["id"])  # submitted by user co-1
        assert submitted["submitted_by_user_id"] == "co-1"
        # Same human, different hat: StateAuditor role with X-User-ID co-1.
        resp = api.accept_report(
            report["id"], build_user_headers("co-1", "StateAuditor")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)
        assert get_report(report["id"])["status"] == "SUBMITTED"

    def test_approver_must_differ_from_reviewer(self, api):
        """PRD §3.7: "A `ClaimsApprover` approves or denies an `UNDER_REVIEW`
        claim, and in both cases the approver's `X-User-ID` must differ from
        the recorded `reviewed_by_user_id` — the same person may never examine
        and decide — else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        Design: Corner/rbac/sod_claim_approve_by_reviewer_rejected
        """
        chain = setup_under_review_claim(original_value_cents=90000)
        assert chain["claim"]["reviewed_by_user_id"] == "ce-1"
        reviewer_as_approver = build_user_headers("ce-1", "ClaimsApprover")
        e1 = api.approve_claim(chain["claim"]["id"], reviewer_as_approver)
        validate_error(e1, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)
        e2 = api.deny_claim(
            chain["claim"]["id"],
            {"denial_reason": "reviewer self-denial attempt"},
            reviewer_as_approver,
        )
        validate_error(e2, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)
        still = get_success_data(api.get_claim(chain["claim"]["id"], READER), 200)
        assert still["status"] == "UNDER_REVIEW"


class TestClaimantScoping:
    def test_claimant_self_service_allowed(self, api):
        """PRD §3.7: "A `Claimant` files through a payload naming the
        `property_id` and, optionally, an `evidence_ref`. The claim's
        `claimant_owner_id` is set to the filer's `X-User-ID` and must equal
        the property's owner"
        PRD §3.1: "when the caller is a `Claimant`, single-resource reads of an
        owner, a property, or a claim succeed only where the record's owner
        linkage equals the caller's `X-User-ID`, and otherwise fail with
        `ERR_OWNERSHIP_SCOPE_VIOLATION`."

        Design: Corner/rbac/claimant_self_service_allowed
        """
        chain = setup_remitted_cash_property(original_value_cents=90000)
        owner_id = chain["owner"]["id"]
        claim = validate_success(
            api.create_claim(
                {"property_id": chain["property"]["id"], "evidence_ref": "id-scan-1"},
                make_claimant_headers(owner_id),
            ),
            201,
        )
        assert claim["status"] == "SUBMITTED"
        assert claim["claimant_owner_id"] == owner_id
        assert claim["claim_type"] == "CASH"
        claims, meta = validate_paginated(
            api.list_owner_claims(owner_id, make_claimant_headers(owner_id))
        )
        assert meta["total_count"] == 1
        assert claims[0]["id"] == claim["id"]

    def test_claimant_cannot_read_other_claim(self, api):
        """PRD §3.1: "when the caller is a `Claimant`, single-resource reads of
        an owner, a property, or a claim succeed only where the record's owner
        linkage equals the caller's `X-User-ID`, and otherwise fail with
        `ERR_OWNERSHIP_SCOPE_VIOLATION`."

        Design: Corner/rbac/claimant_cannot_read_other_claim_forbidden
        """
        chain = setup_remitted_cash_property(original_value_cents=90000)
        claim = get_success_data(
            api.create_claim(
                {"property_id": chain["property"]["id"]},
                make_claimant_headers(chain["owner"]["id"]),
            ),
            201,
        )
        other_owner = create_owner(full_name="Own Er")
        resp = api.get_claim(claim["id"], make_claimant_headers(other_owner["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_SCOPE_VIOLATION, 403)

    def test_claimant_cannot_claim_others_property(self, api):
        """PRD §3.7: "The claim's `claimant_owner_id` is set to the filer's
        `X-User-ID` and must equal the property's owner — a claimant touching
        another owner's property is refused with
        `ERR_OWNERSHIP_SCOPE_VIOLATION`."

        Design: Corner/rbac/claimant_cannot_claim_others_property_forbidden
        """
        chain = setup_remitted_cash_property(original_value_cents=90000)
        other_owner = create_owner(full_name="Own Cee")
        resp = api.create_claim(
            {"property_id": chain["property"]["id"]},
            make_claimant_headers(other_owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_SCOPE_VIOLATION, 403)
        claims, meta = validate_paginated(
            api.list_property_claims(chain["property"]["id"], READER)
        )
        assert meta["total_count"] == 0


class TestListEnvelopeAndPagination:
    def test_pagination_windows_and_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated list-based responses include the following fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either \"object\" for a single
        resource or \"array\" for a list of resources."

        Design: Corner/endpoints/list_pagination_and_envelope_shape
        """
        for sc, pt, yrs in (("CA", "SAVINGS", 3), ("NV", "SAVINGS", 3),
                            ("TX", "SAVINGS", 5)):
            create_rule(state_code=sc, property_type=pt, dormancy_years=yrs)
        page1, meta1 = validate_paginated(
            api.list_dormancy_rules(READER, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api.list_dormancy_rules(READER, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        page_all, meta_all = validate_paginated(api.list_dormancy_rules(READER))
        assert len(page_all) == 3
        assert meta_all["limit"] == 10
        assert meta_all["offset"] == 0
        body = api.list_dormancy_rules(READER).json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestNotFound:
    def test_property_not_found(self, api):
        """PRD §2.9: "Identifiers are validated in sequential, left-to-right
        order, and the request is rejected immediately with the not-found error
        corresponding to the first identifier that does not exist"

        Design: Corner/entities/property_get_not_found_returns_404
        """
        resp = api.get_property(NON_EXISTENT_UUID, READER)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND, 404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]

    def test_resource_specific_not_found_ids(self, api):
        """PRD §2.9: "Identifiers are validated in sequential, left-to-right
        order, and the request is rejected immediately with the not-found error
        corresponding to the first identifier that does not exist:
        `ERR_OWNER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`,
        `ERR_DORMANCY_RULE_NOT_FOUND`, `ERR_CONTACT_EVENT_NOT_FOUND`,
        `ERR_LETTER_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        `ERR_LINE_ITEM_NOT_FOUND`, `ERR_SECURITIES_DETAIL_NOT_FOUND`,
        `ERR_LIQUIDATION_ORDER_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_PENALTY_ASSESSMENT_NOT_FOUND`,
        `ERR_AUDIT_CASE_NOT_FOUND`, or `ERR_DOCUMENT_RECORD_NOT_FOUND` (each
        HTTP 404)."

        Design: Corner/errors/not_found_errors_across_resources
        """
        cases = [
            (lambda: api.get_owner(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_OWNER_NOT_FOUND),
            (lambda: api.get_dormancy_rule(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_DORMANCY_RULE_NOT_FOUND),
            (lambda: api.get_report(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_REPORT_NOT_FOUND),
            (lambda: api.get_letter(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_LETTER_NOT_FOUND),
            (lambda: api.get_liquidation_order(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_LIQUIDATION_ORDER_NOT_FOUND),
            (lambda: api.get_remittance(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_REMITTANCE_NOT_FOUND),
            (lambda: api.get_claim(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_CLAIM_NOT_FOUND),
            (lambda: api.get_penalty_assessment(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_PENALTY_ASSESSMENT_NOT_FOUND),
            (lambda: api.get_audit_case(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_AUDIT_CASE_NOT_FOUND),
            (lambda: api.get_document_record(NON_EXISTENT_UUID, READER),
             ApiErrorId.ERR_DOCUMENT_RECORD_NOT_FOUND),
        ]
        for call, error_id in cases:
            validate_error(call(), error_id, 404)
