"""Boundary precision (difficulty rule 6).

X-1 / X / X+1 around three different metrics: money (credit limit at accept),
quantity (full vs short-by-one delivery), and time (delivery window end vs ETD).
"""
from test_helpers import (
    ApiErrorId,
    OPS,
    TEST_USERS,
    api_client,
    get_success_data,
    make_officer_headers,
    setup_accepted_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    arrive_vessel_call,
    confirm_delivery,
    create_agent,
    create_catalog_item,
    create_sent_quotation,
    create_stock_lot,
    create_submitted_requisition,
    create_vessel_call,
    create_scheduled_delivery,
    dispatch_delivery,
    set_clock,
)

WAREHOUSE = TEST_USERS["warehouse_headers"]


# ===========================================================================
# boundary_precision_check / credit_limit_exact_equality_accepted
# ===========================================================================

class TestCreditLimitExactEqualityAccepted:
    def test_total_equal_to_remaining_credit_is_accepted(self, api):
        """PRD §3.4: "then the credit gate compares the order's total against the
        agent's remaining credit per §3.9, surfacing `ERR_CREDIT_LIMIT_EXCEEDED`".
        PRD §3.9's gate rejects only when the total exceeds remaining credit, so
        exact equality is accepted (boundary inclusive-accept). Agent credit
        limit exactly 120,000; order total exactly 120,000 (1000 x 120).

        Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_accepted
        """
        ctx = setup_accepted_order(
            qty=1000, unit_price_cents=120,
            agent_overrides=dict(name="Agent Xi", credit_limit_cents=120000),
            item_overrides=dict(sku="WATER-14", name="Water 1L"),
            lot_overrides=dict(lot_code="DS-W14", received_qty=10000),
        )
        order = ctx["order"]
        assert order["total_cents"] == 120000
        assert order["fulfillment_status"] == "OPEN", (
            "Accept succeeds with order total == credit_limit (inclusive-accept)"
        )

    def test_one_cent_over_remaining_credit_is_rejected(self, api):
        """PRD §3.4: "surfacing `ERR_CREDIT_LIMIT_EXCEEDED`" when the order total
        exceeds remaining credit. One cent over the boundary: credit limit
        119,999 against the same 120,000-cent order => rejected.

        Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_accepted
        """
        agent = create_agent(name="Agent Xi-1", credit_limit_cents=119999)
        water = create_catalog_item(
            sku="WATER-14B", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-W14B", received_qty=10000)
        call = create_vessel_call(agent["id"])
        officer = make_officer_headers(call["id"])
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=1000)
        quo = create_sent_quotation(req["id"], water["id"], qty=1000, unit_price_cents=120)
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])
        resp = api_client.accept_quotation(quo["id"], officer)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


# ===========================================================================
# boundary_precision_check / delivery_full_vs_short_by_one
# ===========================================================================

class TestDeliveryFullVsShortByOne:
    def test_short_by_exactly_one_yields_partially_delivered(self, api):
        """PRD §3.6: "if any line remains short the order moves `OPEN →
        PARTIALLY_DELIVERED` (or stays `PARTIALLY_DELIVERED`), and when every
        line's `qty_delivered` reaches its `qty_ordered` the order becomes
        `DELIVERED`." Confirming 999 of 1000 (short by exactly 1) yields
        PARTIALLY_DELIVERED; the delivery itself completes (DELIVERED).

        Design: Difficulty/boundary_precision_check/delivery_full_vs_short_by_one
        """
        ctx = setup_accepted_order(
            qty=1000, unit_price_cents=120,
            item_overrides=dict(sku="WATER-15", name="Water 1L"),
            lot_overrides=dict(lot_code="DS-W15", received_qty=10000),
        )
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 1000)
        dispatch_delivery(delivery["id"])
        officer = make_officer_headers(ctx["call"]["id"])
        confirmed = confirm_delivery(delivery["id"], ctx["item"]["id"], 999, officer)
        assert confirmed["status"] == "DELIVERED", (
            "The delivery itself completed; the ORDER reflects the shortage"
        )
        order = get_success_data(api_client.get_order(ctx["order"]["id"], OPS))
        assert order["fulfillment_status"] == "PARTIALLY_DELIVERED", (
            "999 of 1000: short by exactly one unit crosses the == boundary"
        )

    def test_full_quantity_yields_delivered(self, api):
        """PRD §3.6: "when every line's `qty_delivered` reaches its `qty_ordered`
        the order becomes `DELIVERED`." Boundary equality: confirming all 1000
        of 1000 flips the order to DELIVERED.

        Design: Difficulty/boundary_precision_check/delivery_full_vs_short_by_one
        """
        ctx = setup_accepted_order(
            qty=1000, unit_price_cents=120,
            item_overrides=dict(sku="WATER-15", name="Water 1L"),
            lot_overrides=dict(lot_code="DS-W15", received_qty=10000),
        )
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 1000)
        dispatch_delivery(delivery["id"])
        officer = make_officer_headers(ctx["call"]["id"])
        confirm_delivery(delivery["id"], ctx["item"]["id"], 1000, officer)
        order = get_success_data(api_client.get_order(ctx["order"]["id"], OPS))
        assert order["fulfillment_status"] == "DELIVERED"


# ===========================================================================
# boundary_precision_check / delivery_window_etd_equality_allowed
# ===========================================================================

def _setup_open_order_for_window():
    return setup_accepted_order(
        qty=100, unit_price_cents=120,
        item_overrides=dict(sku="WATER-16", name="Water 1L"),
        lot_overrides=dict(lot_code="DS-W16", received_qty=10000),
    )


class TestDeliveryWindowEtdEqualityAllowed:
    def test_window_end_equal_to_etd_is_accepted(self, api):
        """PRD §3.6: "Containment is a closed interval; a window whose start equals
        the arrival or whose end equals the departure is admissible." window_end
        == scheduled_etd 2026-08-14T12:00:00Z exactly => delivery created.

        Design: Difficulty/boundary_precision_check/delivery_window_etd_equality_allowed
        """
        ctx = _setup_open_order_for_window()
        resp = api_client.create_delivery(ctx["order"]["id"], {
            "window_start": "2026-08-14T08:00:00Z",
            "window_end": "2026-08-14T12:00:00Z",  # == scheduled_etd
            "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 50}],
        }, WAREHOUSE)
        delivery = validate_success(resp, expected_status=201)
        assert delivery["status"] == "SCHEDULED"

    def test_window_end_one_second_past_etd_is_rejected(self, api):
        """PRD §3.6: "A window outside the stay is `ERR_WINDOW_OUTSIDE_PORT_STAY`."
        window_end == scheduled_etd + 1s => ERR_WINDOW_OUTSIDE_PORT_STAY.

        Design: Difficulty/boundary_precision_check/delivery_window_etd_equality_allowed
        """
        ctx = _setup_open_order_for_window()
        resp = api_client.create_delivery(ctx["order"]["id"], {
            "window_start": "2026-08-14T08:00:00Z",
            "window_end": "2026-08-14T12:00:01Z",  # one second past ETD
            "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 50}],
        }, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_PORT_STAY)
