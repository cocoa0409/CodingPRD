"""Optimistic concurrency, authentication/authorization layers, scope checks,
response envelope, pagination, not-found, and request-shape validation
(PRD §2.1-§2.9, §3.5, §3.6)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_us_rule,
    create_client,
    create_contact,
    create_family,
    create_application,
    create_pending_application,
    create_granted_application,
    create_jurisdiction_rule_payload,
    list_obligations,
    get_obligation,
    get_application,
    request_authorization,
    propose_review,
    make_client_approver_headers,
)

ANY = TEST_USERS["any_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["clerk_headers"]
MGR = TEST_USERS["manager_headers"]
FIN = TEST_USERS["finance_headers"]


class TestOccAuthorizationCreate:
    def test_observed_version_accepted_and_bumps_version(self):
        """PRD §3.5: "The request creates a **PaymentAuthorization** in
        `REQUESTED` status, records the acting header as its
        `requested_by_user_id`, binds it to the obligation via
        `annuity_obligation_id`, moves the obligation `SCHEDULED →
        `PENDING_AUTHORIZATION`, and increments the obligation's `version` by
        one."

        Design: Corner/cross_cutting_complexity_layers/occ_authorization_create_stale_version
        """
        from test_helpers import setup_world_with_granted_app
        world = setup_world_with_granted_app(client_name="OccCo")
        obligation = world["obligations"][0]
        v1 = get_obligation(obligation["id"])["version"]
        au, _ = request_authorization(obligation["id"], 10000)
        assert au["status"] == "REQUESTED"
        assert au["requested_by_user_id"] == "mgr-1"
        v2 = get_obligation(obligation["id"])["version"]
        assert v2 == v1 + 1

    def test_stale_version_rejected_after_reject_cycle(self):
        """PRD §2.8: "If the obligation's current `version` has advanced since
        that read — for example because another writer has just requested an
        authorization, which moves the obligation to `PENDING_AUTHORIZATION`
        and increments its version, or because a recalculation touched the
        obligation — the request is rejected with `ERR_STALE_VERSION` (HTTP
        412), preventing the client from acting on an obligation state it has
        not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_authorization_create_stale_version
        """
        from test_helpers import setup_world_with_granted_app
        world = setup_world_with_granted_app(client_name="OccCo")
        obligation = world["obligations"][0]
        v1 = get_obligation(obligation["id"])["version"]
        au, _ = request_authorization(obligation["id"], 10000)
        validate_success(
            api_client.reject_authorization(au["id"], make_client_approver_headers(world["contact"]["id"])),
            200)
        # Obligation is back in SCHEDULED but its version advanced; replaying
        # the original observed version is stale.
        validate_error(
            api_client.create_authorization(
                obligation["id"],
                {"amount_cents": 10000, "expected_annuity_obligation_version": v1},
                MGR),
            ApiErrorId.ERR_STALE_VERSION)
        # The current version is accepted.
        v3 = get_obligation(obligation["id"])["version"]
        au2 = validate_success(api_client.create_authorization(
            obligation["id"],
            {"amount_cents": 9000, "expected_annuity_obligation_version": v3},
            MGR), 201)
        assert au2["amount_cents"] == 9000


class TestOccReviewCreate:
    def test_review_creation_bumps_application_version(self):
        """PRD §3.6: "The review starts `PROPOSED`, and its creation increments
        the application's `version` by one, which is precisely what makes a
        second proposer's older read stale."

        Design: Corner/cross_cutting_complexity_layers/occ_review_create_stale_application_version
        """
        create_us_rule()
        client = create_client("OccRv")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-OR")
        v1 = get_application(app["id"])["version"]
        review = propose_review(app["id"], rationale="first")
        assert review["status"] == "PROPOSED"
        v2 = get_application(app["id"])["version"]
        assert v2 == v1 + 1

    def test_stale_application_version_rejected(self):
        """PRD §2.8: "proposing an abandonment review against an application
        requires the non-optional field `expected_application_version`,
        carrying the `version` of the application as the client last observed
        it. A prior review proposal legitimately opened review state on the
        application and incremented its version, so a creator holding an older
        version works from a stale read; the mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_review_create_stale_application_version
        """
        create_us_rule()
        client = create_client("OccRv")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-OR")
        v1 = get_application(app["id"])["version"]
        propose_review(app["id"], rationale="first")
        validate_error(
            api_client.create_abandonment_review(
                app["id"], {"rationale": "stale", "expected_application_version": v1}, MGR),
            ApiErrorId.ERR_STALE_VERSION)


class TestAuthenticationLayer:
    def test_missing_auth_headers_rejected(self):
        """PRD §2.1: "Failure to provide both headers, presenting an
        `X-User-Role` value that is not one of the declared role names, or —
        for the entity-backed roles below — presenting an `X-User-ID` that does
        not reference an existing instance of the backing entity is rejected
        with an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        # This call intentionally omits the X-User-ID / X-User-Role headers.
        validate_error(api_client.create_client({"display_name": "NoHdr"}, headers={}),
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_header_check_precedes_role_check(self):
        """PRD §2.9: "1. **User context.** Both authentication headers present,
        the role declared, and any entity-backed identifier resolving to an
        existing instance — otherwise
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. 2. **Role
        authorization.** The acting role is permitted on the endpoint —
        otherwise `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/validations/priority_auth_header_precedes_role_check
        """
        # No auth headers at all, on an endpoint a clerk could not use anyway:
        # the priority-1 header error must surface, never ERR_FORBIDDEN_FOR_ROLE.
        validate_error(
            api_client.create_jurisdiction_rule(create_jurisdiction_rule_payload(), headers={}),
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestForbiddenForRole:
    def test_clerk_cannot_create_jurisdiction_rule(self):
        """PRD §2.1: "an attempt to perform an action outside of the caller's
        designated role is rejected with an `ERR_FORBIDDEN_FOR_ROLE` error";
        PRD §4 assigns POST /jurisdiction-rules to PlatformAdmin.

        Design: Corner/validations/forbidden_role_denied_on_exclusive_ops
        """
        validate_error(
            api_client.create_jurisdiction_rule(
                create_jurisdiction_rule_payload(jurisdiction="KR"), CLERK),
            ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_client_approver_cannot_create_application(self):
        """PRD §2.1: "an attempt to perform an action outside of the caller's
        designated role is rejected with an `ERR_FORBIDDEN_FOR_ROLE` error";
        PRD §4 assigns POST /families/{familyId}/applications to
        DocketingClerk.

        Design: Corner/validations/forbidden_role_denied_on_exclusive_ops
        """
        create_us_rule()
        client = create_client("RoleCo")
        contact = create_contact(client["id"])
        family = create_family(client["id"], budget_cap_cents=1000000)
        validate_error(
            api_client.create_application(
                family["id"],
                {"jurisdiction": "US", "application_type": "ORIGINAL",
                 "filing_date": "2026-02-01", "application_number": "US-RO2",
                 "entity_size": "LARGE"},
                make_client_approver_headers(contact["id"])),
            ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_finance_officer_cannot_approve_authorization(self):
        """PRD §2.1: "an attempt to perform an action outside of the caller's
        designated role is rejected with an `ERR_FORBIDDEN_FOR_ROLE` error";
        PRD §4 assigns POST /authorizations/{authorizationId}/approve to
        ClientApprover.

        Design: Corner/validations/forbidden_role_denied_on_exclusive_ops
        """
        from test_helpers import setup_world_with_granted_app
        world = setup_world_with_granted_app(client_name="RoleCo")
        obligation = world["obligations"][0]
        au, _ = request_authorization(obligation["id"], 10000)
        validate_error(api_client.approve_authorization(au["id"], FIN),
                       ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestClientApproverScope:
    def test_approver_from_wrong_client_rejected(self):
        """PRD §2.1: "ownership checks on a resource compare the contact's
        `client_id` to the client that owns the resource's patent family, and a
        mismatch is a scope violation"; PRD §3.5: "The scope check requires the
        acting contact's `client_id` to equal the client owning the
        obligation's family (`ERR_SCOPE_VIOLATION`)."

        Design: Corner/validations/scope_violation_client_approver_wrong_client
        """
        create_us_rule()
        client_a = create_client("CliA")
        client_b = create_client("CliB")
        contact_a = create_contact(client_a["id"], full_name="A Contact", email="a@x.com")
        contact_b = create_contact(client_b["id"], full_name="B Contact", email="b@x.com")
        family_b = create_family(client_b["id"], budget_cap_cents=1000000)
        app_b = create_granted_application(family_b["id"], application_number="US-B1")
        obligation = list_obligations(app_b["id"])[0]
        au, _ = request_authorization(obligation["id"], 10000)
        validate_error(
            api_client.approve_authorization(au["id"], make_client_approver_headers(contact_a["id"])),
            ApiErrorId.ERR_SCOPE_VIOLATION)
        data = validate_success(
            api_client.approve_authorization(au["id"], make_client_approver_headers(contact_b["id"])), 200)
        assert data["status"] == "APPROVED"


class TestRequestShapeValidation:
    def test_missing_required_field_rejected(self):
        """PRD §2.9: "Required fields present, no undeclared fields, enum
        values within their declared sets, date fields in ISO YYYY-MM-DD form,
        integers where integers are declared, and — on docket audits —
        `window_start` strictly earlier than `window_end`; violations are
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/entity_required_and_enum_validation
        """
        create_us_rule()
        client = create_client("ReqCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        resp = api_client.create_application(
            family["id"],
            {"application_type": "ORIGINAL", "filing_date": "2026-02-01",
             "application_number": "US-M1", "entity_size": "LARGE"},
            CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_enum_outside_declared_set_rejected(self):
        """PRD §2.9: "Required fields present, no undeclared fields, enum
        values within their declared sets, date fields in ISO YYYY-MM-DD
        form, integers where integers are declared, and — on docket audits —
        `window_start` strictly earlier than `window_end`; violations are
        rejected with `ERR_INVALID_REQUEST`." PRD §3.2: "an `entity_size` of `LARGE` or
        `SMALL`."

        Design: Corner/entities/entity_required_and_enum_validation
        """
        create_us_rule()
        client = create_client("ReqCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        resp = api_client.create_application(
            family["id"],
            {"jurisdiction": "US", "application_type": "ORIGINAL",
             "filing_date": "2026-02-01", "application_number": "US-M2",
             "entity_size": "MEGA"},
            CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFound:
    def test_get_with_nonexistent_id_returns_not_found(self):
        """PRD §2.9: "the request is rejected with `ERR_NOT_FOUND` for the
        first identifier that does not resolve; only then are body-supplied
        references — `parent_application_id`, `counsel_firm_id`,
        `docket_entry_id`, and each element of `inventor_ids` — resolved"

        Design: Corner/entities/entity_not_found_on_read_and_path_parent
        """
        validate_error(api_client.get_application(NON_EXISTENT_UUID, ANY),
                       ApiErrorId.ERR_NOT_FOUND)

    def test_child_creation_under_nonexistent_parent_path_returns_not_found(self):
        """PRD §2.9: "Path identifiers are validated left to right, and the
        request is rejected with `ERR_NOT_FOUND` for the first identifier that
        does not resolve; only then are body-supplied references —
        `parent_application_id`, `counsel_firm_id`, `docket_entry_id`, and
        each element of `inventor_ids` — resolved, each failure also producing
        `ERR_NOT_FOUND`."

        Design: Corner/entities/entity_not_found_on_read_and_path_parent
        """
        validate_error(api_client.create_docket_entry(
            NON_EXISTENT_UUID,
            {"entry_type": "STATUTORY", "title": "X", "base_due_date": "2026-09-01"},
            CLERK), ApiErrorId.ERR_NOT_FOUND)


class TestResponseEnvelope:
    def test_success_envelope_shape(self):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources" and "The `api_request_id`
        is a server-generated unique identifier for the request that starts
        with `req_`."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        resp = api_client.create_client({"display_name": "EnvCo"}, ADMIN)
        body = resp.json()
        assert resp.status_code == 201
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["response_type"] == "object"
        assert body["data"]["id"]

    def test_error_envelope_shape(self):
        """PRD §2.2 error format: "The `meta` object for error responses
        contains only `api_request_id` and `api_request_timestamp`" and "The
        `error_id` is a unique, machine-readable string that identifies the
        specific error."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        resp = api_client.get_client(NON_EXISTENT_UUID, ANY)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)


class TestListPagination:
    def test_limit_offset_total_count_has_more(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return" and "The `offset` parameter specifies the number of
        items to skip and defaults to 0" and "Paginated and non-paginated
        list-based responses include the following fields in the `meta` object
        of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/list_pagination_limit_offset_has_more
        """
        create_us_rule()
        client = create_client("PageCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        for i in range(1, 4):
            create_application(family["id"], application_number=f"US-P{i}",
                               filing_date=f"2026-02-0{i}")
        page1, meta1 = validate_paginated(
            api_client.list_applications_of_family(family["id"], ANY, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api_client.list_applications_of_family(family["id"], ANY, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
