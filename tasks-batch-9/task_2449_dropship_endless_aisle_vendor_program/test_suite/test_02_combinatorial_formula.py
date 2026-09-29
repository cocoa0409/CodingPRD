"""Multi-term money formulas whose evaluation order is part of the contract.

Covers the per-unit rounding point in commission cost derivation and the order
rollup built on it, and the restocking-fee tier that is keyed on the pre-fee refund
base rather than on the refund it helps produce.
"""

from typing import Any, Dict

from test_helpers import (
    CARE,
    MM,
    ApiClient,
    create_active_vendor,
    create_item_payload,
    create_order_payload,
    get_success_data,
    open_return,
    order_line_input,
    order_lines_of,
    refresh_item,
    refresh_order,
    refresh_vendor,
    setup_shipped_line,
    setup_vendor_with_active_offer,
    validate_success,
)

# An offer priced at 1999 cents at a commission of 1500 basis points.
LAMP_OVERRIDES = {"sku": "SKU-LAMP-9", "unit_retail_cents": 1999}

# An offer priced at 20500 cents, which lands in the top restocking-fee band.
DESK_OVERRIDES = {"sku": "SKU-DESK-4", "unit_retail_cents": 20500}


def _shipped_desk_line(api: ApiClient, suffix: str, order_ref: str) -> Dict[str, Any]:
    """One shipped unit of the 20500-cent offer, shipped on 2026-08-04.

    The clock stays on the ship date, so the return sits well inside the offer's
    thirty-day defect window.
    """
    return setup_shipped_line(
        api,
        quantity=1,
        order_ref=order_ref,
        suffix=suffix,
        ship_at="2026-08-04T10:00:00Z",
        item_overrides=DESK_OVERRIDES,
        on_hand_units=10,
    )


# ─── Cost derivation: rounding once, at the per-unit stage ───


def test_commission_offer_unit_cost_rounds_half_up_at_the_per_unit_figure(api):
    """PRD §3.3: "For a `COMMISSION` vendor, the offer's `unit_cost_cents` is the offer's `unit_retail_cents` multiplied by the quantity 10000 minus the vendor's `commission_rate_bps`, divided by 10000, with the result rounded half up to a whole cent; `unit_wholesale_cost_cents` plays no part whatsoever."

    1999 cents at 8500 remaining basis points is 1699.15 cents, which rounds half up
    to 1699. The figure is derived at creation and derived again at activation.

    Design: Difficulty/combinatorial_formula/per_unit_rounding_before_multiplication_pins_line_cost
    """
    vendor = create_active_vendor(api, suffix="RDA")

    created = validate_success(
        api.create_item(create_item_payload(vendor["id"], **LAMP_OVERRIDES), MM), 201
    )
    assert created["unit_retail_cents"] == 1999
    assert created["unit_cost_cents"] == 1699

    activated = validate_success(api.activate_item(created["id"], MM))
    assert activated["status"] == "ACTIVE"
    assert activated["unit_cost_cents"] == 1699
    assert refresh_item(api, created["id"])["unit_cost_cents"] == 1699


def test_order_cost_multiplies_the_rounded_unit_cost_by_the_line_quantity(api):
    """PRD §2.7: "Consider an offer whose `unit_retail_cents` is 1999 at a vendor commission of 1500 basis points, ordered in a quantity of four: rounding per unit first yields 1699 cents per unit and 6796 cents extended, while multiplying first and rounding the total would yield 6797."

    Transmission pins the offer's already-rounded 1699 onto the line, so the order's
    cost is four times 1699. The forbidden ordering, multiplying 1999 by 8500 basis
    points by four and rounding the 6796.60 total, would report 6797.

    Design: Difficulty/combinatorial_formula/per_unit_rounding_before_multiplication_pins_line_cost
    """
    base = setup_vendor_with_active_offer(
        api, suffix="RDB", item_overrides=LAMP_OVERRIDES, on_hand_units=20
    )
    order = get_success_data(
        api.create_order(
            create_order_payload(
                "ORD-ROUND-1", [order_line_input(base["item_id"], 4)]
            ),
            CARE,
        )
    )

    validate_success(api.transmit_order(order["id"], MM))

    line = order_lines_of(api, order["id"])[0]
    assert line["unit_cost_cents"] == 1699
    assert line["surcharge_cents"] == 0

    after = refresh_order(api, order["id"])
    assert after["total_retail_cents"] == 7996
    assert after["total_cost_cents"] == 6796
    assert after["total_cost_cents"] != 6797
    assert after["margin_cents"] == 1200


def test_untransmitted_order_reports_zero_cost_and_margin_equal_to_retail(api):
    """PRD §3.5: "Because an untransmitted line's cost and surcharge are both 0 — no vendor and no coverage row have been pinned yet — a freshly placed order reports `total_cost_cents` of 0 and `margin_cents` equal to its `total_retail_cents`, and only transmission turns that into a real margin."

    The offer already carries its rounded 1699 unit cost, but the line does not: a
    freshly placed four-unit order shows 7996 of retail against no cost at all.

    Design: Difficulty/combinatorial_formula/per_unit_rounding_before_multiplication_pins_line_cost
    """
    base = setup_vendor_with_active_offer(
        api, suffix="RDC", item_overrides=LAMP_OVERRIDES, on_hand_units=20
    )
    assert refresh_item(api, base["item_id"])["unit_cost_cents"] == 1699

    order = validate_success(
        api.create_order(
            create_order_payload(
                "ORD-ROUND-2", [order_line_input(base["item_id"], 4)]
            ),
            CARE,
        ),
        201,
    )
    assert order["total_retail_cents"] == 7996
    assert order["total_cost_cents"] == 0
    assert order["margin_cents"] == 7996

    line = order_lines_of(api, order["id"])[0]
    assert line["status"] == "PENDING_TRANSMIT"
    assert line["unit_retail_cents"] == 1999
    assert line["unit_cost_cents"] == 0
    assert line["surcharge_cents"] == 0


# ─── The refund waterfall: the fee tier reads the pre-fee base ───


def test_restocking_fee_tier_is_keyed_on_the_pre_fee_refund_base(api):
    """PRD §3.8: "The fee tier is keyed on the **pre-fee** `refund_base_cents` and never on `refund_cents`, which is what makes the apparent circularity — the refund depends on the fee, the fee tier depends on an amount — well defined."

    A base of 20500 cents sits in the top band at 1000 basis points, so the fee is
    2050 and the refund 17155. Reading the tier off that 17155 refund instead would
    drop the fee to the 500-basis-point band and charge 1025.

    Design: Difficulty/combinatorial_formula/return_fee_tier_keyed_on_pre_fee_base_not_on_refund
    """
    state = _shipped_desk_line(api, "RFA", "ORD-FEE-1")
    ra = open_return(
        api, state["line_id"], quantity_returned=1, reason_code="BUYER_REMORSE"
    )
    assert ra["status"] == "REQUESTED"

    authorized = validate_success(api.authorize_return(ra["id"], CARE))

    assert authorized["status"] == "AUTHORIZED"
    assert authorized["refund_base_cents"] == 20500
    assert authorized["restocking_fee_cents"] == 2050
    assert authorized["restocking_fee_cents"] != 1025
    assert authorized["reverse_freight_owner"] == "RETAILER"
    assert authorized["customer_freight_charge_cents"] == 1295
    assert authorized["refund_cents"] == 17155


def test_vendor_routed_return_charges_back_the_frozen_unit_cost_as_a_matched_pair(api):
    """PRD §3.8: "Step seven sets `vendor_chargeback_cents` to 0 when `routing_destination` is `RETAILER_DC`, and otherwise to `quantity_returned` multiplied by the line's frozen `unit_cost_cents`, increased by a further 1295 cents when `reverse_freight_owner` is `VENDOR`."

    The sourcing vendor is eligible to take the goods back, so one unit is charged
    back at the line's frozen 17425 and no reverse freight is added because the
    retailer owns it. The posting is a matched pair, so the shipment's 17425 of
    settlement lands back at zero.

    Design: Difficulty/combinatorial_formula/return_fee_tier_keyed_on_pre_fee_base_not_on_refund
    """
    state = _shipped_desk_line(api, "RFB", "ORD-FEE-2")
    assert state["line"]["unit_cost_cents"] == 17425
    assert refresh_vendor(api, state["vendor_id"])["settlement_balance_cents"] == 17425

    ra = open_return(
        api, state["line_id"], quantity_returned=1, reason_code="BUYER_REMORSE"
    )
    authorized = validate_success(api.authorize_return(ra["id"], CARE))

    assert authorized["routing_destination"] == "VENDOR"
    assert authorized["routed_vendor_id"] == state["vendor_id"]
    assert authorized["restock_disposition"] == "VENDOR_RESTOCK"
    assert authorized["vendor_chargeback_cents"] == 17425

    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["chargeback_balance_cents"] == 17425
    assert vendor["settlement_balance_cents"] == 0
    assert (
        vendor["settlement_balance_cents"] + vendor["chargeback_balance_cents"] == 17425
    )

    order = refresh_order(api, state["order_id"])
    assert order["refunded_cents"] == 17155
    assert order["net_retail_cents"] == 3345
    assert order["financial_status"] == "PARTIALLY_REFUNDED"
    assert order["retailer_absorbed_cents"] == 0


def test_defective_return_waives_the_fee_and_moves_reverse_freight_to_the_vendor(api):
    """PRD §3.8: "Step three sets `restocking_fee_cents` to 0 whenever the `reason_code` is `DEFECTIVE`, `NOT_AS_DESCRIBED` or `LATE_DELIVERY` — the three reasons that waive the fee, because none of them is the customer's fault — and otherwise to the base multiplied by that fee rate, divided by 10000, rounded half up to a whole cent."

    The identical 20500-cent base still lands in the top fee band, but a defect
    waives the fee outright, moves reverse freight onto the vendor so the customer
    is charged nothing, and refunds the whole base. The vendor's chargeback picks up
    the 1295 of freight on top of the frozen 17425 of cost.

    Design: Difficulty/combinatorial_formula/return_fee_tier_keyed_on_pre_fee_base_not_on_refund
    """
    state = _shipped_desk_line(api, "RFC", "ORD-FEE-3")
    ra = open_return(
        api, state["line_id"], quantity_returned=1, reason_code="DEFECTIVE"
    )

    authorized = validate_success(api.authorize_return(ra["id"], CARE))

    assert authorized["refund_base_cents"] == 20500
    assert authorized["restocking_fee_cents"] == 0
    assert authorized["reverse_freight_owner"] == "VENDOR"
    assert authorized["customer_freight_charge_cents"] == 0
    assert authorized["refund_cents"] == 20500
    assert authorized["vendor_chargeback_cents"] == 18720

    vendor = refresh_vendor(api, state["vendor_id"])
    assert vendor["chargeback_balance_cents"] == 18720
    assert vendor["settlement_balance_cents"] == -1295
    assert (
        vendor["settlement_balance_cents"] + vendor["chargeback_balance_cents"] == 17425
    )

    order = refresh_order(api, state["order_id"])
    assert order["refunded_cents"] == 20500
    assert order["net_retail_cents"] == 0
    assert order["financial_status"] == "REFUNDED"
