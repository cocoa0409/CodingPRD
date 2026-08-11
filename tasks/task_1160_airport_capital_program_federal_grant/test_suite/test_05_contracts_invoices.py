"""Contract award, invoice filing and verification, and project-drop guards (PRD §3.2, §3.5)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_invoice, assert_money,
    create_invoice_payload, create_contract_payload,
    create_sponsor, create_draft_program, add_project, submit_program, accept_program,
    apply_selection, create_application, certify_all_assurances, submit_application,
    offer_application, create_contractor, award_contract, file_invoice, verify_invoice,
    reject_invoice, request_closeout,
    setup_active_grant, setup_grant_with_contract, setup_grant_with_verified_invoice,
    make_contractor_headers, set_clock,
    TEST_USERS, ApiErrorId,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]


class TestInvoiceComputation:
    def test_invoice_retainage_computed_on_create(self):
        """PRD §3.5: "At filing, the retainage split is computed: `retainage_withheld` is the
        `gross_amount` multiplied by the contract's `retainage_pct`, rounded half-up to two
        decimal places, and `net_payable` is the exact remainder of `gross_amount` minus
        `retainage_withheld`."
        PRD §3.5: "The invoice starts in `SUBMITTED`, and its `drawdown_id` stays null until a
        reimbursement request includes it."

        Design: Corner/entities/invoice_retainage_computed_on_create
        """
        ctx = setup_grant_with_contract()
        invoice = validate_success(api_client.create_invoice(
            create_invoice_payload(ctx["contract"]["id"], invoice_number="INV-1",
                                   period="2026-05", gross_amount=100_000),
            make_contractor_headers(ctx["contractor"]["id"])), 201)
        assert_invoice(invoice)
        assert_money(invoice["retainage_withheld"], 10_000.00, "retainage_withheld")
        assert_money(invoice["net_payable"], 90_000.00, "net_payable")
        assert invoice["status"] == "SUBMITTED"
        assert invoice["drawdown_id"] is None

    def test_retainage_rounding_half_up(self):
        """PRD §2.6: "rounded to exactly 2 decimal places using the round-half-up method, and
        this applies equally to intermediate per-line amounts where a calculation pins
        line-level rounding".
        PRD §3.5: "`retainage_withheld` is the `gross_amount` multiplied by the contract's
        `retainage_pct`, rounded half-up to two decimal places".
        33,333.33 x 0.10 = 3,333.333 -> 3,333.33 (not 3,333.34); net 30,000.00.

        Design: Corner/calculations/retainage_rounding_half_up
        """
        ctx = setup_grant_with_contract()
        invoice = validate_success(api_client.create_invoice(
            create_invoice_payload(ctx["contract"]["id"], invoice_number="INV-R",
                                   period="2026-05", gross_amount=33_333.33),
            make_contractor_headers(ctx["contractor"]["id"])), 201)
        assert_money(invoice["retainage_withheld"], 3_333.33, "retainage_withheld")
        assert_money(invoice["net_payable"], 30_000.00, "net_payable")


class TestInvoiceVerification:
    def test_invoice_verify_after_reject_rejected(self):
        """PRD §3.5: "Sponsor staff may instead reject a submitted invoice, moving it to the
        terminal `REJECTED` status with no ledger effect."
        PRD §2.9: "state preconditions for the requested transition (generic failures carry
        `ERR_INVALID_STATE`, HTTP 409, while specific ones carry their dedicated codes)".

        Design: Corner/state_machines/invoice_verify_after_reject_rejected
        """
        ctx = setup_grant_with_contract()
        invoice = file_invoice(ctx["contract"]["id"], ctx["contractor"]["id"])
        rejected = reject_invoice(invoice["id"])
        assert rejected["status"] == "REJECTED"
        res = api_client.verify_invoice(invoice["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        contract = validate_success(
            api_client.get_contract(ctx["contract"]["id"], SPONSOR), 200)
        assert_money(contract["invoiced_total"], 0.00,
                     "invoiced_total (reject left no ledger trace)")

    def test_invoice_contract_value_equality_boundary(self):
        """PRD §3.5: "the contract's current `invoiced_total` plus the invoice's
        `gross_amount` must not exceed `awarded_value`, with exact equality allowed (otherwise
        `ERR_INVOICE_EXCEEDS_CONTRACT_VALUE`, HTTP 402)."

        Design: Corner/validations/invoice_contract_value_equality_boundary
        """
        ctx = setup_grant_with_contract(awarded_value=100_000, retainage_pct=0.00)
        con_id = ctx["contract"]["id"]
        ctr_id = ctx["contractor"]["id"]
        inv_a = verify_invoice(file_invoice(con_id, ctr_id, invoice_number="INV-A",
                                            gross_amount=60_000)["id"])
        assert inv_a["status"] == "VERIFIED"

        # 60,000 + 40,000.01 exceeds the 100,000 award.
        inv_b = file_invoice(con_id, ctr_id, invoice_number="INV-B", period="2026-06",
                             gross_amount=40_000.01)
        res = api_client.verify_invoice(inv_b["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_INVOICE_EXCEEDS_CONTRACT_VALUE,
                       expected_status=402)

        # 60,000 + 40,000.00 hits the award exactly: allowed.
        inv_c = file_invoice(con_id, ctr_id, invoice_number="INV-C", period="2026-06",
                             gross_amount=40_000.00)
        verified = validate_success(api_client.verify_invoice(inv_c["id"], SPONSOR), 200)
        assert verified["status"] == "VERIFIED"
        contract = validate_success(api_client.get_contract(con_id, SPONSOR), 200)
        assert_money(contract["invoiced_total"], 100_000.00, "invoiced_total")
        assert_money(contract["remaining_value"], 0.00, "remaining_value")

    def test_invoice_verify_requires_active_grant(self):
        """PRD §3.5: "the contract's grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`,
        HTTP 409)".

        Design: Corner/validations/invoice_verify_requires_active_grant
        """
        ctx = setup_grant_with_contract()
        request_closeout(ctx["grant"]["id"])  # grant now CLOSEOUT_REQUESTED
        invoice = file_invoice(ctx["contract"]["id"], ctx["contractor"]["id"],
                               invoice_number="INV-L", gross_amount=1_000)
        res = api_client.verify_invoice(invoice["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_GRANT_NOT_ACTIVE, expected_status=409)


class TestContractAwardGuards:
    def test_cross_sponsor_contract_rejected(self):
        """PRD §3.5: "the referenced contractor and project must belong to the same sponsor
        as the grant, and the project must be one of the source application's `project_ids` —
        a breach of either rule is `ERR_CROSS_SPONSOR_REFERENCE` (HTTP 422)".

        Design: Corner/validations/cross_sponsor_contract_rejected
        """
        ctx = setup_active_grant()
        sponsor_b = create_sponsor(name="Sponsor B")
        outsider = create_contractor(sponsor_b["id"], name="Outsider")
        res = api_client.create_contract(create_contract_payload(
            ctx["grant"]["id"], ctx["project"]["id"], outsider["id"],
            awarded_value=100_000), SPONSOR)
        validate_error(res, ApiErrorId.ERR_CROSS_SPONSOR_REFERENCE, expected_status=422)

    def test_suspended_contractor_blocks_award(self):
        """PRD §3.5: "suspension blocks new awards — awarding a contract to a `SUSPENDED`
        contractor is rejected with `ERR_CONTRACTOR_SUSPENDED` (HTTP 422)."

        Design: Corner/validations/suspended_contractor_blocks_award
        """
        ctx = setup_active_grant()
        contractor = create_contractor(ctx["sponsor"]["id"])
        validate_success(api_client.suspend_contractor(contractor["id"], SPONSOR), 200)
        res = api_client.create_contract(create_contract_payload(
            ctx["grant"]["id"], ctx["project"]["id"], contractor["id"],
            awarded_value=100_000), SPONSOR)
        validate_error(res, ApiErrorId.ERR_CONTRACTOR_SUSPENDED, expected_status=422)

    def test_contractor_ownership_enforced_on_invoice_create(self):
        """PRD §2.1: "a contractor may file an invoice or a DBE participation report only
        against a contract whose `contractor_id` equals the presented `X-User-ID`; acting on
        another contractor's contract is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/contractor_ownership_enforced_on_invoice_create
        """
        ctx = setup_grant_with_contract()
        other = create_contractor(ctx["sponsor"]["id"], name="BuildCo B", dbe_certified=True)
        res = api_client.create_invoice(
            create_invoice_payload(ctx["contract"]["id"], invoice_number="INV-X",
                                   gross_amount=1_000),
            make_contractor_headers(other["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        own = validate_success(api_client.create_invoice(
            create_invoice_payload(ctx["contract"]["id"], invoice_number="INV-Y",
                                   gross_amount=1_000),
            make_contractor_headers(ctx["contractor"]["id"])), 201)
        assert own["status"] == "SUBMITTED"


class TestProjectDropGuards:
    def test_project_drop_blocked_when_under_contract(self):
        """PRD §3.2: "first, if any Contract references the project, the drop is rejected
        with `ERR_PROJECT_UNDER_CONTRACT` (HTTP 422)".

        Design: Corner/validations/project_drop_blocked_when_under_contract
        """
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        p1 = add_project(program["id"], title="P1", project_type="PRESERVATION",
                         estimated_cost=600_000)
        p2 = add_project(program["id"], title="P2", project_type="CAPACITY",
                         estimated_cost=500_000, safety_score=10)
        submit_program(program["id"])
        accepted = accept_program(program["id"])
        apply_selection(program["id"], 2_000_000, accepted["version"])
        app = create_application(sponsor["id"], program["id"], [p1["id"], p2["id"]])
        certify_all_assurances(app["id"])
        submit_application(app["id"])
        offer_application(app["id"])
        app = validate_success(api_client.accept_offer(app["id"], SPONSOR), 200)
        grant_id = app["created_grant_id"]

        contractor = create_contractor(sponsor["id"])
        award_contract(grant_id, p1["id"], contractor["id"], awarded_value=100_000)

        res = api_client.drop_project(p1["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_PROJECT_UNDER_CONTRACT, expected_status=422)
        p1_after = validate_success(api_client.get_project(p1["id"], SPONSOR), 200)
        assert p1_after["status"] == "SELECTED"

    def test_project_drop_blocked_in_active_application(self):
        """PRD §3.2: "second, if any grant application in `UNDER_REVIEW` or `OFFERED`
        references the project, the drop is rejected with
        `ERR_PROJECT_IN_ACTIVE_APPLICATION` (HTTP 422)."
        PRD §3.2: "When the drop succeeds, every application in `DRAFT` or `RETURNED` that
        referenced the project has it removed from `project_ids` with `total_eligible_cost`
        recomputed".

        Design: Corner/validations/project_drop_blocked_in_active_application
        """
        set_clock("2026-05-01T00:00:00Z")
        sponsor = create_sponsor()
        program = create_draft_program(sponsor["id"])
        p1 = add_project(program["id"])
        submit_program(program["id"])
        accepted = accept_program(program["id"])
        apply_selection(program["id"], 2_000_000, accepted["version"])
        app = create_application(sponsor["id"], program["id"], [p1["id"]])
        certify_all_assurances(app["id"])
        submit_application(app["id"])  # UNDER_REVIEW

        res = api_client.drop_project(p1["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_PROJECT_IN_ACTIVE_APPLICATION,
                       expected_status=422)

        # Once the application is RETURNED, the drop succeeds and scrubs the reference.
        validate_success(api_client.return_application(app["id"], FAA), 200)
        dropped = validate_success(api_client.drop_project(p1["id"], SPONSOR), 200)
        assert dropped["status"] == "DROPPED"
        app_after = validate_success(api_client.get_application(app["id"], SPONSOR), 200)
        assert app_after["project_ids"] == []
        assert_money(app_after["total_eligible_cost"], 0.00, "total_eligible_cost")


class TestInvoiceListing:
    def test_invoice_filtered_list_by_contract_and_status(self):
        """PRD §4: "List invoices; optional filters `contract_id`, `drawdown_id`, `status`".
        PRD §2.3: "Paginated and non-paginated list-based responses include the following
        fields in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/invoice_filtered_list_by_contract_and_status
        """
        ctx = setup_grant_with_contract()
        con_id = ctx["contract"]["id"]
        ctr_id = ctx["contractor"]["id"]
        verify_invoice(file_invoice(con_id, ctr_id, invoice_number="INV-1")["id"])
        inv2 = reject_invoice(
            file_invoice(con_id, ctr_id, invoice_number="INV-2", gross_amount=5_000)["id"])

        data, meta = validate_paginated(api_client.list_invoices(
            SPONSOR, params={"contract_id": con_id, "status": "REJECTED"}))
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [inv2["id"]]
