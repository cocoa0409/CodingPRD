"""Purchase-limit aggregation, special-population blocks, and per-order caps
(PRD §3.5).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    setup_psychotropic_window_scenario,
    setup_prescription_scenario,
    setup_basic_platform,
    create_pharmacist,
    create_customer,
    create_two_pharmacists,
    create_and_shelve_drug,
    create_otc_drug_on_shelf,
    upload_and_approve_prescription,
    place_order,
    pay_order,
    advance_clock,
    setup_platform_at_clock,
    create_platform,
    create_vendor,
    prescription_item,
    order_item,
    create_purchase_limit_rule_payload,
    create_order_payload,
    add_days,
    TEST_USERS,
    make_admin_headers,
    make_customer_headers,
)


# ---------------------------------------------------------------------------
# Per-order quantity cap (PRD §3.5)
# ---------------------------------------------------------------------------

class TestPerOrderQuantityCap:
    """PRD §3.5: 'For each line, qty must not exceed the line's drug's
    per_order_qty_cap; otherwise the order is rejected with
    ERR_PURCHASE_LIMIT_EXCEEDED.'
    """

    def test_qty_at_cap_succeeds(self, api):
        """PRD §3.5: qty == per_order_qty_cap is allowed (boundary, not exceeded)."""
        pf, vendor = setup_basic_platform(api)
        drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"],
                                            per_order_qty_cap=5)
        customer = create_customer(api, pf["id"], real_name_verified=True)
        order = place_order(api, pf["id"], customer,
                              items=[order_item(drug["id"], qty=5, unit_price_cents=1000)])
        assert order["dispensing_status"] == "PENDING_REVIEW"

    def test_qty_above_cap_rejected(self, api):
        """PRD §3.5: qty > per_order_qty_cap → ERR_PURCHASE_LIMIT_EXCEEDED."""
        pf, vendor = setup_basic_platform(api)
        drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"],
                                            per_order_qty_cap=5)
        customer = create_customer(api, pf["id"], real_name_verified=True)
        resp = api.create_order(
            pf["id"],
            create_order_payload(customer["id"],
                                   items=[order_item(drug["id"], qty=6,
                                                       unit_price_cents=1000)]),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PURCHASE_LIMIT_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Special-population block (PRD §3.5)
# ---------------------------------------------------------------------------

class TestSpecialPopulationBlock:
    """PRD §3.5: 'For each line whose category is governed by a rule, the
    intersection of the customer's special_population_flags with that
    rule's blocks_special_populations must be empty; otherwise the order is
    rejected with ERR_SPECIAL_POPULATION_RESTRICTED.'
    """

    def test_blocked_population_rejected(self, api):
        pf, vendor = setup_basic_platform(api)
        drug = create_and_shelve_drug(api, pf["id"], vendor["id"],
                                          classification="PRESCRIPTION",
                                          control_category="NARCOTIC",
                                          per_order_qty_cap=10)
        # Rule blocks PREGNANCY for NARCOTIC.
        api.create_purchase_limit_rule(
            pf["id"],
            create_purchase_limit_rule_payload(
                control_category="NARCOTIC",
                window_days=30, max_units_per_window=100,
                blocks_special_populations=["PREGNANCY"],
            ),
            TEST_USERS["admin_headers"],
        )
        customer = create_customer(api, pf["id"], real_name_verified=True,
                                       special_population_flags=["PREGNANCY"])
        pr, _rr = create_two_pharmacists(api, pf["id"])
        rx = upload_and_approve_prescription(
            api, pf["id"], customer, pr,
            drug_items=[prescription_item(drug["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=999,
        )
        resp = api.create_order(
            pf["id"],
            create_order_payload(customer["id"],
                                   items=[order_item(drug["id"], qty=1, unit_price_cents=10_000)],
                                   prescription_id=rx["id"]),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SPECIAL_POPULATION_RESTRICTED.value)


# ---------------------------------------------------------------------------
# Rolling window aggregation (PRD §3.5)
# ---------------------------------------------------------------------------

class TestRollingWindowAggregation:
    """PRD §3.5: 'For each governed line, the server computes the window
    start as current_clock_iso minus the rule's window_days days. It then
    sums, in chronological order of paid_at, the qty of every line on every
    prior order that belongs to the same customer, has payment_status
    equal to PAID, has paid_at greater than or equal to the window start
    and strictly less than current_clock_iso (the window is closed at the
    left and open at the right), and whose drug shares the same
    control_category as the line under evaluation. To this existing total
    the server adds the proposed total ... If the existing-plus-proposed
    total is strictly greater than the rule's max_units_per_window, the
    order is rejected with ERR_PURCHASE_LIMIT_EXCEEDED.'

    # difficulty: resource_temporal_overlap/purchase_limit_rolling_window_aggregate_capacity
    """

    def test_aggregate_at_max_succeeds(self, api):
        """PRD §3.5: 'If the existing-plus-proposed total is strictly greater
        than the rule's max_units_per_window, the order is rejected.'

        existing=8, proposed=2, total=10 == max → NOT > max → succeeds.
        """
        s = setup_psychotropic_window_scenario(
            api,
            clock_iso="2025-01-31T00:00:00.000Z",
            window_days=30, max_units_per_window=10,
            existing_paid_units_in_window=8,
            existing_paid_units_outside_window=1,  # excluded by closed-open window
        )
        pf, drug, customer = s["platform"], s["drug"], s["customer"]
        rx = upload_and_approve_prescription(
            api, pf["id"], customer, s["pr_pharmacist"],
            drug_items=[prescription_item(drug["id"], qty=2)],
            issued_at="2025-01-31T00:00:00.000Z", validity_days=30,
        )
        resp = api.create_order(
            pf["id"],
            create_order_payload(customer["id"],
                                   items=[order_item(drug["id"], qty=2, unit_price_cents=10_000)],
                                   prescription_id=rx["id"]),
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["dispensing_status"] == "PENDING_REVIEW"

    def test_aggregate_above_max_rejected(self, api):
        """existing=8, proposed=3, total=11 > 10 → ERR_PURCHASE_LIMIT_EXCEEDED."""
        s = setup_psychotropic_window_scenario(
            api,
            clock_iso="2025-01-31T00:00:00.000Z",
            window_days=30, max_units_per_window=10,
            existing_paid_units_in_window=8,
            existing_paid_units_outside_window=0,
        )
        pf, drug, customer = s["platform"], s["drug"], s["customer"]
        rx = upload_and_approve_prescription(
            api, pf["id"], customer, s["pr_pharmacist"],
            drug_items=[prescription_item(drug["id"], qty=3)],
            issued_at="2025-01-31T00:00:00.000Z", validity_days=30,
        )
        resp = api.create_order(
            pf["id"],
            create_order_payload(customer["id"],
                                   items=[order_item(drug["id"], qty=3, unit_price_cents=10_000)],
                                   prescription_id=rx["id"]),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PURCHASE_LIMIT_EXCEEDED.value)

    def test_outside_window_excluded_from_aggregation(self, api):
        """PRD §3.5: 'has paid_at greater than or equal to the window start
        and strictly less than current_clock_iso (the window is closed at
        the left and open at the right).' An older PAID order outside the
        window must not contribute.

        Setup: 8 units inside window + 1 unit outside window. Aggregator
        should report 8, not 9. We propose qty=2 → new total 10 == max, OK.
        """
        s = setup_psychotropic_window_scenario(
            api,
            clock_iso="2025-01-31T00:00:00.000Z",
            window_days=30, max_units_per_window=10,
            existing_paid_units_in_window=8,
            existing_paid_units_outside_window=1,
        )
        pf, drug, customer = s["platform"], s["drug"], s["customer"]
        rx = upload_and_approve_prescription(
            api, pf["id"], customer, s["pr_pharmacist"],
            drug_items=[prescription_item(drug["id"], qty=2)],
            issued_at="2025-01-31T00:00:00.000Z", validity_days=30,
        )
        resp = api.create_order(
            pf["id"],
            create_order_payload(customer["id"],
                                   items=[order_item(drug["id"], qty=2, unit_price_cents=10_000)],
                                   prescription_id=rx["id"]),
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["dispensing_status"] == "PENDING_REVIEW"


# ---------------------------------------------------------------------------
# Compensating invariant: cancel-before-pay leaves units count unchanged
# (PRD §3.5)
# ---------------------------------------------------------------------------

class TestCompensatingInvariantCancelBeforePay:
    """PRD §3.5: 'Past orders that are REFUNDED, CANCELLED, or REJECTED are
    not counted; orders that are UNPAID are also not counted regardless of
    dispensing state.'

    A 'place-and-cancel-before-pay' sequence MUST NOT contribute to the
    aggregator. After cancellation, a fresh order at the cap MUST still
    succeed.

    # difficulty: compensating_invariant/purchase_limit_units_invariant_on_revoke_cancel
    """

    def test_cancelled_unpaid_order_does_not_count(self, api):
        clock = "2025-01-15T00:00:00.000Z"
        pf = setup_platform_at_clock(api, clock)
        vendor = create_vendor(api, pf["id"])
        drug = create_and_shelve_drug(api, pf["id"], vendor["id"],
                                          classification="PRESCRIPTION",
                                          control_category="PSYCHOTROPIC_II",
                                          per_order_qty_cap=10)
        api.create_purchase_limit_rule(
            pf["id"],
            create_purchase_limit_rule_payload(
                control_category="PSYCHOTROPIC_II",
                window_days=30, max_units_per_window=10,
                blocks_special_populations=[],
            ),
            TEST_USERS["admin_headers"],
        )
        customer = create_customer(api, pf["id"], real_name_verified=True)
        pr, _rr = create_two_pharmacists(api, pf["id"])
        # Place 1st order qty=5 (UNPAID); cancel it.
        rx1 = upload_and_approve_prescription(
            api, pf["id"], customer, pr,
            drug_items=[prescription_item(drug["id"], qty=5)],
            issued_at=clock, validity_days=999,
        )
        order1 = place_order(api, pf["id"], customer,
                                items=[order_item(drug["id"], qty=5, unit_price_cents=10_000)],
                                prescription_id=rx1["id"])
        from test_helpers import cancel_order
        cancel_order(api, pf["id"], order1)
        # Now place qty=10 — total in window for PAID orders should be 0,
        # so 0 + 10 = 10 == max (NOT > max), succeeds.
        rx2 = upload_and_approve_prescription(
            api, pf["id"], customer, pr,
            drug_items=[prescription_item(drug["id"], qty=10)],
            issued_at=clock, validity_days=999,
        )
        resp = api.create_order(
            pf["id"],
            create_order_payload(customer["id"],
                                   items=[order_item(drug["id"], qty=10, unit_price_cents=10_000)],
                                   prescription_id=rx2["id"]),
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["dispensing_status"] == "PENDING_REVIEW"
