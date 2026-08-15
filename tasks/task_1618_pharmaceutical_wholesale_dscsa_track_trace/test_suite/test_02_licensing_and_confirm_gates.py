"""License lifecycle and the order-confirmation gate: license verification,
scope requirements, expiry-window boundaries, credit-limit enforcement, and
the fixed ordering of state vs fiscal rejections."""
from test_helpers import (
    ApiErrorId,
    FulfillmentStatus,
    confirm_order,
    create_license,
    create_order_with_line,
    create_partner,
    create_product,
    get_order,
    get_partner,
    set_clock,
    setup_customer_with_license,
    validate_error,
    validate_success,
)


class TestLicenseTerminalLockdown:
    def test_revoke_terminal_license_rejected(
        self, api, order_manager_headers, compliance_officer_headers
    ):
        """PRD §3.1: "Revocation is available from either `ACTIVE` or
        `SUSPENDED` and lands in the terminal `REVOKED` state; acting on an
        already-revoked license is rejected with `ERR_LICENSE_ALREADY_REVOKED`."

        Design: Corner/state_machines/revoke_terminal_license_rejected
        """
        partner = create_partner(partner_name="RevRx")
        lic = create_license(partner["id"], state_code="WA", license_scope="RX_ONLY")
        revoke1 = api.revoke_license(lic["id"], compliance_officer_headers)
        data = validate_success(revoke1)
        assert data["license_status"] == "REVOKED"

        revoke2 = api.revoke_license(lic["id"], compliance_officer_headers)
        validate_error(revoke2, ApiErrorId.ERR_LICENSE_ALREADY_REVOKED)


class TestConfirmLicenseVerification:
    def test_confirm_without_license_fails(self, api, order_manager_headers):
        """PRD §3.4: "the customer must hold a state license covering the
        `ship_to_state` that is `ACTIVE` with `valid_to` at or beyond the
        current logical clock, failing which the confirm is rejected with
        `ERR_LICENSE_VERIFICATION_FAILED` (HTTP 403)."

        Design: Corner/validations/confirm_without_license_fails
        """
        set_clock()
        # Customer is licensed for WA only; the order ships to CA.
        customer, _lic = setup_customer_with_license(name="NoLicRx", state_code="WA")
        product = create_product()
        order, _line = create_order_with_line(customer["id"], product["id"], 1)

        resp = api.confirm_order(order["id"], order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LICENSE_VERIFICATION_FAILED)
        assert get_order(order["id"])["fulfillment_status"] == FulfillmentStatus.DRAFT.value

    def test_confirm_controlled_without_scope_fails(self, api, order_manager_headers):
        """PRD §3.4: "If any line's product `is_controlled`, that license's
        `license_scope` must be `RX_AND_CONTROLLED` or `FULL`, failing which the
        confirm is rejected with `ERR_CONTROLLED_LICENSE_REQUIRED` (HTTP 403)".

        Design: Corner/validations/confirm_controlled_without_scope_fails
        """
        set_clock()
        customer, _lic = setup_customer_with_license(
            name="CtlRx", license_scope="RX_ONLY"
        )
        product = create_product(is_controlled=True)
        order, _line = create_order_with_line(customer["id"], product["id"], 1)

        resp = api.confirm_order(order["id"], order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CONTROLLED_LICENSE_REQUIRED)
        assert get_order(order["id"])["fulfillment_status"] == FulfillmentStatus.DRAFT.value


class TestConfirmDependsOnLicenseState:
    """Cross-entity gate: the license lifecycle (a different resource) flips an
    order's confirm outcome without the order itself changing."""

    def _setup_draft_order(self):
        set_clock()
        customer, lic = setup_customer_with_license(name="LicRx")
        product = create_product()
        order, _line = create_order_with_line(customer["id"], product["id"], 2)
        return customer, lic, product, order

    def test_confirm_succeeds_while_license_active(self, api, order_manager_headers):
        """PRD §3.4: "the customer must hold a state license covering the
        `ship_to_state` that is `ACTIVE` with `valid_to` at or beyond the
        current logical clock, failing which the confirm is rejected with
        `ERR_LICENSE_VERIFICATION_FAILED` (HTTP 403)."

        Control leg: an ACTIVE in-window license admits the confirm.

        Design: Difficulty/cross_entity_state_dependency/order_confirm_depends_on_license_state
        """
        _customer, _lic, _product, order = self._setup_draft_order()
        resp = api.confirm_order(order["id"], order_manager_headers)
        data = validate_success(resp)
        assert data["fulfillment_status"] == FulfillmentStatus.CONFIRMED.value

    def test_confirm_rejected_after_license_suspended(
        self, api, order_manager_headers, compliance_officer_headers
    ):
        """PRD §3.4: "the customer must hold a state license covering the
        `ship_to_state` that is `ACTIVE` with `valid_to` at or beyond the
        current logical clock, failing which the confirm is rejected with
        `ERR_LICENSE_VERIFICATION_FAILED` (HTTP 403)."
        PRD §3.1: "Suspension moves `license_status` to `SUSPENDED`".

        Design: Difficulty/cross_entity_state_dependency/order_confirm_depends_on_license_state
        """
        _customer, lic, _product, order = self._setup_draft_order()
        suspend = api.suspend_license(lic["id"], compliance_officer_headers)
        assert validate_success(suspend)["license_status"] == "SUSPENDED"

        resp = api.confirm_order(order["id"], order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LICENSE_VERIFICATION_FAILED)
        assert get_order(order["id"])["fulfillment_status"] == FulfillmentStatus.DRAFT.value


class TestLicenseValidityWindowBoundary:
    """Closed-end validity: confirm admits valid_to >= clock; reinstatement is
    refused once the clock has passed valid_to."""

    def _setup_license_expiring_at(self, valid_to: str):
        set_clock("2026-08-01T00:00:00Z")
        customer, lic = setup_customer_with_license(
            name="WinRx", valid_to=valid_to
        )
        product = create_product()
        order, _line = create_order_with_line(customer["id"], product["id"], 1)
        return customer, lic, product, order

    def test_confirm_at_exact_license_expiry_instant_succeeds(
        self, api, order_manager_headers
    ):
        """PRD §3.4: "the customer must hold a state license covering the
        `ship_to_state` that is `ACTIVE` with `valid_to` at or beyond the
        current logical clock, failing which the confirm is rejected with
        `ERR_LICENSE_VERIFICATION_FAILED` (HTTP 403)."

        "At or beyond" makes the window closed at the end: the confirm succeeds
        at the exact valid_to instant.

        Design: Difficulty/resource_temporal_overlap/license_validity_window_expiry_boundary
        """
        _c, _lic, _p, order = self._setup_license_expiring_at("2026-08-01T12:00:00Z")
        set_clock("2026-08-01T12:00:00Z")
        resp = api.confirm_order(order["id"], order_manager_headers)
        data = validate_success(resp)
        assert data["fulfillment_status"] == FulfillmentStatus.CONFIRMED.value

    def test_reinstate_one_second_past_expiry_rejected(
        self, api, compliance_officer_headers
    ):
        """PRD §3.1: "Reinstatement returns a suspended license from `SUSPENDED`
        to `ACTIVE`, but only while the current logical clock has not passed
        `valid_to` — an expired license refuses reinstatement with
        `ERR_LICENSE_EXPIRED` (HTTP 403)".

        Design: Difficulty/resource_temporal_overlap/license_validity_window_expiry_boundary
        """
        _c, lic, _p, _o = self._setup_license_expiring_at("2026-08-01T12:00:00Z")
        set_clock("2026-08-01T12:00:00Z")
        suspend = api.suspend_license(lic["id"], compliance_officer_headers)
        assert validate_success(suspend)["license_status"] == "SUSPENDED"

        set_clock("2026-08-01T12:00:01Z")
        resp = api.reinstate_license(lic["id"], compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_LICENSE_EXPIRED)


class TestCreditLimitBoundary:
    def test_confirm_at_exact_credit_limit_succeeds(self, api, order_manager_headers):
        """PRD §3.4: "Only then does the credit gate run: the customer's
        projected `open_receivable_cents` after booking this invoice must not
        exceed `credit_limit_cents`, or the confirm fails with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        "Must not exceed" is inclusive: a projected receivable exactly equal to
        the limit passes.

        Design: Difficulty/boundary_precision_check/credit_limit_at_exactly_limit_passes
        """
        set_clock()
        customer, _lic = setup_customer_with_license(name="EdgeRx", credit_limit_cents=4000)
        product = create_product(wholesale_acquisition_cost_cents=1000)
        order, _line = create_order_with_line(customer["id"], product["id"], 4)

        resp = api.confirm_order(order["id"], order_manager_headers)
        data = validate_success(resp)
        assert data["fulfillment_status"] == FulfillmentStatus.CONFIRMED.value
        assert data["invoice_total_cents"] == 4000
        assert get_partner(customer["id"])["open_receivable_cents"] == 4000

    def test_confirm_over_credit_limit_rejected(self, api, order_manager_headers):
        """PRD §3.4: "Only then does the credit gate run: the customer's
        projected `open_receivable_cents` after booking this invoice must not
        exceed `credit_limit_cents`, or the confirm fails with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        With 4000 already booked against a 4000 limit, a further 1000 invoice
        projects 5000 — over the limit — and is rejected.

        Design: Difficulty/boundary_precision_check/credit_limit_at_exactly_limit_passes
        """
        set_clock()
        customer, _lic = setup_customer_with_license(name="EdgeRx", credit_limit_cents=4000)
        product = create_product(wholesale_acquisition_cost_cents=1000)

        order_a, _la = create_order_with_line(customer["id"], product["id"], 4)
        conf_a = api.confirm_order(order_a["id"], order_manager_headers)
        assert validate_success(conf_a)["fulfillment_status"] == FulfillmentStatus.CONFIRMED.value

        order_b, _lb = create_order_with_line(customer["id"], product["id"], 1)
        resp = api.confirm_order(order_b["id"], order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_order(order_b["id"])["fulfillment_status"] == FulfillmentStatus.DRAFT.value


class TestStateVersusFiscalOnConfirm:
    """The confirm gate evaluates state admissibility before the credit rule."""

    def _setup_two_orders_at_limit(self):
        set_clock()
        customer, _lic = setup_customer_with_license(name="DualRx", credit_limit_cents=4000)
        product = create_product(wholesale_acquisition_cost_cents=1000)
        order_a, _la = create_order_with_line(customer["id"], product["id"], 4)
        confirm_order(order_a["id"])  # receivable now exactly 4000
        order_b, _lb = create_order_with_line(customer["id"], product["id"], 1)
        return customer, product, order_a, order_b

    def test_confirm_credit_breach_with_clean_state_reports_fiscal_error(
        self, api, order_manager_headers
    ):
        """PRD §3.4: "Only then does the credit gate run: the customer's
        projected `open_receivable_cents` after booking this invoice must not
        exceed `credit_limit_cents`, or the confirm fails with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Control leg: a DRAFT order whose only violation is fiscal surfaces the
        fiscal error.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_confirm
        """
        _c, _p, _a, order_b = self._setup_two_orders_at_limit()
        resp = api.confirm_order(order_b["id"], order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_order(order_b["id"])["fulfillment_status"] == FulfillmentStatus.DRAFT.value

    def test_reconfirm_with_credit_breach_reports_state_error_first(
        self, api, order_manager_headers
    ):
        """PRD §3.4: "Confirmation is the pivotal checkpoint, performed by an
        `OrderManager`, and its gate evaluates checks in a fixed order. The
        order must be `DRAFT` (`ERR_ORDER_NOT_DRAFT`) and must contain at least
        one line (`ERR_ORDER_EMPTY`)."
        PRD §3.4: "Only then does the credit gate run".

        Re-confirming the already-CONFIRMED order would also breach the credit
        limit, but the state check runs first and ERR_ORDER_NOT_DRAFT surfaces.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_confirm
        """
        _c, _p, order_a, _b = self._setup_two_orders_at_limit()
        resp = api.confirm_order(order_a["id"], order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT)
