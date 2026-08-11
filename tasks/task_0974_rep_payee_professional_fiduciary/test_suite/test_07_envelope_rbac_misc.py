"""Cross-cutting: auth envelope, error envelope, RBAC denials, not-found
variants, pagination, entitlement overlap, account close gates, unique-field
constraints, list filtering."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, build_user_headers,
    ApiErrorId, make_admin_headers, make_financial_officer_headers,
    make_case_manager_headers, make_conservator_headers, make_auditor_headers,
    create_client, create_active_client, create_client_with_verified_entitlement,
    create_account, create_active_bond, create_and_post_deposit,
    create_budget_plan_for_client, create_approved_budget_plan,
    create_disbursement, create_approved_disbursement,
    create_released_disbursement, create_conservator, set_clock,
    create_client_payload, create_entitlement_payload,
    create_trust_account_payload, create_deposit_payload,
    create_audit_case_payload, create_submitted_report,
    setup_funded_release_ready,
)
from test_helpers.api_client import api_client as api

ADMIN = make_admin_headers()
FO = make_financial_officer_headers()
CM = make_case_manager_headers()
AUD = make_auditor_headers()

UUID_1 = "11111111-1111-4111-8111-111111111111"
UUID_2 = "22222222-2222-4222-8222-222222222222"
UUID_3 = "33333333-3333-4333-8333-333333333333"
UUID_4 = "44444444-4444-4444-8444-444444444444"
UUID_5 = "55555555-5555-4555-8555-555555555555"
UUID_6 = "66666666-6666-4666-8666-666666666666"


class TestAuthEnvelope:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, naming the
        operator's role. A request missing either header, or carrying a role
        that is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_clients(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_role_denial_precedes_existence_forbidden(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline,
        and earlier stages mask later ones. Stage one is authentication (§2.1):
        missing or invalid headers produce `ERR_UNAUTHENTICATED`. Stage two is
        role authorization: an authenticated role outside the endpoint's
        permitted set produces `ERR_FORBIDDEN`."

        Design: Corner/validations/role_denial_precedes_existence_forbidden
        """
        resp = api.activate_client(UUID_1, CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_error_envelope_shape_on_failure(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_envelope_shape_on_failure
        """
        resp = api.create_client({"ssn_last4": "4455"}, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert isinstance(err.get("message"), str) and len(err["message"]) > 0
        body = resp.json()
        assert body["response_type"] == "error"


class TestNotFoundVariants:
    def test_resource_not_found_variants_primary(self, api):
        """PRD §2.9: "Stage four is existence: path identifiers are resolved
        first, from left to right, then body foreign-key references in their
        declared field order; an unknown client reference produces
        `ERR_CLIENT_NOT_FOUND`, and each other resource family reports its own
        identifier — `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`,
        `ERR_DEPOSIT_NOT_FOUND`, `ERR_COURT_ORDER_NOT_FOUND`,
        `ERR_BOND_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        `ERR_SPEND_DOWN_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, and
        `ERR_CONSERVATOR_NOT_FOUND` — all at HTTP 404."

        Design: Corner/entities/resource_not_found_variants_primary
        """
        validate_error(api.get_client(UUID_1, ADMIN), ApiErrorId.ERR_CLIENT_NOT_FOUND)
        validate_error(api.get_trust_account(UUID_2, ADMIN), ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
        validate_error(api.get_budget_plan(UUID_3, ADMIN), ApiErrorId.ERR_PLAN_NOT_FOUND)
        validate_error(api.get_disbursement(UUID_4, ADMIN), ApiErrorId.ERR_DISBURSEMENT_NOT_FOUND)
        validate_error(api.get_deposit(UUID_5, ADMIN), ApiErrorId.ERR_DEPOSIT_NOT_FOUND)
        validate_error(api.get_entitlement(UUID_6, ADMIN), ApiErrorId.ERR_ENTITLEMENT_NOT_FOUND)

    def test_resource_not_found_variants_secondary(self, api):
        """PRD §2.9: "Stage four is existence: path identifiers are resolved
        first, from left to right, then body foreign-key references in their
        declared field order; an unknown client reference produces
        `ERR_CLIENT_NOT_FOUND`, and each other resource family reports its own
        identifier — `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`,
        `ERR_DEPOSIT_NOT_FOUND`, `ERR_COURT_ORDER_NOT_FOUND`,
        `ERR_BOND_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        `ERR_SPEND_DOWN_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, and
        `ERR_CONSERVATOR_NOT_FOUND` — all at HTTP 404."

        Design: Corner/entities/resource_not_found_variants_secondary
        """
        validate_error(api.get_court_order(UUID_1, ADMIN), ApiErrorId.ERR_COURT_ORDER_NOT_FOUND)
        validate_error(api.get_surety_bond(UUID_2, ADMIN), ApiErrorId.ERR_BOND_NOT_FOUND)
        validate_error(api.get_accounting_report(UUID_3, ADMIN), ApiErrorId.ERR_REPORT_NOT_FOUND)
        validate_error(api.get_spend_down_plan(UUID_4, ADMIN), ApiErrorId.ERR_SPEND_DOWN_NOT_FOUND)
        validate_error(api.get_audit_case(UUID_5, ADMIN), ApiErrorId.ERR_AUDIT_NOT_FOUND)
        validate_error(api.get_conservator(UUID_6, ADMIN), ApiErrorId.ERR_CONSERVATOR_NOT_FOUND)


class TestResponseEnvelope:
    def test_response_envelope_success_and_pagination_fields(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
        The `limit` defaults to 10, with a minimum of 1 and a maximum of 100;
        the `offset` defaults to 0. List responses are sorted by `created_at`
        ascending, and the `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/response_envelope_success_and_pagination_fields
        """
        client = create_client(legal_name="Env Ella")
        single = api.get_client(client["id"], ADMIN).json()
        assert single["response_type"] == "object"
        assert single["meta"]["api_request_id"]
        assert single["meta"]["api_request_timestamp"]
        assert single["data"]["legal_name"] == "Env Ella"
        rows, meta = validate_paginated(api.list_clients(ADMIN))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert "total_count" in meta and "has_more" in meta

    def test_clients_list_pagination_limit_offset(self, api):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query
        parameters. The `limit` defaults to 10, with a minimum of 1 and a
        maximum of 100; the `offset` defaults to 0. List responses are sorted
        by `created_at` ascending, and the `meta` block of a list response
        carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/clients_list_pagination_limit_offset
        """
        c1 = create_client(legal_name="Page One")
        c2 = create_client(legal_name="Page Two")
        rows1, meta1 = validate_paginated(api.list_clients(ADMIN, params={"limit": 1, "offset": 0}))
        assert len(rows1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        rows2, meta2 = validate_paginated(api.list_clients(ADMIN, params={"limit": 1, "offset": 1}))
        assert len(rows2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert {rows1[0]["id"], rows2[0]["id"]} == {c1["id"], c2["id"]}


class TestRbac:
    def test_rbac_case_manager_cannot_release_disbursement(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_case_manager_cannot_release_disbursement
        """
        set_clock("2026-06-10T00:00:00Z")
        env = setup_funded_release_ready(deposit_amount=50000, disbursement_amount=10000)
        d = env["disbursement"]
        resp = api.release_disbursement(d["id"], CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_disbursement(d["id"], FO))
        assert after["status"] == "APPROVED"

    def test_rbac_financial_officer_cannot_create_client(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_financial_officer_cannot_create_client
        """
        resp = api.create_client(
            create_client_payload(legal_name="Rbac FO"), FO
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_rbac_conservator_cannot_approve_disbursement(self, api):
        """PRD §2.1: "`ConservatorOfficer` — a court-appointed conservator
        acting on coordinated clients; the only operation exclusive to this
        role is disbursement co-approval."
        PRD §2.1: "A request whose role is authenticated but not listed among
        the roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_conservator_cannot_approve_disbursement
        """
        client, _ = create_active_client()
        acct = create_account(client["id"])
        cons = create_conservator(client["id"], authority_scope="EXCLUSIVE")
        plan = create_budget_plan_for_client(client["id"])
        d = create_disbursement(client["id"], acct["id"], plan["id"],
                                amount_cents=5000, payee_name="Rbac C Payee")
        resp = api.approve_disbursement(d["id"], make_conservator_headers(cons["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_rbac_auditor_cannot_post_deposit(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_auditor_cannot_post_deposit
        """
        client, _ = create_active_client()
        acct = create_account(client["id"])
        dep = get_success_data(api.create_deposit(
            create_deposit_payload(account_id=acct["id"], amount_cents=10000), FO
        ))
        resp = api.post_deposit(dep["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_deposit(dep["id"], FO))
        assert after["status"] == "RECEIVED"

    def test_rbac_admin_cannot_issue_findings(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_admin_cannot_issue_findings
        """
        client = create_client()
        case = get_success_data(api.create_audit_case(
            create_audit_case_payload(client_id=client["id"]), AUD
        ))
        resp = api.issue_findings(
            case["id"], {"misuse_amount_cents": 1000, "findings_count": 1}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_audit_case(case["id"], AUD))
        assert after["status"] == "OPENED"

    def test_rbac_case_manager_cannot_accept_report(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.8: "Adjudication belongs to the `ComplianceAuditor`: acceptance
        moves a submitted report `SUBMITTED` → `ACCEPTED`, and rejection moves
        it `SUBMITTED` → `REJECTED`."

        Design: Corner/rbac/rbac_case_manager_cannot_accept_report
        """
        set_clock("2026-06-10T00:00:00Z")
        client, _ = create_active_client()
        report = create_submitted_report(client["id"])
        resp = api.accept_accounting_report(report["id"], CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_accounting_report(report["id"], AUD))
        assert after["status"] == "SUBMITTED"


class TestEntitlementWindows:
    def test_entitlement_half_open_window_adjacency(self, api):
        """PRD §3.1: "Among a client's non-`TERMINATED` entitlements sharing
        the same `claim_type`, these half-open windows must not overlap —
        adjacency, where one window's end equals the next window's start, is
        permitted — and an overlapping registration is rejected with
        `ERR_ENTITLEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/entitlement_half_open_window_adjacency
        """
        client = create_client()
        e1 = get_success_data(api.create_entitlement(
            create_entitlement_payload(client_id=client["id"],
                                       effective_end_date="2026-06-01"), ADMIN
        ))
        # Adjacency: start == prior end is allowed under half-open windows.
        e2 = get_success_data(api.create_entitlement(
            create_entitlement_payload(client_id=client["id"],
                                       monthly_benefit_cents=85000,
                                       effective_start_date="2026-06-01"), ADMIN
        ))
        assert e2["status"] == "PENDING_VERIFICATION"
        # One day earlier collides with [2026-01-01, 2026-06-01).
        resp = api.create_entitlement(
            create_entitlement_payload(client_id=client["id"],
                                       monthly_benefit_cents=81000,
                                       effective_start_date="2026-05-31"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_OVERLAP)

    def test_entitlement_overlap_interior_start_rejected(self, api):
        """PRD §3.1: "Among a client's non-`TERMINATED` entitlements sharing
        the same `claim_type`, these half-open windows must not overlap —
        adjacency, where one window's end equals the next window's start, is
        permitted — and an overlapping registration is rejected with
        `ERR_ENTITLEMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/entitlement_half_open_window_adjacency
        """
        client = create_client()
        get_success_data(api.create_entitlement(
            create_entitlement_payload(client_id=client["id"],
                                       effective_end_date="2026-06-01"), ADMIN
        ))
        # Interior start (2026-03-01) intersects [2026-01-01, 2026-06-01).
        resp = api.create_entitlement(
            create_entitlement_payload(client_id=client["id"],
                                       monthly_benefit_cents=82000,
                                       effective_start_date="2026-03-01"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_OVERLAP)

    def test_double_verify_entitlement_returns_invalid_state(self, api):
        """PRD §3.1: "Verification moves the entitlement `PENDING_VERIFICATION`
        → `VERIFIED`; an administrator may also end a verified award, moving it
        `VERIFIED` → `TERMINATED`."
        PRD §2.9: "Stage five checks that the entity's state machine permits
        the requested transition from its current state (`ERR_INVALID_STATE`,
        HTTP 409)."

        Design: Corner/state_machines/double_verify_entitlement_returns_invalid_state
        """
        client = create_client()
        ent = get_success_data(api.create_entitlement(
            create_entitlement_payload(client_id=client["id"], claim_type="SSDI",
                                       monthly_benefit_cents=90000), ADMIN
        ))
        first = get_success_data(api.verify_entitlement(ent["id"], ADMIN))
        resp = api.verify_entitlement(ent["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_entitlement(ent["id"], ADMIN))
        assert after["verified_at"] == first["verified_at"]


class TestAccountCloseGates:
    def test_account_close_dual_failure_priority(self, api):
        """PRD §3.2: "Closing an account moves it `OPEN` → `CLOSED` and carries
        two gates evaluated in order: the derived `balance_cents` must be
        exactly zero, failing with `ERR_ACCOUNT_NOT_ZERO`, and the account must
        have no disbursements in `REQUESTED`, `PENDING_CONSERVATOR`, or
        `APPROVED`, failing with `ERR_PENDING_DISBURSEMENTS`."

        Design: Corner/validations/account_close_dual_failure_priority
        """
        set_clock("2026-06-10T00:00:00Z")
        client, _ = create_active_client()
        a1 = create_account(client["id"])
        a2 = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(a1["id"], 5000, received_date="2026-06-05")
        plan = create_budget_plan_for_client(client["id"])
        create_disbursement(client["id"], a1["id"], plan["id"], amount_cents=1000,
                            payee_name="Pend One", scheduled_release_date="2026-06-15")
        create_disbursement(client["id"], a2["id"], plan["id"], amount_cents=1000,
                            payee_name="Pend Two", scheduled_release_date="2026-06-15")
        resp1 = api.close_trust_account(a1["id"], FO)
        validate_error(resp1, ApiErrorId.ERR_ACCOUNT_NOT_ZERO)
        resp2 = api.close_trust_account(a2["id"], FO)
        validate_error(resp2, ApiErrorId.ERR_PENDING_DISBURSEMENTS)


class TestUniqueFields:
    def test_duplicate_bank_account_ref_rejected(self, api):
        """PRD §3.2: "Each account records its owning `client_id`, an
        `account_type`, and an external `bank_account_ref` that must be unique
        across every trust account in the system — a duplicate reference is
        rejected with `ERR_DUPLICATE_UNIQUE_FIELD`."

        Design: Corner/validations/duplicate_bank_account_ref_rejected
        """
        c1 = create_client(legal_name="Dup One")
        c2 = create_client(legal_name="Dup Two")
        get_success_data(api.create_trust_account(
            create_trust_account_payload(client_id=c1["id"],
                                         bank_account_ref="BA-DUP-001"), FO
        ))
        resp = api.create_trust_account(
            create_trust_account_payload(client_id=c2["id"],
                                         bank_account_ref="BA-DUP-001"), FO
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIQUE_FIELD)


class TestCrossEntityValidation:
    def test_budget_plan_mismatch_at_create(self, api):
        """PRD §3.5: "Creation enforces its checks in a fixed order: the
        client-activity gate first (a `TERMINATED` client fails with
        `ERR_CLIENT_NOT_ACTIVE`), then the restricted-account court-order
        requirement, then the dedicated-account category rule (a `DEDICATED`
        source account may fund only `MEDICAL` and `EDUCATION` categories,
        otherwise `ERR_DEDICATED_ACCOUNT_RESTRICTED`), and finally foreign-key
        coherence — the account, the budget plan, the court order when present,
        and the spend-down plan when present must all belong to the named
        client, or creation fails with `ERR_BUDGET_PLAN_MISMATCH`."

        Design: Corner/validations/budget_plan_mismatch_at_create
        """
        client_a, _ = create_active_client(legal_name="Ref A")
        acct_a = create_account(client_a["id"])
        client_b, _ = create_active_client(legal_name="Ref B")
        plan_b = create_budget_plan_for_client(client_b["id"])
        resp = api.create_disbursement(
            {
                "client_id": client_a["id"], "account_id": acct_a["id"],
                "budget_plan_id": plan_b["id"], "payee_name": "Ref Payee",
                "category": "HOUSING", "amount_cents": 5000,
                "scheduled_release_date": "2026-06-10",
            },
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_BUDGET_PLAN_MISMATCH)


class TestAccountTypeValidation:
    def test_account_create_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.9: "Stage three is request-body shape: missing required
        fields, invalid enum values, violated integer constraints (amounts that
        must be positive, counts that must be non-negative), an `ssn_last4`
        that is not exactly four digits, budget line percents that do not sum
        to exactly 100 or repeat a category, and malformed date strings all
        produce `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/account_create_invalid_enum_returns_invalid_request
        """
        client = create_client()
        resp = api.create_trust_account(
            create_trust_account_payload(client_id=client["id"],
                                         account_type="SAVINGS_ACCT"), FO
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestListFiltering:
    def test_disbursements_list_filter_by_status(self, api):
        """PRD §2.3: "Beyond paging, each list endpoint accepts optional
        equality filters drawn from the resource's own fields — the full
        vocabulary of filter names across the API is `status`, `client_id`,
        `medicaid_enrolled`, `claim_type`, `account_type`, `entry_type`,
        `period_month`, `superseded_by_plan_id`, `category`, `source`,
        `entitlement_id`, `order_type`, `executed_disbursement_id`,
        `report_type`, `target_month`, `authority`, `authority_scope`,
        `budget_plan_id`, `court_order_id`, `spend_down_plan_id`,
        `account_id`, and `co_approved_by_conservator_id`, each applied to the
        collection for which §4 lists it."

        Design: Corner/endpoints/disbursements_list_filter_by_status
        """
        client, _ = create_active_client()
        acct = create_account(client["id"])
        plan = create_budget_plan_for_client(client["id"])
        d1 = create_disbursement(client["id"], acct["id"], plan["id"],
                                 amount_cents=5000, payee_name="Keep")
        d2 = create_disbursement(client["id"], acct["id"], plan["id"],
                                 amount_cents=6000, payee_name="Drop")
        get_success_data(api.reject_disbursement(d2["id"], FO))
        rows_rej, meta_rej = validate_paginated(
            api.list_disbursements(CM, params={"client_id": client["id"], "status": "REJECTED"})
        )
        assert meta_rej["total_count"] == 1
        assert rows_rej[0]["id"] == d2["id"]
        assert rows_rej[0]["status"] == "REJECTED"
        rows_req, meta_req = validate_paginated(
            api.list_disbursements(CM, params={"client_id": client["id"], "status": "REQUESTED"})
        )
        assert meta_req["total_count"] == 1
        assert rows_req[0]["id"] == d1["id"]
        assert rows_req[0]["status"] == "REQUESTED"
