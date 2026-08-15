"""Access control: the authentication context gate, role exclusivity,
organization ownership, refund segregation of duties, and the state-before-
fiscal gate ordering on permit confirmation."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    cancel_permit_as_owner,
    close_allocation_window,
    create_facility_payload,
    create_organization,
    create_payment_payload,
    create_refund_payload,
    get_application,
    get_invoice,
    get_permit,
    issue_invoice,
    make_athletics_admin_headers,
    make_finance_clerk_headers,
    make_org_coordinator_headers,
    pay_invoice,
    setup_awarded_permit,
    setup_open_season,
    submit_application,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["athletics_admin_headers"]
SUPERVISOR = TEST_USERS["field_supervisor_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]


class TestAuthenticationContext:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which that user acts. A request missing either header, or carrying an empty
        value for one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        res = api.get_organization(NON_EXISTENT_UUID, headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleExclusivity:
    def test_field_supervisor_cannot_run_allocation(self, api):
        """PRD §2.1: "A caller whose role is not permitted to perform an operation is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the endpoint-by-endpoint
        role assignments appear in §4."
        PRD §4: run-allocation is listed for AthleticsAdmin only.

        Design: Corner/rbac/field_supervisor_cannot_run_allocation
        """
        ctx = setup_open_season(publish_schedule=False)
        submit_application(ctx["window"]["id"], ctx["facility"]["id"],
                           ctx["organization"]["id"])
        close_allocation_window(ctx["window"]["id"])
        res = api.run_allocation(ctx["window"]["id"], SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        window = validate_success(
            api.get_allocation_window(ctx["window"]["id"], ADMIN), 200)
        assert window["status"] == "CLOSED", "rejected run must not advance the window"

    def test_org_coordinator_cannot_create_facility(self, api):
        """PRD §2.1: "A caller whose role is not permitted to perform an operation is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the endpoint-by-endpoint
        role assignments appear in §4."
        PRD §4: POST /facilities is listed for AthleticsAdmin only.

        Design: Corner/rbac/org_coordinator_cannot_create_facility
        """
        org = create_organization()
        res = api.create_facility(
            create_facility_payload(name="Rogue Field", facility_class="DIAMOND",
                                    has_lights=False, capacity=80,
                                    weekly_prime_hour_cap=10,
                                    nightly_light_block_cap=8),
            make_org_coordinator_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_athletics_admin_cannot_record_payments(self, api):
        """PRD §2.1: "A caller whose role is not permitted to perform an operation is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the endpoint-by-endpoint
        role assignments appear in §4."
        PRD §4: POST /invoices/{id}/payments is listed for FinanceClerk only.

        Design: Corner/rbac/athletics_admin_cannot_record_payments
        """
        ctx = setup_awarded_permit()
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        res = api.record_payment(invoice_id, create_payment_payload(4000), ADMIN)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_finance_clerk_cannot_create_closure(self, api):
        """PRD §2.1: "A caller whose role is not permitted to perform an operation is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the endpoint-by-endpoint
        role assignments appear in §4."
        PRD §4: POST /field-closures is listed for FieldSupervisor only.

        Design: Corner/rbac/finance_clerk_cannot_create_closure
        """
        ctx = setup_open_season(publish_schedule=False)
        res = api.create_field_closure(
            {"facility_id": ctx["facility"]["id"], "closure_date": "2026-08-10",
             "reason": "RAIN"},
            CLERK)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOrgOwnership:
    def test_cross_org_withdraw_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `OrgCoordinator`, `X-User-ID` is the `id`
        of the acting Organization; ownership checks on any resource that references
        an Organization compare the resource's `organization_id` field to `X-User-ID`,
        and a mismatch is rejected with `ERR_FORBIDDEN_ORG_OWNERSHIP` (HTTP 403)."

        Org B's coordinator cannot withdraw org A's application even though the role
        is correct for the endpoint.

        Design: Corner/validations/cross_org_withdraw_forbidden
        """
        ctx = setup_open_season(publish_schedule=False)
        org_a = ctx["organization"]
        org_b = create_organization(name="Beta Youth", prior_seasons_active=0)
        application = submit_application(
            ctx["window"]["id"], ctx["facility"]["id"], org_a["id"])

        res = api.withdraw_application(application["id"],
                                       make_org_coordinator_headers(org_b["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ORG_OWNERSHIP)
        assert get_application(application["id"])["status"] == "SUBMITTED"


class TestRefundSegregationOfDuties:
    def test_refund_approval_same_operator_rejected(self, api):
        """PRD §3.8: "Approval requires the payment to still be `PENDING_APPROVAL`,
        else `ERR_INVALID_PAYMENT_STATE`, and segregation of duties applies: an
        approver whose `X-User-ID` equals the row's `initiated_by` is rejected with
        `ERR_SEGREGATION_OF_DUTIES`. Approval stamps `approved_by`, adds the amount to
        the invoice's `refunded_cents`, recomputes `balance_due_cents`, and — when
        cleared refunds fully cover the net paid amount with the invoice total at 0 —
        settles the invoice to `REFUNDED` from either `PAID` or `PARTIALLY_PAID`."
        PRD §2.1: "When `X-User-Role` is `FinanceClerk`, `X-User-ID` is again opaque;
        the server records it as `initiated_by` on every payment or refund row the
        clerk creates, but performs no identity comparison against it."

        The refund of 10001 (> 10000) starts PENDING_APPROVAL with initiated_by
        clerk-7; an approver authenticating with that same operator id is rejected,
        while a different operator approves successfully.

        Design: Corner/rbac/refund_approval_same_operator_rejected
        """
        ctx = setup_awarded_permit(
            app_overrides={"start_minute": 600, "end_minute": 1080})  # 10:00-18:00
        assert ctx["permit"]["quoted_total_cents"] == 16000, \
            "480 minutes x 2000/hr, RESIDENT, no lights"
        invoice_id = ctx["invoice"]["id"]
        issue_invoice(invoice_id)
        clerk = make_finance_clerk_headers("clerk-7")
        pay_invoice(invoice_id, 16000, clerk_id="clerk-7")

        refund = validate_success(api.create_refund(
            invoice_id, create_refund_payload(10001, "Overcharge correction"),
            clerk), 201)
        assert refund["status"] == "PENDING_APPROVAL"
        assert refund["initiated_by"] == "clerk-7"

        res = api.approve_payment(refund["id"], make_athletics_admin_headers("clerk-7"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        still_pending = validate_success(api.get_payment(refund["id"], ADMIN), 200)
        assert still_pending["status"] == "PENDING_APPROVAL"

        approved = validate_success(api.approve_payment(
            refund["id"], make_athletics_admin_headers("admin-9")), 200)
        assert approved["status"] == "CLEARED"
        assert approved["approved_by"] == "admin-9"


class TestConfirmStateBeforeFiscal:
    """A CANCELLED permit whose invoice also has paid_cents < deposit_cents fails
    both the state gate and the fiscal gate; the state gate reports first."""

    def _setup_cancelled_unpaid_permit(self, api):
        """Awarded permit (invoice DRAFT, nothing paid), cancelled from RESERVED at
        the free 0% tier — leaving the permit CANCELLED with the deposit unpaid."""
        ctx = setup_awarded_permit()  # 2h no lights: quote 4000, deposit 4000
        org_id = ctx["organization"]["id"]
        cancelled = validate_success(cancel_permit_as_owner(
            ctx["permit"]["id"], org_id), 200)
        assert cancelled["status"] == "CANCELLED"
        ctx["permit"] = cancelled  # the post-cancel permit (version bumped by cancel)
        return ctx

    def test_confirm_cancelled_permit_state_beats_fiscal(self, api):
        """PRD §2.8: "Every request passes through a fixed validation pipeline, and
        the order is part of the contract: an earlier failure masks every later check,
        so the error a caller receives always comes from the earliest failing stage."
        PRD §3.6: "Confirmation turns a `RESERVED` permit `CONFIRMED`, and only the
        owning coordinator may do it — acting on another organization's permit fails
        with `ERR_FORBIDDEN_ORG_OWNERSHIP`, and attempting the transition from any
        other status fails with `ERR_INVALID_PERMIT_STATE`."

        The CANCELLED permit also owes its deposit (paid_cents 0 < deposit 4000):
        the response is the state error, not ERR_DEPOSIT_NOT_PAID.

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_permit_state_beats_fiscal
        """
        ctx = self._setup_cancelled_unpaid_permit(api)
        res = api.confirm_permit(ctx["permit"]["id"],
                                 make_org_coordinator_headers(ctx["organization"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_PERMIT_STATE)
        assert get_application(ctx["application"]["id"])["status"] == "AWARDED"

    def test_confirm_cancelled_permit_fires_no_side_effects(self, api):
        """PRD §2.8: "Every request passes through a fixed validation pipeline, and
        the order is part of the contract: an earlier failure masks every later check,
        so the error a caller receives always comes from the earliest failing stage."
        PRD §3.6: "Confirmation turns a `RESERVED` permit `CONFIRMED`, and only the
        owning coordinator may do it — acting on another organization's permit fails
        with `ERR_FORBIDDEN_ORG_OWNERSHIP`, and attempting the transition from any
        other status fails with `ERR_INVALID_PERMIT_STATE`."

        The rejected confirm leaves both aggregates untouched (permit CANCELLED,
        invoice unpaid), and a repeated attempt reports the same state error.

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_permit_state_beats_fiscal
        """
        ctx = self._setup_cancelled_unpaid_permit(api)
        org_id = ctx["organization"]["id"]
        invoice_before = get_invoice(ctx["invoice"]["id"])

        for _ in range(2):
            res = api.confirm_permit(ctx["permit"]["id"],
                                     make_org_coordinator_headers(org_id))
            validate_error(res, ApiErrorId.ERR_INVALID_PERMIT_STATE)

        permit = get_permit(ctx["permit"]["id"])
        assert permit["status"] == "CANCELLED"
        assert permit["version"] == ctx["permit"]["version"], \
            "rejected confirms must not bump the permit version"
        invoice_after = get_invoice(ctx["invoice"]["id"])
        assert invoice_after["paid_cents"] == invoice_before["paid_cents"] == 0
        assert invoice_after["status"] == invoice_before["status"]
