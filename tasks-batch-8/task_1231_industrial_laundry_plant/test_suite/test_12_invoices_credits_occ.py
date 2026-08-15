"""Invoices, credits, and optimistic concurrency: issue/pay balance
conservation, version increments, stale-version rejection, credit-limit and
credit-target guards, and the discrepancy credit cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_invoice, assert_invoice_total_invariants,
    create_plant, create_linen_category, create_customer,
    generate_invoice, issue_invoice, get_invoice, get_customer,
    get_customer_version, setup_finished_load, setup_discrepancy_approved,
    setup_stop_received, manifest_delivery, get_delivery,
)

CLERK = TEST_USERS["billing_clerk_headers"]
DRIVER = TEST_USERS["route_driver_headers"]

MAY = {"billing_period_start": "2026-05-01", "billing_period_end": "2026-06-01"}


def _cog_ctx_with_finished_load():
    """100 pieces * 0.5 lb at 120 c/lb -> 6000 cents linen on a May invoice
    (default logical clock, PRD §2.5)."""
    return setup_finished_load(
        pieces=100,
        stop_overrides={"declared_soiled_weight_lb": 50.0},
        carts=[{"cart_tag": "CART-1", "scale_weight_lb": 50.0}],
        load_overrides={
            "machine_id": "M1",
            "scheduled_start": "2026-05-02T08:00:00Z",
            "scheduled_end": "2026-05-02T09:00:00Z",
        },
    )


class TestIssueStateGuard:
    def test_double_issue_rejected_as_invalid_state(self, api):
        """PRD §2.9: "Incoming requests are validated in a fixed priority order, so that when several problems are present the earliest check is the one reported."
        PRD §2.9: "State admissibility: the target resource must be in a state that permits the requested transition — `ERR_INVALID_STATE` (HTTP 409). Applies to all state-transition endpoints."
        PRD §3.8: "Issuing an invoice moves it from `DRAFT` to `ISSUED` under three guards."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_invoice_issue
        """
        ctx = _cog_ctx_with_finished_load()
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        assert invoice["total_due_cents"] == 6000
        version = get_customer_version(ctx["customer"]["id"])
        issued = issue_invoice(invoice["id"], version)
        assert issued["status"] == "ISSUED"

        fresh_version = get_customer_version(ctx["customer"]["id"])
        resp = api.issue_invoice(
            invoice["id"], {"expected_customer_version": fresh_version}, CLERK
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_issue_after_void_rejected_as_invalid_state(self, api):
        """PRD §3.8: "Voiding abandons a `DRAFT` invoice, moving it to the terminal `VOID`; voiding is blocked while any discrepancy in `CREDITED` references the invoice, failing with `ERR_INVOICE_HAS_CREDITS`, and on success any pending lost-item charge queue entries targeted at this invoice are released back to the unbilled queue."
        PRD §2.9: "State admissibility: the target resource must be in a state that permits the requested transition — `ERR_INVALID_STATE` (HTTP 409). Applies to all state-transition endpoints."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_invoice_issue
        """
        plant = create_plant()
        customer = create_customer(plant["id"], billing_mode="COG")
        invoice = generate_invoice(customer["id"], **MAY)
        validate_success(api.void_invoice(invoice["id"], CLERK), 200)
        version = get_customer_version(customer["id"])
        resp = api.issue_invoice(
            invoice["id"], {"expected_customer_version": version}, CLERK
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBalanceConservation:
    def test_issue_then_pay_conserves_balance(self, api):
        """PRD §3.8: "On success the invoice total is added to `account_balance_cents` and the customer's `version` increments by one. Marking an issued invoice paid moves it from `ISSUED` to the terminal `PAID` and subtracts the total from `account_balance_cents`, again bumping the customer's `version`."

        Design: Difficulty/compensating_invariant/invoice_issue_then_pay_conserves_customer_balance
        """
        ctx = _cog_ctx_with_finished_load()
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        assert invoice["total_due_cents"] == 6000

        bal_pre = get_customer(ctx["customer"]["id"])["account_balance_cents"]
        assert bal_pre == 0
        issue_invoice(invoice["id"], get_customer_version(ctx["customer"]["id"]))
        bal_mid = get_customer(ctx["customer"]["id"])["account_balance_cents"]
        assert bal_mid == 6000, f"issue must add the total, got {bal_mid}"

        validate_success(api.mark_paid_invoice(invoice["id"], CLERK), 200)
        bal_post = get_customer(ctx["customer"]["id"])["account_balance_cents"]
        assert bal_post == 0, f"pay must subtract the same total, got {bal_post}"
        assert bal_post == bal_pre

    def test_customer_version_increments_once_per_balance_mutation(self, api):
        """PRD §2.4: "Note that several workflows mutate a `Customer`'s balance and therefore bump the customer's `version`: marking a delivery delivered, issuing an invoice, marking an invoice paid, and applying a discrepancy credit each increment the customer's `version` by one. By contrast, upserting a par-level row does not touch the customer's `version` at all — the par-level row carries its own `version` and the customer record is left untouched."

        Design: Difficulty/compensating_invariant/invoice_issue_then_pay_conserves_customer_balance
        """
        ctx = _cog_ctx_with_finished_load()
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        ver_pre = get_customer_version(ctx["customer"]["id"])
        issue_invoice(invoice["id"], ver_pre)
        ver_mid = get_customer_version(ctx["customer"]["id"])
        assert ver_mid == ver_pre + 1, (
            f"issue must bump the version by exactly one, {ver_pre} -> {ver_mid}"
        )
        validate_success(api.mark_paid_invoice(invoice["id"], CLERK), 200)
        ver_post = get_customer_version(ctx["customer"]["id"])
        assert ver_post == ver_mid + 1, (
            f"mark-paid must bump the version by exactly one, {ver_mid} -> {ver_post}"
        )


class TestOptimisticConcurrency:
    def test_stale_version_on_invoice_issue(self, api):
        """PRD §2.7: "Issuing an invoice requires the request to carry `expected_customer_version`, the `version` of the invoice's customer as last observed by the client. If the customer's current `version` does not match — because, for example, another writer has since posted a utility surcharge true-up or applied a credit, both of which mutate `account_balance_cents` and bump the customer's `version` — the issue is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_version_on_invoice_issue
        """
        plant = create_plant()
        customer = create_customer(plant["id"], billing_mode="COG")
        invoice = generate_invoice(customer["id"], **MAY)
        version = get_customer_version(customer["id"])
        resp = api.issue_invoice(
            invoice["id"], {"expected_customer_version": version - 1}, CLERK
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_version_on_mark_delivered(self, api):
        """PRD §2.7: "Marking a delivery delivered likewise requires the request to carry `expected_customer_version` matching the current `version` of the customer on the delivery's stop. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since `account_balance_cents`, and therefore the credit-limit precondition, may have changed since the driver last read the customer."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_mark_delivered
        """
        ctx = setup_stop_received(customer_overrides={"billing_mode": "RENTAL"})
        delivery = manifest_delivery(
            ctx["stop"]["id"], ctx["category"]["id"], 10
        )
        version = get_customer_version(ctx["customer"]["id"], DRIVER)
        resp = api.mark_delivered(
            delivery["id"],
            {"pieces_delivered": 10, "expected_customer_version": version - 1},
            DRIVER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_issue_bumps_customer_version(self, api):
        """PRD §2.4: "Note that several workflows mutate a `Customer`'s balance and therefore bump the customer's `version`: marking a delivery delivered, issuing an invoice, marking an invoice paid, and applying a discrepancy credit each increment the customer's `version` by one."
        PRD §3.8: "On success the invoice total is added to `account_balance_cents` and the customer's `version` increments by one."

        Design: Corner/cross_cutting_layers/customer_version_increments_on_balance_mutation
        """
        plant = create_plant()
        customer = create_customer(plant["id"], billing_mode="COG")
        invoice = generate_invoice(customer["id"], **MAY)
        ver_pre = get_customer_version(customer["id"])
        issued = issue_invoice(invoice["id"], ver_pre)
        assert issued["status"] == "ISSUED"
        ver_post = get_customer_version(customer["id"])
        assert ver_post == ver_pre + 1, (
            f"version must increment by exactly one on issue, "
            f"{ver_pre} -> {ver_post}"
        )


class TestCreditLimit:
    def test_issue_beyond_credit_limit_rejected(self, api):
        """PRD §3.8: "The customer's `account_balance_cents` plus the invoice's `total_due_cents` must not exceed `credit_limit_cents`, unless the total is zero, in which case issue proceeds; a breach fails with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/errors/error_credit_limit_exceeded_on_issue
        """
        ctx = setup_finished_load(
            pieces=100,
            customer_overrides={"credit_limit_cents": 100},
            stop_overrides={"declared_soiled_weight_lb": 50.0},
            carts=[{"cart_tag": "CART-1", "scale_weight_lb": 50.0}],
            load_overrides={
                "machine_id": "M1",
                "scheduled_start": "2026-05-02T08:00:00Z",
                "scheduled_end": "2026-05-02T09:00:00Z",
            },
        )
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        assert invoice["total_due_cents"] == 6000
        version = get_customer_version(ctx["customer"]["id"])
        resp = api.issue_invoice(
            invoice["id"], {"expected_customer_version": version}, CLERK
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestCreditCascade:
    def test_apply_credit_cascades_to_invoice_and_balance(self, api):
        """PRD §3.7: "Applying the credit moves the discrepancy from `APPROVED` to the terminal `CREDITED`, adds `credit_cents` into the invoice's `credits_cents`, recomputes the invoice's `total_due_cents`, subtracts `credit_cents` from the customer's `account_balance_cents`, and bumps the customer's `version` by one."
        PRD §3.8: "The invoice's `total_due_cents` is the linen charges plus the lost-item charges plus the utility surcharge minus the credits, floored at zero; the same formula recomputes on every credit application and every lost-item queue drain."

        Design: Difficulty/transitive_cascade/discrepancy_approve_to_customer_balance_chain
        """
        ctx = setup_discrepancy_approved(claimed=2, approved=2)
        assert ctx["discrepancy"]["credit_cents"] == 600, (
            "2 pieces * 500 cents * 60% must approve a 600-cent credit"
        )
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        before = get_invoice(invoice["id"])
        bal_before = get_customer(ctx["customer"]["id"])["account_balance_cents"]

        validate_success(api.apply_credit_discrepancy(
            ctx["discrepancy"]["id"], {"invoice_id": invoice["id"]}, CLERK
        ), 200)

        disp = get_success_data(api.get_discrepancy(ctx["discrepancy"]["id"], CLERK))
        assert disp["status"] == "CREDITED"
        after = get_invoice(invoice["id"])
        assert after["credits_cents"] == before["credits_cents"] + 600
        # RENTAL customer with no par rows: total 0 floored against 600 credit.
        assert after["total_due_cents"] == 0, "the total floors at zero"
        assert_invoice_total_invariants(after)
        bal_after = get_customer(ctx["customer"]["id"])["account_balance_cents"]
        assert bal_after == bal_before - 600, (
            f"credit must subtract from the balance: {bal_before} -> {bal_after}"
        )

    def test_apply_credit_settles_delivery_and_bumps_version(self, api):
        """PRD §3.7: "Whenever all discrepancies of a delivery have reached their terminal states — `CREDITED` or `REJECTED` — the delivery settles automatically from `DISPUTED` to `SETTLED`; this happens both on rejection and on credit application."
        PRD §3.7: "Applying the credit moves the discrepancy from `APPROVED` to the terminal `CREDITED`, adds `credit_cents` into the invoice's `credits_cents`, recomputes the invoice's `total_due_cents`, subtracts `credit_cents` from the customer's `account_balance_cents`, and bumps the customer's `version` by one."

        Design: Difficulty/transitive_cascade/discrepancy_approve_to_customer_balance_chain
        """
        ctx = setup_discrepancy_approved(claimed=2, approved=2)
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        ver_pre = get_customer_version(ctx["customer"]["id"])
        validate_success(api.apply_credit_discrepancy(
            ctx["discrepancy"]["id"], {"invoice_id": invoice["id"]}, CLERK
        ), 200)
        assert get_delivery(ctx["delivery"]["id"])["status"] == "SETTLED", (
            "with its only discrepancy CREDITED the delivery must settle"
        )
        ver_post = get_customer_version(ctx["customer"]["id"])
        assert ver_post == ver_pre + 1, (
            f"credit application must bump the customer version by one, "
            f"{ver_pre} -> {ver_post}"
        )


class TestCreditTargetGuards:
    def test_apply_credit_to_issued_invoice_rejected(self, api):
        """PRD §3.7: "The target invoice must belong to the same customer as the disputed delivery's stop — a cross-customer credit fails with `ERR_INVOICE_CUSTOMER_MISMATCH` — and must be in `DRAFT` status, failing otherwise with `ERR_INVOICE_NOT_DRAFT`."
        PRD §3.8: "The customer's `account_balance_cents` plus the invoice's `total_due_cents` must not exceed `credit_limit_cents`, unless the total is zero, in which case issue proceeds; a breach fails with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/apply_credit_to_issued_invoice_rejected
        """
        ctx = setup_discrepancy_approved(claimed=2, approved=2)
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        assert invoice["total_due_cents"] == 0, (
            "RENTAL customer with no par rows generates a zero total"
        )
        version = get_customer_version(ctx["customer"]["id"])
        issued = issue_invoice(invoice["id"], version)
        assert issued["status"] == "ISSUED"
        resp = api.apply_credit_discrepancy(
            ctx["discrepancy"]["id"], {"invoice_id": invoice["id"]}, CLERK
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_DRAFT)

    def test_apply_credit_to_other_customers_invoice_rejected(self, api):
        """PRD §3.7: "The target invoice must belong to the same customer as the disputed delivery's stop — a cross-customer credit fails with `ERR_INVOICE_CUSTOMER_MISMATCH` — and must be in `DRAFT` status, failing otherwise with `ERR_INVOICE_NOT_DRAFT`."

        Design: Corner/errors/error_invoice_customer_mismatch_triggerable
        """
        ctx = setup_discrepancy_approved(claimed=2, approved=2)
        other = create_customer(ctx["plant"]["id"], name="C2",
                                billing_mode="RENTAL")
        other_invoice = generate_invoice(other["id"], **MAY)
        resp = api.apply_credit_discrepancy(
            ctx["discrepancy"]["id"], {"invoice_id": other_invoice["id"]}, CLERK
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_CUSTOMER_MISMATCH)

    def test_invoice_void_blocked_when_credited(self, api):
        """PRD §3.8: "Voiding abandons a `DRAFT` invoice, moving it to the terminal `VOID`; voiding is blocked while any discrepancy in `CREDITED` references the invoice, failing with `ERR_INVOICE_HAS_CREDITS`, and on success any pending lost-item charge queue entries targeted at this invoice are released back to the unbilled queue."

        Design: Corner/state_machines/invoice_void_blocked_when_credited
        """
        ctx = setup_discrepancy_approved(claimed=2, approved=2)
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        validate_success(api.apply_credit_discrepancy(
            ctx["discrepancy"]["id"], {"invoice_id": invoice["id"]}, CLERK
        ), 200)
        resp = api.void_invoice(invoice["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_CREDITS)
