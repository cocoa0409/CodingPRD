"""Promise dates, SLA breach, and vendor drop-ship margin settlement."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_branch,
    create_customer,
    create_item,
    get_order_lines,
    place_order,
    restock,
    set_clock,
    setup_confirmed_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
BRANCH_MANAGER = TEST_USERS["branch_manager_headers"]
VENDOR_REP = TEST_USERS["vendor_rep_headers"]


def _cutoff_setup(api):
    """Branch cutoff 900 (15:00 UTC); two WILL_CALL orders of 1 unit each."""
    customer = create_customer(
        account_number="CO-1", credit_limit_cents=10000000,
        primary_ship_to_state="OH",
    )
    item = create_item(sku="CO-1", list_price_cents=1000)
    branch = create_branch(location_code="BR-11", same_day_cutoff_minute=900)
    restock(branch["id"], item["id"], 2)
    order_a = place_order(
        customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
    )
    order_b = place_order(
        customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
    )
    return customer, item, branch, order_a, order_b


class TestSameDayCutoffMinuteBoundary:
    def test_confirm_exactly_at_cutoff_earns_same_day_promise(
        self, api, admin_headers
    ):
        """PRD §3.6: "the UTC minute-of-day of the logical clock at confirm is
        compared to the fulfilling branch's `same_day_cutoff_minute`: a minute no
        later than the cutoff — the boundary is inclusive — earns a `promise_date`
        of the confirm date itself, while a later minute rolls the promise to the
        next calendar day."

        Design: Difficulty/boundary_precision_check/same_day_cutoff_minute_boundary
        """
        _customer, _item, _branch, order_a, _order_b = _cutoff_setup(api)
        set_clock("2026-08-01T15:00:00Z")
        confirmed = validate_success(api.confirm_order(order_a["id"], admin_headers))
        assert confirmed["promise_date"] == "2026-08-01"

    def test_confirm_one_minute_after_cutoff_rolls_to_next_day(
        self, api, admin_headers
    ):
        """PRD §3.6: "a minute no later than the cutoff — the boundary is
        inclusive — earns a `promise_date` of the confirm date itself, while a
        later minute rolls the promise to the next calendar day."

        Design: Difficulty/boundary_precision_check/same_day_cutoff_minute_boundary
        """
        _customer, _item, _branch, _order_a, order_b = _cutoff_setup(api)
        set_clock("2026-08-01T15:01:00Z")
        confirmed = validate_success(api.confirm_order(order_b["id"], admin_headers))
        assert confirmed["promise_date"] == "2026-08-02"


class TestPromiseDateAndSlaBreach:
    def test_promise_date_null_for_standard_method(self, api, admin_headers):
        """PRD §3.6: "`STANDARD` orders carry no promise and keep `promise_date`
        null."

        Design: Corner/calculations/promise_date_null_for_standard_method
        """
        scenario = setup_confirmed_order(
            [{"qty": 1, "sku": "PN-1", "list_price_cents": 100}],
            customer_overrides={"account_number": "PN-1",
                                "credit_limit_cents": 100000},
            branch_overrides={"location_code": "BR-PN"},
            fulfillment_method="STANDARD",
            restock_qtys=[1],
        )
        assert scenario["order"]["status"] == "CONFIRMED"
        assert scenario["order"].get("promise_date") is None

    def test_sla_breach_flag_set_only_when_ready_late(self, api, admin_headers,
                                                      branch_manager_headers):
        """PRD §3.7: "Marking ready also adjudicates the service promise:
        `sla_breach` becomes true exactly when a `promise_date` was set and the
        logical-clock date at mark-ready is later than that promise."

        Design: Corner/calculations/sla_breach_flag_set_only_when_ready_late
        """
        customer = create_customer(
            account_number="SLA-1", credit_limit_cents=100000,
            primary_ship_to_state="OH",
        )
        item = create_item(sku="SLA-1", list_price_cents=100)
        branch = create_branch(location_code="BR-SLA", same_day_cutoff_minute=900)
        restock(branch["id"], item["id"], 2)
        set_clock("2026-08-01T14:00:00Z")
        order1 = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )
        order2 = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )
        validate_success(api.confirm_order(order1["id"], admin_headers))
        validate_success(api.confirm_order(order2["id"], admin_headers))

        readied1 = validate_success(
            api.mark_order_ready(order1["id"], branch_manager_headers)
        )
        assert readied1["promise_date"] == "2026-08-01"
        assert readied1["sla_breach"] is False

        set_clock("2026-08-02T09:00:00Z")
        readied2 = validate_success(
            api.mark_order_ready(order2["id"], branch_manager_headers)
        )
        assert readied2["promise_date"] == "2026-08-01"
        assert readied2["sla_breach"] is True


def _drop_ship_setup(api):
    """SPECIAL_ORDER drop-ship-eligible item, list 1,000, vendor cost estimate
    500/unit, freight estimate 100/line; no stock anywhere; STANDARD order qty 2."""
    customer = create_customer(
        account_number="DS-C", credit_limit_cents=1000000,
        primary_ship_to_state="TX",
    )
    item = create_item(
        sku="DS-1", item_class="SPECIAL_ORDER", list_price_cents=1000,
        drop_ship_eligible=True, vendor_cost_estimate_cents=500,
        vendor_freight_estimate_cents=100,
    )
    branch = create_branch(location_code="BR-2", region_state="TX")
    order = place_order(
        customer["id"], branch["id"], [{"item_id": item["id"], "qty": 2}],
        fulfillment_method="STANDARD",
    )
    validate_success(api.confirm_order(order["id"], ADMIN), 200)
    return customer, item, branch, order


class TestDropShipProvisionalVsFinalMargin:
    def test_confirm_sets_provisional_margin_from_estimates(self, api,
                                                            admin_headers):
        """PRD §3.6: "`provisional_margin_cents` is the drop-shipped quantity
        times the snapshot `unit_price_cents`, minus the sum of that quantity
        times the item's `vendor_cost_estimate_cents` and the item's per-line
        `vendor_freight_estimate_cents`, and the line's `margin_status` moves from
        `NOT_APPLICABLE` to `PROVISIONAL`"
        PRD §3.6: "`DROP_SHIP_ONLY` when drop-ship alone covered it"

        Design: Difficulty/dual_variant_calc/drop_ship_provisional_vs_final_margin
        """
        _customer, _item, _branch, order = _drop_ship_setup(api)
        line = get_order_lines(order["id"])[0]
        assert line["qty_drop_ship"] == 2
        assert line["fulfillment_source"] == "DROP_SHIP_ONLY"
        # 2 * 1000 - (2 * 500 + 100) = 900
        assert line["provisional_margin_cents"] == 900
        assert line["margin_status"] == "PROVISIONAL"

    def test_vendor_confirm_actualizes_final_margin(self, api, admin_headers,
                                                    vendor_rep_headers):
        """PRD §3.7: "Each listed line records the vendor-supplied
        `vendor_cost_actual_cents` and `freight_actual_cents`, sets
        `qty_vendor_confirmed` equal to its `qty_drop_ship`, and actualizes its
        economics: `final_margin_cents` is the drop-shipped quantity times
        `unit_price_cents`, minus the sum of that quantity times
        `vendor_cost_actual_cents` and the line's `freight_actual_cents`, with
        `margin_status` advancing to `FINALIZED`."

        Design: Difficulty/dual_variant_calc/drop_ship_provisional_vs_final_margin
        """
        _customer, _item, _branch, order = _drop_ship_setup(api)
        line_id = get_order_lines(order["id"])[0]["id"]
        validate_success(
            api.vendor_confirm_order(
                order["id"],
                {"actual_costs": [
                    {"order_line_id": line_id, "vendor_cost_actual_cents": 450,
                     "freight_actual_cents": 150},
                ]},
                vendor_rep_headers,
            ),
            200,
        )
        line = get_order_lines(order["id"])[0]
        # 2 * 1000 - (2 * 450 + 150) = 950
        assert line["final_margin_cents"] == 950
        assert line["qty_vendor_confirmed"] == 2
        assert line["margin_status"] == "FINALIZED"


class TestDropShipFulfillmentGate:
    def test_drop_ship_unconfirmed_blocks_fulfillment(self, api, admin_headers,
                                                      branch_manager_headers,
                                                      vendor_rep_headers):
        """PRD §3.7: "It is gated on vendor settlement: any line whose
        `qty_drop_ship` exceeds its `qty_vendor_confirmed` blocks fulfillment with
        `ERR_DROP_SHIP_UNCONFIRMED`."

        Design: Corner/errors/drop_ship_unconfirmed_blocks_fulfillment
        """
        customer = create_customer(
            account_number="DU-1", credit_limit_cents=100000,
            primary_ship_to_state="OH",
        )
        item = create_item(
            sku="DU-1", list_price_cents=1000, drop_ship_eligible=True,
            vendor_cost_estimate_cents=500, vendor_freight_estimate_cents=100,
        )
        branch = create_branch(location_code="BR-DU")
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}],
            fulfillment_method="STANDARD",
        )
        validate_success(api.confirm_order(order["id"], admin_headers))
        readied = validate_success(
            api.mark_order_ready(order["id"], branch_manager_headers)
        )
        assert readied["fulfillment_status"] == "SHIPPED"
        line_id = get_order_lines(order["id"])[0]["id"]

        res = api.mark_order_fulfilled(order["id"], branch_manager_headers)
        validate_error(res, ApiErrorId.ERR_DROP_SHIP_UNCONFIRMED)

        validate_success(
            api.vendor_confirm_order(
                order["id"],
                {"actual_costs": [
                    {"order_line_id": line_id, "vendor_cost_actual_cents": 500,
                     "freight_actual_cents": 100},
                ]},
                vendor_rep_headers,
            ),
            200,
        )
        fulfilled = validate_success(
            api.mark_order_fulfilled(order["id"], branch_manager_headers)
        )
        assert fulfilled["fulfillment_status"] == "FULFILLED"

    def test_vendor_lines_mismatch_rejected(self, api, admin_headers,
                                            vendor_rep_headers):
        """PRD §3.7: "A `VendorRep` confirms the order's drop-ship lines by
        submitting `actual_costs`, which must cover exactly the order's
        not-yet-confirmed drop-ship lines — no more, no fewer — with any other
        coverage rejected as `ERR_VENDOR_LINES_MISMATCH`."

        Design: Corner/errors/vendor_lines_mismatch_rejected
        """
        customer = create_customer(
            account_number="VM-1", credit_limit_cents=100000,
            primary_ship_to_state="OH",
        )
        item = create_item(
            sku="VM-1", list_price_cents=1000, drop_ship_eligible=True,
            vendor_cost_estimate_cents=500, vendor_freight_estimate_cents=100,
        )
        branch = create_branch(location_code="BR-VM")
        order = place_order(
            customer["id"], branch["id"], [{"item_id": item["id"], "qty": 1}],
            fulfillment_method="STANDARD",
        )
        validate_success(api.confirm_order(order["id"], admin_headers))

        res = api.vendor_confirm_order(
            order["id"], {"actual_costs": []}, vendor_rep_headers
        )
        validate_error(res, ApiErrorId.ERR_VENDOR_LINES_MISMATCH)
