"""Size exchanges: full swap cycle, differential settlement, window, RBAC."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_exchange,
    create_active_program,
    create_approved_design,
    create_approved_vendor_with_quote,
    create_exchange,
    create_open_event,
    create_pos_order,
    create_variant,
    get_order,
    get_variant,
    make_customer_headers,
    set_clock,
    setup_exchange_shop,
    stock_variant,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestExchangeFullCycle:
    def test_exchange_full_cycle_swaps_inventory(self, api):
        """PRD §3.7: "At creation the server computes `differential_cents`:
        the new variant's `unit_price_cents` minus the unit price captured on
        the original order line."
        PRD §3.7: "`RESALEABLE` units go back on the shelf (the original
        variant's `on_hand_qty` rises by 1) while `DAMAGED` units are written
        off and not restocked — and the held new unit leaves the shelf as the
        new variant's `reserved_online_qty` and `on_hand_qty` each fall by 1."

        Design: Corner/state_machines/exchange_full_cycle_swaps_inventory
        """
        shop = setup_exchange_shop(customer_user_id="cust-40")
        exchange = create_exchange(
            shop["program"]["id"],
            shop["order"]["id"],
            shop["variant_m"]["id"],
            shop["variant_l"]["id"],
            "cust-40",
        )
        assert exchange["differential_cents"] == 0, "equal list prices: even swap"
        approve_exchange(exchange["id"])
        variant_l = get_variant(shop["variant_l"]["id"])
        assert variant_l["reserved_online_qty"] == 1, (
            "approval holds one unit of the new variant"
        )

        completed = validate_success(
            api.complete_exchange(exchange["id"], {"condition": "RESALEABLE"}, TREASURER),
            200,
        )
        assert completed["status"] == "COMPLETED"
        variant_m = get_variant(shop["variant_m"]["id"])
        assert variant_m["on_hand_qty"] == 25, (
            "24 after the sale, +1 RESALEABLE return"
        )
        variant_l = get_variant(shop["variant_l"]["id"])
        assert variant_l["on_hand_qty"] == 24 and variant_l["reserved_online_qty"] == 0, (
            "the held unit left the shelf; the approval reservation is "
            "released"
        )


class TestExchangeDifferentialRefund:
    def test_exchange_differential_refund_when_cheaper(self, api):
        """PRD §3.7: "At creation the server computes `differential_cents`:
        the new variant's `unit_price_cents` minus the unit price captured on
        the original order line."
        PRD §3.7: "A negative differential is refunded against the original
        order, whose `refunded_cents` grows by the absolute differential and
        whose `payment_status` may move to `PARTIALLY_REFUNDED`."

        Design: Corner/calculations/exchange_differential_refund_when_cheaper
        """
        shop = setup_exchange_shop(
            original_price=3000, new_price=2500, customer_user_id="cust-41"
        )
        exchange = create_exchange(
            shop["program"]["id"],
            shop["order"]["id"],
            shop["variant_m"]["id"],
            shop["variant_l"]["id"],
            "cust-41",
        )
        assert exchange["differential_cents"] == -500, "2500 - 3000"
        approve_exchange(exchange["id"])
        completed = validate_success(
            api.complete_exchange(exchange["id"], {"condition": "RESALEABLE"}, TREASURER),
            200,
        )
        assert completed["status"] == "COMPLETED"

        order = get_order(shop["order"]["id"])
        assert order["refunded_cents"] == 500
        assert order["payment_status"] == "PARTIALLY_REFUNDED", (
            "500 < 3000 total leaves the order partially refunded"
        )


class TestExchangeWindow:
    def test_exchange_window_last_day_allowed_day15_rejected(self, api):
        """PRD §3.7: "Within `exchange_window_days` of the order's fulfillment
        — the final day still counts; an exchange opened later is
        `ERR_EXCHANGE_WINDOW_CLOSED`"

        Design: Corner/validations/exchange_window_last_day_allowed_day15_rejected
        """
        program = create_active_program()
        design = create_approved_design(program["id"])
        variant_m = create_variant(program["id"], design["id"], size="M")
        variant_l = create_variant(program["id"], design["id"], size="L")
        vendor = create_approved_vendor_with_quote(program["id"], design["id"])
        stock_variant(program["id"], variant_m["id"], vendor["id"], 25)
        stock_variant(program["id"], variant_l["id"], vendor["id"], 25)

        set_clock("2026-09-05T15:00:00Z")
        event = create_open_event(program["id"], register="GYM-W")
        order1 = create_pos_order(
            program["id"], event["id"], variant_m["id"], 1,
            customer_user_id="cust-A", payment_method="CARD",
        )
        order2 = create_pos_order(
            program["id"], event["id"], variant_m["id"], 1,
            customer_user_id="cust-B", payment_method="CARD",
        )

        # Exactly fulfillment_day + 14 days: the final day still counts.
        set_clock("2026-09-19T15:00:00Z")
        exchange1 = validate_success(
            api.create_exchange(
                {
                    "program_id": program["id"],
                    "order_id": order1["id"],
                    "original_variant_id": variant_m["id"],
                    "new_variant_id": variant_l["id"],
                },
                make_customer_headers("cust-A"),
            ),
            201,
        )
        assert exchange1["id"]

        # One second past the window: closed.
        set_clock("2026-09-20T15:00:01Z")
        res = api.create_exchange(
            {
                "program_id": program["id"],
                "order_id": order2["id"],
                "original_variant_id": variant_m["id"],
                "new_variant_id": variant_l["id"],
            },
            make_customer_headers("cust-B"),
        )
        validate_error(res, ApiErrorId.ERR_EXCHANGE_WINDOW_CLOSED, 422)


class TestExchangeEligibility:
    def test_exchange_foreign_design_rejected(self, api):
        """PRD §3.7: "The original variant must appear among the order's
        lines, and the new variant must share the original's design while
        differing in size; violations are `ERR_EXCHANGE_VARIANT_MISMATCH`."

        Design: Corner/errors/exchange_foreign_design_rejected
        """
        program = create_active_program()
        design_a = create_approved_design(program["id"], name="A")
        design_b = create_approved_design(program["id"], name="B")
        variant_a = create_variant(program["id"], design_a["id"], size="M")
        variant_b = create_variant(program["id"], design_b["id"], size="M")
        vendor = create_approved_vendor_with_quote(program["id"], design_a["id"])
        stock_variant(program["id"], variant_a["id"], vendor["id"], 25)
        event = create_open_event(program["id"], register="GYM-F")
        order = create_pos_order(
            program["id"], event["id"], variant_a["id"], 1,
            customer_user_id="cust-84", payment_method="CARD",
        )
        res = api.create_exchange(
            {
                "program_id": program["id"],
                "order_id": order["id"],
                "original_variant_id": variant_a["id"],
                "new_variant_id": variant_b["id"],
            },
            make_customer_headers("cust-84"),
        )
        validate_error(res, ApiErrorId.ERR_EXCHANGE_VARIANT_MISMATCH, 422)

    def test_customer_cannot_exchange_others_order(self, api):
        """PRD §2.1: "paying a preorder, cancelling a preorder, and opening an
        exchange are own-resource actions, and for those the request's
        `X-User-ID` must equal the resource's `customer_user_id` — for an
        exchange, the `customer_user_id` of the order being exchanged. A
        mismatch is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/customer_cannot_exchange_others_order
        """
        shop = setup_exchange_shop(customer_user_id="cust-A")
        res = api.create_exchange(
            {
                "program_id": shop["program"]["id"],
                "order_id": shop["order"]["id"],
                "original_variant_id": shop["variant_m"]["id"],
                "new_variant_id": shop["variant_l"]["id"],
            },
            make_customer_headers("cust-B"),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
