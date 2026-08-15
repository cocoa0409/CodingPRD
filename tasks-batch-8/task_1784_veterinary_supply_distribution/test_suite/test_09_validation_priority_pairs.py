"""Validation-pipeline ordering at the approval gate (PRD §2.8, §3.5)."""
from test_helpers import (
    ACCOUNT_MANAGER,
    ApiErrorId,
    create_active_clinic,
    create_approved_authorization,
    create_lot,
    create_order,
    create_product,
    create_stocked_product,
    get_order,
    make_clinic_buyer_headers,
    order_line_spec,
    setup_rx_scenario,
    submit_order,
    validate_error,
)


class TestStateBeatsSafety:
    def _setup_draft_rx_order_without_authorization(self, api, name_suffix=""):
        """ACTIVE clinic; stocked RX product; order left in DRAFT; NO
        ManufacturerAuthorization exists — both the state gate and the Rx gate
        would fail."""
        clinic = create_active_clinic(clinic_name=f"Clinic P1{name_suffix}",
                                      license_number=f"LIC-P1{name_suffix}",
                                      ship_to_address="10 Leash Ln")
        product, _lot = create_stocked_product(
            product_overrides={"sku": f"RX-P1{name_suffix}",
                               "product_name": "Carprofen 100mg",
                               "manufacturer_code": "ZOETIS",
                               "product_type": "RX_PHARMACEUTICAL",
                               "unit_price_cents": 10000})
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])
        return clinic, product, order

    def test_approve_state_error_beats_safety_error(self, api):
        """PRD §2.8: "Every request is validated in a fixed order, and the first
        failing check determines the error returned" — state preconditions
        (step 5) precede business safety rules (step 7).
        PRD §3.5: "The order must be `SUBMITTED` (otherwise
        `ERR_ORDER_INVALID_STATE`) and the clinic still `ACTIVE` (otherwise
        `ERR_CLINIC_NOT_ACTIVE`). Then the prescription-safety sequence runs."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_vs_safety_priority
        """
        _clinic, _product, order = (
            self._setup_draft_rx_order_without_authorization(api))

        # The order is DRAFT (state gate fails) AND no authorization exists
        # (Rx safety gate fails); the state error must win.
        resp = api.approve_order(order["id"], ACCOUNT_MANAGER)
        assert resp.json()["data"]["error_id"] != \
            ApiErrorId.ERR_RX_AUTHORIZATION_REQUIRED
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        assert get_order(order["id"])["status"] == "DRAFT"

    def test_approve_safety_error_surfaces_once_state_gate_passes(self, api):
        """PRD §2.8: "Every request is validated in a fixed order, and the first
        failing check determines the error returned"
        PRD §3.5: "For every `RX_PHARMACEUTICAL` line, the clinic must hold a
        ManufacturerAuthorization for that line's manufacturer that is
        `APPROVED` and whose window covers the current clock date on both ends —
        ... otherwise the approval is rejected with
        `ERR_RX_AUTHORIZATION_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_vs_safety_priority
        """
        clinic, _product, order = (
            self._setup_draft_rx_order_without_authorization(api, name_suffix="B"))

        # Once the state gate passes (order SUBMITTED), the same missing
        # authorization surfaces the safety error.
        submit_order(order["id"], clinic["id"])
        resp = api.approve_order(order["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_RX_AUTHORIZATION_REQUIRED)
        assert get_order(order["id"])["status"] == "SUBMITTED"


class TestSafetyBeatsFiscal:
    def _setup_submitted_rx_order_over_credit(self, api, *, with_authorization,
                                              name_suffix=""):
        """ACTIVE clinic with credit_limit 1000; stocked 10000c RX product;
        order SUBMITTED with total 12500 (10000 net + 2500 freight), which
        breaches the credit limit. Authorization present only if requested."""
        clinic = create_active_clinic(clinic_name=f"Clinic P2{name_suffix}",
                                      license_number=f"LIC-P2{name_suffix}",
                                      ship_to_address="11 Muzzle Ave",
                                      credit_limit_cents=1000,
                                      minimum_order_value_cents=5000,
                                      free_freight_threshold_cents=100000)
        product, _lot = create_stocked_product(
            product_overrides={"sku": f"RX-P2{name_suffix}",
                               "product_name": "Apoquel 16mg",
                               "manufacturer_code": "ZOETIS",
                               "product_type": "RX_PHARMACEUTICAL",
                               "unit_price_cents": 10000})
        if with_authorization:
            create_approved_authorization(
                clinic["id"], manufacturer_code="ZOETIS",
                approved_ship_to_address="11 Muzzle Ave")
        order = create_order(clinic["id"], [order_line_spec(product["id"], 1)])
        submitted = submit_order(order["id"], clinic["id"])
        assert submitted["total_cents"] == 12500
        return clinic, order

    def test_approve_safety_error_beats_fiscal_error(self, api):
        """PRD §2.8: "Every request is validated in a fixed order, and the first
        failing check determines the error returned" — business safety rules
        (step 7) precede fiscal rules (step 9).
        PRD §3.5: "Then the prescription-safety sequence runs. ... Finally the
        fiscal gate: the clinic's `credit_used_cents` plus this order's
        `total_cents` must remain at or below `credit_limit_cents` — equality
        passes — otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/approve_safety_vs_fiscal_priority
        """
        _clinic, order = self._setup_submitted_rx_order_over_credit(
            api, with_authorization=False)

        # Both the Rx-authorization gate (no authorization) and the credit gate
        # (0 + 12500 > 1000) fail; the safety error must win.
        resp = api.approve_order(order["id"], ACCOUNT_MANAGER)
        assert resp.json()["data"]["error_id"] != \
            ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED
        validate_error(resp, ApiErrorId.ERR_RX_AUTHORIZATION_REQUIRED)
        assert get_order(order["id"])["status"] == "SUBMITTED"

    def test_approve_fiscal_error_surfaces_once_safety_gate_passes(self, api):
        """PRD §3.5: "Finally the fiscal gate: the clinic's `credit_used_cents`
        plus this order's `total_cents` must remain at or below
        `credit_limit_cents` — equality passes — otherwise
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/approve_safety_vs_fiscal_priority
        """
        _clinic, order = self._setup_submitted_rx_order_over_credit(
            api, with_authorization=True, name_suffix="F")

        # With an APPROVED authorization in place, the safety sequence passes
        # and the fiscal gate fires: 0 + 12500 > 1000.
        resp = api.approve_order(order["id"], ACCOUNT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_order(order["id"])["status"] == "SUBMITTED"
