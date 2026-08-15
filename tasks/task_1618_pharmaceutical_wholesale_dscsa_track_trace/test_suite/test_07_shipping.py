"""Shipping gates: segregation-mode coverage and the suspect-stock
interdiction driven by the investigation lifecycle."""
from test_helpers import (
    ApiErrorId,
    CaseStatus,
    FulfillmentStatus,
    clear_investigation,
    create_case,
    create_product,
    get_case,
    get_order,
    open_investigation,
    quarantine_investigation,
    set_clock,
    setup_allocated_order,
    setup_customer_with_license,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestSegregationCoverage:
    def test_segregation_mode_mismatch_on_ship(self, api, warehouse_operator_headers):
        """PRD §3.5: "and finally segregation coverage — controlled lines
        require the `CONTROLLED` declaration, cold-chain lines require
        `COLD_CHAIN`, and a shipment containing both classes is mixed and
        forbidden unless the declared `segregation_mode` is
        `SEGREGATED_COMBINED` (`ERR_SEGREGATION_REQUIRED`, HTTP 422)."

        A controlled line shipped under the STANDARD declaration is rejected.

        Design: Corner/validations/segregation_mode_mismatch_on_ship
        """
        set_clock()
        customer, _lic = setup_customer_with_license(name="SegRx")
        product = create_product(is_controlled=True)
        order = setup_allocated_order(customer["id"], product["id"], 1)
        assert order["fulfillment_status"] == FulfillmentStatus.ALLOCATED.value
        case = create_case(product["id"])

        resp = api.ship_order(
            order["id"], {"segregation_mode": "STANDARD", "case_ids": [case["id"]]},
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_REQUIRED)
        assert get_order(order["id"])["fulfillment_status"] == FulfillmentStatus.ALLOCATED.value
        assert get_case(case["id"])["case_status"] == CaseStatus.COMMISSIONED.value


class TestSuspectStockInterdiction:
    """Cross-entity gate: the investigation lifecycle blocks and re-enables
    the ship transition without touching the order."""

    def _setup_allocated_order_with_investigated_case(self, quarantine: bool):
        set_clock()
        customer, _lic = setup_customer_with_license(name="ShipRx")
        product = create_product(wholesale_acquisition_cost_cents=1000)
        order = setup_allocated_order(customer["id"], product["id"], 2)
        case = create_case(product["id"])
        inv = open_investigation(case["id"], qa_user_id="qa-1")
        if quarantine:
            quarantine_investigation(inv["id"], "qa-1")
        return customer, product, order, case, inv

    def test_ship_rejected_while_investigation_quarantined(
        self, api, warehouse_operator_headers
    ):
        """PRD §3.5: "then the suspect-stock interdiction — no listed case may
        be `QUARANTINED`, and no `OPEN` or `QUARANTINED` suspect investigation
        may exist for any listed case (`ERR_PRODUCT_UNDER_INVESTIGATION`, HTTP
        403)".
        PRD §3.5: "every listed case must be `COMMISSIONED` with a product
        matching some line's `product_id` (`ERR_CASE_NOT_SHIPPABLE`); then the
        suspect-stock interdiction".

        A ship request listing a quarantined case is rejected; the PRD orders
        the case-state check and the interdiction check adjacent to one
        another, so the rejection surfaces as one of the two named errors
        while the order itself is untouched.

        Design: Difficulty/cross_entity_state_dependency/ship_blocked_by_investigation_state
        """
        _c, _p, order, case, _inv = self._setup_allocated_order_with_investigated_case(
            quarantine=True
        )
        assert get_case(case["id"])["case_status"] == CaseStatus.QUARANTINED.value
        resp = api.ship_order(
            order["id"], {"segregation_mode": "STANDARD", "case_ids": [case["id"]]},
            warehouse_operator_headers,
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_PRODUCT_UNDER_INVESTIGATION, ApiErrorId.ERR_CASE_NOT_SHIPPABLE],
        )
        assert get_order(order["id"])["fulfillment_status"] == FulfillmentStatus.ALLOCATED.value

    def test_ship_succeeds_after_investigation_cleared(
        self, api, warehouse_operator_headers
    ):
        """PRD §3.6: "Clearing requires the investigation to be `QUARANTINED`
        (`ERR_INVESTIGATION_NOT_QUARANTINED`) and releases the case: the case's
        status is restored to what it was before quarantine — `RECEIVED` when
        it was quarantined from `RECEIVED`, otherwise `COMMISSIONED`".
        PRD §3.6: "even an `OPEN` investigation is enough to block shipping,
        since any ship request listing the case in `case_ids` fails with
        `ERR_PRODUCT_UNDER_INVESTIGATION` while the investigation is `OPEN` or
        `QUARANTINED`."

        The CLEARED transition (by a different QA lead, per segregation of
        duties) releases the case and re-enables the ship transition without
        any change to the order.

        Design: Difficulty/cross_entity_state_dependency/ship_blocked_by_investigation_state
        """
        _c, _p, order, case, inv = self._setup_allocated_order_with_investigated_case(
            quarantine=True
        )
        blocked = api.ship_order(
            order["id"], {"segregation_mode": "STANDARD", "case_ids": [case["id"]]},
            warehouse_operator_headers,
        )
        assert blocked.status_code >= 400, "quarantined investigation must block shipping"

        clear_investigation(inv["id"], "qa-2")
        assert get_case(case["id"])["case_status"] == CaseStatus.COMMISSIONED.value

        resp = api.ship_order(
            order["id"], {"segregation_mode": "STANDARD", "case_ids": [case["id"]]},
            warehouse_operator_headers,
        )
        data = validate_success(resp)
        assert data["fulfillment_status"] == FulfillmentStatus.SHIPPED.value

    def test_ship_rejected_with_case_under_open_investigation(
        self, api, warehouse_operator_headers
    ):
        """PRD §3.6: "Opening the investigation changes nothing about the case
        itself — interdiction requires the quarantine step — but even an `OPEN`
        investigation is enough to block shipping, since any ship request
        listing the case in `case_ids` fails with
        `ERR_PRODUCT_UNDER_INVESTIGATION` while the investigation is `OPEN` or
        `QUARANTINED`."

        The business-safety rejection fires even though the order is otherwise
        shippable (ALLOCATED, case COMMISSIONED, fresh lot, segregation
        satisfied).

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_ship_and_claim
        """
        _c, _p, order, case, _inv = self._setup_allocated_order_with_investigated_case(
            quarantine=False
        )
        assert get_case(case["id"])["case_status"] == CaseStatus.COMMISSIONED.value
        resp = api.ship_order(
            order["id"], {"segregation_mode": "STANDARD", "case_ids": [case["id"]]},
            warehouse_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_UNDER_INVESTIGATION)
        assert get_order(order["id"])["fulfillment_status"] == FulfillmentStatus.ALLOCATED.value
