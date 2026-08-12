"""Corner queue: response envelope, pagination, auth headers, existence order,
logical clock, sweep counters, version semantics, read-after-write consistency."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_account,
    begin_fieldwork,
    create_customer,
    create_engagement,
    create_finding,
    create_rep,
    get_account,
    post_wire,
    run_daily_sweep,
    set_clock,
    setup_pending_account,
    submit_and_verify_document,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_rep_headers


class TestErrorEnvelopeShapeOnFailure:
    def test_error_envelope_carries_error_id_message_and_request_meta(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format" with `"response_type": "error"` and a data object carrying
        `"error_id"` and `"message"` — "The `error_id` is a unique, machine-readable
        string that identifies the specific error" and "The `message` provides a
        human-readable explanation of what went wrong" — while "The `meta` object for
        error responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape_on_failure
        """
        create_rep(full_name="Rep R1", crd_number="CRD-R01")
        resp = api_client.get_account(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_ACCOUNT_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert body["meta"]["api_request_id"], "meta.api_request_id must be present"


class TestPaginationLimitBoundsRejected:
    def test_limit_below_min_and_above_max_rejected(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items and defaults to 0. Values outside these
        bounds are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/pagination_limit_bounds_rejected
        """
        create_rep(full_name="Rep P1", crd_number="CRD-P01")
        resp = api_client.list_reps(TEST_USERS["admin_headers"], params={"limit": 0})
        error = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert error["error_id"] == "ERR_INVALID_REQUEST"
        resp = api_client.list_reps(TEST_USERS["admin_headers"], params={"limit": 101})
        error = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert error["error_id"] == "ERR_INVALID_REQUEST"

        resp = api_client.list_reps(TEST_USERS["admin_headers"], params={"limit": 100})
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1 and meta["total_count"] == 1, (
            "limit=100 is within bounds and must be accepted"
        )


class TestCustomersListPaginationEnvelope:
    def test_pagination_pages_and_meta_fields(self, api):
        """PRD §2.3: "The `meta` object of list responses carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."
        Three customers with limit=2: page 1 has 2 rows with total_count 3 and
        has_more true; page 2 (offset 2) has the remaining row with has_more false.

        Design: Corner/entities/customers_list_pagination_envelope
        """
        rep = create_rep(full_name="Rep E5", crd_number="CRD-ENT5")
        for name, tin in (("P1", "TIN-E5a"), ("P2", "TIN-E5b"), ("P3", "TIN-E5c")):
            create_customer(rep, full_name=name, tax_id=tin)

        resp = api_client.list_customers(
            TEST_USERS["officer_headers"], params={"limit": 2, "offset": 0}
        )
        page1, meta1 = validate_paginated(resp)
        assert len(page1) == 2, f"page 1 must hold 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert resp.json()["meta"]["api_request_id"].startswith("req_")

        resp = api_client.list_customers(
            TEST_USERS["officer_headers"], params={"limit": 2, "offset": 2}
        )
        page2, meta2 = validate_paginated(resp)
        assert len(page2) == 1, f"page 2 must hold the remaining row, got {len(page2)}"
        assert meta2["has_more"] is False


class TestMissingAuthHeadersReturnsUnauthenticated:
    def test_no_headers_rejected_before_existence_check(self, api):
        """PRD §2.9: "1. Header context first — a missing or malformed `X-User-ID` or
        `X-User-Role` surfaces as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400)
        before anything else."
        Sent against a non-existent account id to prove auth runs before the 404 check.

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        create_rep(full_name="Rep V1", crd_number="CRD-V01")
        resp = api_client.get_account(NON_EXISTENT_UUID, headers={})
        error = validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
        )
        assert error["error_id"] == "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
        assert resp.status_code == 400


class TestExistenceCheckedBeforeStateOnReverse:
    def test_reverse_nonexistent_transaction_returns_404(self, api):
        """PRD §2.8: "Paths that carry multiple identifiers are validated left to
        right: the first path identifier that does not correspond to an existing
        resource determines the rejection, before any business rule is evaluated" —
        "a missing transaction `ERR_TRANSACTION_NOT_FOUND`" and "All not-found
        rejections carry HTTP 404."
        PRD §2.9 orders "4. Path existence" before "6. Target lifecycle and
        actionability", so the ghost id yields 404, not a state error.

        Design: Corner/validations/existence_checked_before_state_on_reverse
        """
        create_rep(full_name="Rep V2", crd_number="CRD-V02")
        resp = api_client.reverse_transaction(
            NON_EXISTENT_UUID, {"reason": "ghost"}, TEST_USERS["ops_headers"]
        )
        error = validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_FOUND)
        assert error["error_id"] == "ERR_TRANSACTION_NOT_FOUND"
        assert resp.status_code == 404


class TestAccountGetNonexistentReturnsNotFound:
    def test_get_missing_account_returns_404(self, api):
        """PRD §2.8: "a missing account `ERR_ACCOUNT_NOT_FOUND`" and "All not-found
        rejections carry HTTP 404."

        Design: Corner/entities/account_get_nonexistent_returns_not_found
        """
        create_rep(full_name="Rep E4", crd_number="CRD-ENT4")
        resp = api_client.get_account(NON_EXISTENT_UUID, TEST_USERS["officer_headers"])
        error = validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
        assert error["error_id"] == "ERR_ACCOUNT_NOT_FOUND"
        assert resp.status_code == 404


class TestBeneficialOwnerCreationNonexistentCertificationNotFound:
    def test_add_owner_under_missing_certification_returns_404(self, api):
        """PRD §2.8: "Paths that carry multiple identifiers are validated left to
        right: the first path identifier that does not correspond to an existing
        resource determines the rejection, before any business rule is evaluated" —
        "a missing certification `ERR_CERTIFICATION_NOT_FOUND`", HTTP 404.

        Design: Corner/entities/beneficial_owner_creation_nonexistent_certification_not_found
        """
        rep = create_rep(full_name="Rep E7", crd_number="CRD-ENT7")
        resp = api_client.add_owner(
            NON_EXISTENT_UUID,
            {"full_name": "Orphan", "ownership_pct": 30.00},
            make_rep_headers(rep["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_FOUND)
        assert error["error_id"] == "ERR_CERTIFICATION_NOT_FOUND"
        assert resp.status_code == 404


class TestClockDefaultStartupValue:
    def test_startup_clock_dates_received_at_and_deadline(self, api):
        """PRD §2.5: "Before any administrative call sets it, the clock reads exactly
        `2026-05-01T00:00:00Z`; once set, it holds that value until the next set, and
        it never falls back to wall-clock time."
        PRD §3.7: "Registration stamps `received_at` from the logical clock, computes
        `response_deadline` as the received date plus fourteen calendar days, and
        places the request in `RECEIVED`."
        With the clock never set, a request stamps received_at 2026-05-01 and deadline
        2026-05-15.

        Design: Corner/cross_cutting_layers/clock_default_startup_value
        """
        resp = api_client.create_fincen_request(
            {
                "request_reference": "FIN-X7",
                "subjects": [{"name": "Nobody", "subject_type": "INDIVIDUAL"}],
            },
            TEST_USERS["officer_headers"],
        )
        request = validate_success(resp, expected_status=201)
        assert request["response_deadline"] == "2026-05-15", (
            f"received 2026-05-01 + 14 days = 2026-05-15, got {request['response_deadline']}"
        )
        assert request["received_at"].startswith("2026-05-01"), (
            f"received_at must reflect the startup clock, got {request['received_at']}"
        )


class TestSweepOutputCountsLiteral:
    def test_sweep_reports_exact_per_family_counts(self, api):
        """PRD §2.5: "The sweep reports how many entities each family touched, via
        `documents_expired`, `edd_reviews_flagged`, `sar_reviews_due`,
        `requests_314a_overdue`, `holds_released`, and `findings_aged`."
        PRD §3.9: "thirty days for `CRITICAL`" — a CRITICAL finding created 2026-05-01
        has deadline 2026-05-31 and is aged by a 2026-06-01 sweep; "with `CRITICAL`
        unchanged" its severity stays CRITICAL.
        One expiring VERIFIED document + one aging CRITICAL finding swept at
        2026-06-01 yield exactly {1, 0, 0, 0, 0, 1}.

        Design: Corner/cross_cutting_layers/sweep_output_counts_literal
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep X6", crd_number="CRD-X06")
        customer = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="X6", tax_id="TIN-X06",
            country_risk_tier="LOW",
        )
        submit_and_verify_document(
            customer["id"], rep, document_number="P-X06", expiry_date="2026-05-02"
        )
        engagement = create_engagement(
            scope_unit="AML_PROGRAM", start_date="2026-04-01", end_date="2026-06-30"
        )
        begin_fieldwork(engagement["id"])
        finding = create_finding(
            engagement["id"], severity="CRITICAL", description="no SAR governance"
        )
        assert finding["remediation_deadline"] == "2026-05-31"

        set_clock("2026-06-01T00:00:00Z")
        sweep = run_daily_sweep()
        expected = {
            "documents_expired": 1,
            "edd_reviews_flagged": 0,
            "sar_reviews_due": 0,
            "requests_314a_overdue": 0,
            "holds_released": 0,
            "findings_aged": 1,
        }
        for key, want in expected.items():
            assert sweep.get(key) == want, (
                f"sweep counter {key} must be {want}, got {sweep.get(key)}"
            )

        resp = api_client.get_finding(finding["id"], TEST_USERS["auditor_headers"])
        aged = validate_success(resp)
        assert aged["is_overdue"] is True
        assert aged["severity"] == "CRITICAL", "escalation is capped at CRITICAL"


class TestVersionIncrementsOnEveryMutation:
    def test_account_version_increments_once_per_mutation(self, api):
        """PRD §2.4: "`version` (integer): starts at its initial value on creation and
        increments by one on every mutation of the resource, including system-driven
        transitions and cascade-driven updates."
        Creation -> approve -> transaction post each add exactly one.

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        ctx = setup_pending_account()
        account = ctx["account"]
        approved = approve_account(account["id"])
        assert approved["version"] == account["version"] + 1, (
            f"approve must add exactly 1 to version {account['version']}, "
            f"got {approved['version']}"
        )
        post_wire(account["id"], ctx["rep"], 10.00)
        after = get_account(account["id"])
        assert after["version"] == approved["version"] + 1, (
            f"posting must add exactly 1 to version {approved['version']}, "
            f"got {after['version']}"
        )


class TestImmediateVisibilityAfterApprove:
    def test_approve_response_and_followup_read_agree(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §3.3: "Successful approval moves `PENDING_APPROVAL` → `OPEN`".
        PRD §2.11: "Derived dimensions such as the account's AML posture are recomputed
        after every trigger and stored on the account row, so readers always see the
        current composite state rather than a snapshot."
        The approve response carries OPEN, and an immediate GET reflects the same state.

        Design: Corner/consistency_model/immediate_visibility_after_approve
        """
        ctx = setup_pending_account()
        account = ctx["account"]
        resp = api_client.approve_account(account["id"], TEST_USERS["officer_headers"])
        approved = validate_success(resp)
        assert approved["lifecycle_status"] == "OPEN", (
            "the mutation must be visible in its own response"
        )
        assert approved["version"] == account["version"] + 1

        reread = get_account(account["id"])
        assert reread["lifecycle_status"] == "OPEN", (
            "the mutation must be immediately consistent on read"
        )
