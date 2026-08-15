"""Validation priority, ownership, RBAC denials, and customer list scoping."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    accept_estimate,
    build_user_headers,
    create_accepted_job,
    create_customer,
    create_estimate,
    create_stock,
    get_success_data,
    make_customer_headers,
    minimal_signature,
    quote_estimate,
    validate_error,
    validate_paginated,
    validate_success,
)

_PM = TEST_USERS["plant_manager_headers"]
_EST = TEST_USERS["estimator_headers"]
_PRE = TEST_USERS["prepress_headers"]
_SCH = TEST_USERS["scheduler_headers"]
_PUR = TEST_USERS["purchasing_headers"]
_MAIL = TEST_USERS["mail_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)." Priority 1 beats existence: even a nonexistent job id
        yields 401, not 404.

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.get_job(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_unrecognized_role_rejected(self, api):
        """PRD §2.1: "carrying a role the system does not recognize, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.get_job(NON_EXISTENT_UUID,
                           headers=build_user_headers("u-1", "Wizard"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestValidationPriority:
    def test_existence_before_ownership_on_missing_job(self, api):
        """PRD §2.7: "Only after identity is established does the server check
        existence: path parameters and body foreign-key references must
        resolve to existing resources... with the first unresolved reference
        producing `ERR_NOT_FOUND`." A Customer reading a nonexistent job gets
        404, never ERR_NOT_OWN_RESOURCE for a resource that does not exist.

        Design: Corner/validations/existence_before_ownership_on_missing_job
        """
        cust = create_customer(name="O Cust", credit_limit_cents=1000)
        resp = api.get_job(NON_EXISTENT_UUID, make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_role_check_before_not_found(self, api):
        """PRD §2.7: "Authentication of headers comes first
        (`ERR_UNAUTHENTICATED`), followed by role authorization
        (`ERR_FORBIDDEN_ROLE`)... Only after identity is established does the
        server check existence." MailSpecialist is not authorized for
        record-delivery, so the call is 403 even for a nonexistent job.

        Design: Corner/validations/role_check_before_not_found
        """
        resp = api.record_delivery(NON_EXISTENT_UUID, {"delivered_quantity": 5}, _MAIL)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestOwnership:
    def test_wrong_customer_ownership_returns_forbidden(self, api):
        """PRD §2.1: "When a `Customer` attempts to read or act on a resource
        whose `customer_id` does not match their `X-User-ID`, the request is
        rejected with `ERR_NOT_OWN_RESOURCE` (HTTP 403)."

        Design: Corner/validations/wrong_customer_ownership_returns_forbidden
        """
        ca = create_customer(name="A")
        cb = create_customer(name="B")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        _est, job = create_accepted_job(ca["id"], minimal_signature(stock["id"],
                                        make_ready_cents=1000, rate_per_thousand_cents=1000),
                                        quantity_ordered=100, job_name="AJ")
        r_b = api.get_job(job["id"], make_customer_headers(cb["id"]))
        validate_error(r_b, ApiErrorId.ERR_NOT_OWN_RESOURCE)
        r_a = api.get_job(job["id"], make_customer_headers(ca["id"]))
        data = validate_success(r_a, 200)
        assert data["id"] == job["id"]


class TestRBAC:
    def test_rbac_estimator_cannot_create_customer(self, api):
        """PRD §4: POST /customers is PlantManager-only; §2.1: "A request
        whose role is recognized but not authorized for the targeted endpoint
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_estimator_cannot_create_customer
        """
        resp = api.create_customer({"name": "Nope", "credit_limit_cents": 1}, _EST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_customer_cannot_upload_proof(self, api):
        """PRD §2.7: "Authentication of headers comes first
        (`ERR_UNAUTHENTICATED`), followed by role authorization
        (`ERR_FORBIDDEN_ROLE`)" — POST /proofs is PrepressOperator-only
        (PRD §4), so the role check fires before body FK resolution.

        Design: Corner/rbac/rbac_customer_cannot_upload_proof
        """
        cust = create_customer(name="C", credit_limit_cents=1000)
        resp = api.create_proof(
            {"job_id": NON_EXISTENT_UUID, "file_uri": "s3://x.pdf"},
            make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_prepress_cannot_create_press_run(self, api):
        """PRD §2.7: "followed by role authorization
        (`ERR_FORBIDDEN_ROLE`)... Optimistic concurrency
        (`ERR_STALE_VERSION`) is checked next, ahead of any state-machine
        evaluation." POST /press-runs is PressScheduler-only (PRD §4), so the
        role check fires before OCC.

        Design: Corner/rbac/rbac_prepress_cannot_create_press_run
        """
        from test_helpers import create_press
        press = create_press(name="W1")
        resp = api.create_press_run(
            {"press_id": press["id"], "job_id": NON_EXISTENT_UUID, "run_quantity": 1,
             "scheduled_start": "2026-08-10T08:00:00Z",
             "expected_press_version": press["version"]}, _PRE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_scheduler_cannot_generate_invoice(self, api):
        """PRD §2.1: "A request whose role is recognized but not authorized
        for the targeted endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." PRD §4 restricts POST /invoices to PlantManager.

        Design: Corner/rbac/rbac_scheduler_cannot_generate_invoice
        """
        resp = api.create_invoice({"job_id": NON_EXISTENT_UUID}, _SCH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_mail_specialist_cannot_receive_paper(self, api):
        """PRD §2.1: "A request whose role is recognized but not authorized
        for the targeted endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." PRD §4 restricts PO receipts to PurchasingManager.

        Design: Corner/rbac/rbac_mail_specialist_cannot_receive_paper
        """
        resp = api.receive_paper_purchase_order(
            NON_EXISTENT_UUID, {"sheets_received": 1}, _MAIL)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_purchasing_cannot_approve_proof(self, api):
        """PRD §2.1: "A request whose role is recognized but not authorized
        for the targeted endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." PRD §4 restricts proof approval to Customer.

        Design: Corner/rbac/rbac_purchasing_cannot_approve_proof
        """
        resp = api.approve_proof(NON_EXISTENT_UUID, _PUR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestCustomerListScoping:
    def test_rbac_customer_list_scoping(self, api):
        """PRD §3.2: "a `Customer` reading the list sees only their own
        estimates."

        Design: Corner/rbac/rbac_customer_list_scoping
        """
        ca = create_customer(name="A", credit_limit_cents=1000)
        cb = create_customer(name="B", credit_limit_cents=1000)
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        create_estimate(ca["id"], minimal_signature(stock["id"], make_ready_cents=1000,
                                                    rate_per_thousand_cents=1000),
                        quantity_ordered=100, job_name="A")
        eb = create_estimate(cb["id"], minimal_signature(stock["id"], make_ready_cents=1000,
                                                         rate_per_thousand_cents=1000),
                             quantity_ordered=100, job_name="B")
        rows, meta = validate_paginated(
            api.list_estimates(make_customer_headers(cb["id"])))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == eb["id"]
