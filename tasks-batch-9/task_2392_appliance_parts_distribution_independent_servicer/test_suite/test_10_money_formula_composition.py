"""Multi-input money formulas: per-unit rounding before the quantity multiply,
the restocking-fee tier keyed on the gross amount, and the four freight buckets."""
import pytest

from test_helpers import (
    CREDIT_MANAGER,
    add_line,
    allocate_order,
    api_client,
    approve_credit,
    assert_order_money,
    assert_inventory_units,
    assert_restocking_split_reconstitutes_gross,
    fulfill_order,
    inventory_for,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_inventory,
    make_part,
    make_pricing_tier,
    open_drop_ship_order,
    open_will_call_order,
    read_account,
    read_line,
    read_order,
    read_return_authorization,
    request_return,
    set_clock,
    validate_success,
)

PUMP_LIST_PRICE_CENTS = 12999
MOTOR_LIST_PRICE_CENTS = 128000


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _gold_account_with_two_mechanical_parts():
    """A GOLD account (20% mechanical) plus a part whose discounted unit price
    lands on a fraction of a cent and one whose lands exactly on the cent."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    pump = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=PUMP_LIST_PRICE_CENTS, weight_grams=5200,
    )
    motor = make_part(
        part_number="W10-MOTOR", oem_code="WHIRLPOOL", description="Drive motor",
        category="MECHANICAL", list_price_cents=MOTOR_LIST_PRICE_CENTS,
        weight_grams=9000,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    order = open_will_call_order(account, branch)
    line_pump = add_line(order, pump, quantity=3)
    line_motor = add_line(order, motor, quantity=1)
    return {
        "branch": branch, "pump": pump, "motor": motor, "account": account,
        "order": order, "line_pump": line_pump, "line_motor": line_motor,
    }


def _shipped_motor_line_returned_on_day_twenty():
    """One 128,000-cent motor shipped on the default clock, then a WRONG_PART
    return raised twenty days later so the fee tier and the large-return adder
    both engage."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    motor = make_part(
        part_number="W10-MOTOR", oem_code="WHIRLPOOL", description="Drive motor",
        category="MECHANICAL", list_price_cents=MOTOR_LIST_PRICE_CENTS,
        weight_grams=9000,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_inventory(branch, motor, on_hand_units=5, reorder_point=1)

    order = open_will_call_order(account, branch)
    line = add_line(order, motor, quantity=1)
    approve_credit(order)
    allocate_order(order, branch)
    fulfill_order(order, branch, tracking_ref="WILLCALL-M1")

    set_clock("2026-08-21T00:00:00Z")
    ra = request_return(account, line, 1, "WRONG_PART", branch)
    return {
        "branch": branch, "motor": motor, "account": account,
        "order": order, "line": line, "return_authorization": ra,
    }


def _credit_approved_overnight_order():
    """Three 5,200-gram pumps, credit approved, awaiting an allocation sweep out
    of a branch whose overnight surcharge is 100 cents and whose cutoff is 18."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="DAL", name="Dallas DC", region_code="SW",
        will_call_enabled=True, cutoff_hour_utc=18, overnight_surcharge_cents=100,
    )
    pump = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=PUMP_LIST_PRICE_CENTS, weight_grams=5200,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    inventory = make_inventory(branch, pump, on_hand_units=10, reorder_point=2)

    order = open_drop_ship_order(account, "63110")
    line = add_line(order, pump, quantity=3)
    approve_credit(order)
    return {
        "branch": branch, "pump": pump, "account": account,
        "inventory": inventory, "order": order, "line": line,
    }


# ---------------------------------------------------------------------------
# Rounding position inside the line-pricing formula
# ---------------------------------------------------------------------------

class TestLinePricingRoundsPerUnit:

    def test_fractional_unit_price_rounds_half_up_before_the_quantity_multiply(self):
        """PRD §3.4: "Multiply the part's `list_price_cents` by one minus the
        effective discount and round the result half up to a whole cent; that is
        the line's `unit_price_cents`. Multiply that rounded unit price by the
        `quantity`; that is the line's `extended_price_cents`."
        PRD §3.4: "Add a volume bonus of 0.02 when the line's `quantity` is ten
        units or more, and nothing at all when it is fewer than ten."

        Design: Difficulty/combinatorial_formula/line_pricing_rounds_per_unit_before_multiplying_mode_b
        """
        world = _gold_account_with_two_mechanical_parts()

        line = read_line(world["line_pump"]["id"])
        assert line["unit_price_cents"] == 10399, (
            f"12999 x 0.80 = 10399.2 must round half up to 10399, got "
            f"{line['unit_price_cents']}"
        )
        assert line["extended_price_cents"] == 31197, (
            f"Expected 10399 x 3 = 31197, got {line['extended_price_cents']}"
        )

        order = read_order(world["order"]["id"])
        assert order["subtotal_cents"] == 133597, (
            f"Expected subtotal 31197 + 102400 = 133597, got "
            f"{order['subtotal_cents']}"
        )
        assert order["subtotal_cents"] != 133598, (
            "133598 is the figure produced by discounting the extended amount "
            "instead of rounding the unit price first"
        )

    def test_order_totals_never_re_round_an_already_rounded_line_amount(self):
        """PRD §3.4: "Finally `total_cents` is `subtotal_cents` plus
        `core_deposit_total_cents` plus `freight_cents`. None of these sums
        re-rounds an already-rounded line amount."
        PRD §3.5: "Compute the open exposure by walking the account's orders and
        contributing, per order: `invoiced_total_cents` when `settlement_status`
        is `INVOICED`; `total_cents` when `settlement_status` is
        `PENDING_CREDIT` or `CREDIT_APPROVED` **and** `fulfillment_status` is
        `DRAFT`, `ALLOCATED`, or `HELD`; and nothing at all otherwise, which
        covers `PAID`, `CREDIT_DECLINED`, `WRITTEN_OFF`, and cancelled orders."

        Design: Difficulty/combinatorial_formula/line_pricing_rounds_per_unit_before_multiplying_mode_b
        """
        world = _gold_account_with_two_mechanical_parts()

        motor_line = read_line(world["line_motor"]["id"])
        assert motor_line["unit_price_cents"] == 102400, (
            f"128000 x 0.80 = 102400 exactly, got {motor_line['unit_price_cents']}"
        )
        assert motor_line["extended_price_cents"] == 102400

        order = read_order(world["order"]["id"])
        assert_order_money(order, subtotal=133597, freight=0, total=133597,
                           core_deposit_total=0)

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 133597, (
            f"Expected the draft order's total 133597 to be the whole open "
            f"exposure, got {account['credit_used_cents']}"
        )


# ---------------------------------------------------------------------------
# Restocking fee: every percentage keyed on the gross amount
# ---------------------------------------------------------------------------

class TestRestockingFeeKeyedOnGross:

    def test_large_return_adder_and_tier_both_read_the_gross_amount(self):
        """PRD §3.9: "Otherwise consult the pinned
        `days_since_fulfilled_at_request`: a count of 15 days or fewer gives a
        rate of 0.10, and a count above 15 gives 0.20. Then, if the
        authorization's `gross_return_cents` is at least 100,000 cents (one
        thousand dollars) **and** the rate so far is greater than zero, add 0.05
        to the rate — a large return costs the servicer an extra five points, but
        a rate already at zero stays at zero."
        PRD §3.9: "Every percentage in this rule is keyed on
        `gross_return_cents`, the amount **before** the fee is deducted; keying
        the large-return adder or the tier lookup on the post-fee credit would
        select a different branch and produce a different fee."

        Design: Difficulty/combinatorial_formula/restocking_fee_tier_keyed_on_gross_not_net_mode_c
        """
        world = _shipped_motor_line_returned_on_day_twenty()

        response = api_client.decide_return_authorization(
            world["return_authorization"]["id"],
            {
                "decision": "APPROVE",
                "waive_restocking_fee": False,
                "decision_note": "counter inspection passed",
            },
            CREDIT_MANAGER,
        )
        decided = validate_success(response, 200)
        assert decided["ra_status"] == "APPROVED"

        ra = read_return_authorization(world["return_authorization"]["id"])
        assert ra["days_since_fulfilled_at_request"] == 20, (
            f"Expected the pinned day count 20, got "
            f"{ra['days_since_fulfilled_at_request']}"
        )
        assert ra["gross_return_cents"] == 102400, (
            f"Expected gross 102400, got {ra['gross_return_cents']}"
        )
        assert ra["restocking_fee_pct"] == pytest.approx(0.25, abs=0.01), (
            f"Expected 0.20 for day 20 plus the 0.05 large-return adder, got "
            f"{ra['restocking_fee_pct']}"
        )
        assert ra["restocking_fee_cents"] == 25600, (
            f"Expected 102400 x 0.25 = 25600, got {ra['restocking_fee_cents']}"
        )
        assert ra["restocking_fee_cents"] != 20480, (
            "20480 is the fee produced when the adder is tested against the "
            "post-fee credit instead of the gross"
        )

    def test_fee_and_credit_reconstitute_the_gross_and_no_deposit_is_refunded(self):
        """PRD §3.9: "Multiply it by `gross_return_cents` and round half up to a
        whole cent to get `restocking_fee_cents`, then take `credit_amount_cents`
        as `gross_return_cents` minus `restocking_fee_cents` — an exact integer
        remainder, so fee plus credit always reconstitutes the gross exactly."
        PRD §3.9: "Separately, `core_deposit_refund_cents` is the line's
        snapshotted `core_deposit_cents` multiplied by the authorization's
        `quantity` when the `reason_code` is `CORE_RETURN`, and 0 otherwise — so
        a core return has a zero gross, a zero fee, a zero credit, and a non-zero
        deposit refund."

        Design: Difficulty/combinatorial_formula/restocking_fee_tier_keyed_on_gross_not_net_mode_c
        """
        world = _shipped_motor_line_returned_on_day_twenty()

        response = api_client.decide_return_authorization(
            world["return_authorization"]["id"],
            {
                "decision": "APPROVE",
                "waive_restocking_fee": False,
                "decision_note": "counter inspection passed",
            },
            CREDIT_MANAGER,
        )
        validate_success(response, 200)

        ra = read_return_authorization(world["return_authorization"]["id"])
        assert ra["credit_amount_cents"] == 76800, (
            f"Expected 102400 - 25600 = 76800, got {ra['credit_amount_cents']}"
        )
        assert_restocking_split_reconstitutes_gross(ra)
        assert ra["core_deposit_refund_cents"] == 0, (
            f"A WRONG_PART return refunds no deposit, got "
            f"{ra['core_deposit_refund_cents']}"
        )


# ---------------------------------------------------------------------------
# Overnight freight: four buckets composed at allocation
# ---------------------------------------------------------------------------

class TestOvernightFreightComposition:

    def test_freight_sums_base_weight_and_surcharge_buckets_without_the_late_bucket(self):
        """PRD §3.6: "The base bucket is a flat 1,495 cents. The weight bucket
        takes the shipment weight in grams, divides by 5,000 grams (five
        kilograms) to a **rounded-up** whole number of blocks, and charges 250
        cents per block. The surcharge bucket takes the distinct
        `allocation_branch_id` values of those same lines and charges the
        **largest** `overnight_surcharge_cents` among their branches — one truck
        per order, so the worst branch sets the price. The late bucket charges 500
        cents when the UTC hour of the logical clock is greater than or equal to
        the **smallest** `cutoff_hour_utc` among those same branches, and nothing
        otherwise."
        PRD §3.6: "Otherwise `freight_cents` is the sum of all four buckets."

        Design: Difficulty/combinatorial_formula/overnight_freight_composes_four_buckets_mode_a
        """
        world = _credit_approved_overnight_order()

        response = api_client.allocate_part_order(
            world["order"]["id"],
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        allocated = validate_success(response, 200)
        assert allocated["fulfillment_status"] == "ALLOCATED"

        order = read_order(world["order"]["id"])
        assert order["subtotal_cents"] == 31197, (
            f"Expected subtotal 31197, got {order['subtotal_cents']}"
        )
        assert order["freight_cents"] == 2595, (
            f"Expected 1495 base + 1000 for four 5kg blocks of 15600 grams + 100 "
            f"branch surcharge + 0 late = 2595, got {order['freight_cents']}"
        )
        assert_order_money(order, subtotal=31197, freight=2595, total=33792,
                           core_deposit_total=0)

    def test_allocation_reserves_the_units_that_carry_the_freight_weight(self):
        """PRD §3.6: "The shipment weight is the sum, over the order's lines whose
        `line_status` is `ALLOCATED` or `SHIPPED`, of the resolved part's
        `weight_grams` multiplied by the line's `quantity`; lines sitting in
        `BACKORDERED` or `SUBSTITUTE_PENDING` contribute neither weight nor branch
        surcharge."
        PRD §3.6: "Each line that finds a branch moves `RESOLVED → ALLOCATED`,
        records the winning branch as its `allocation_branch_id`, raises that
        inventory record's `reserved_units` by the line's `quantity`, has its
        `available_units` recomputed, and increments that inventory record's
        `version`."

        Design: Difficulty/combinatorial_formula/overnight_freight_composes_four_buckets_mode_a
        """
        world = _credit_approved_overnight_order()
        allocate_order(world["order"], world["branch"])

        line = read_line(world["line"]["id"])
        assert line["line_status"] == "ALLOCATED"
        assert line["allocation_branch_id"] == world["branch"]["id"], (
            f"Expected the line to hold stock at {world['branch']['id']}, got "
            f"{line['allocation_branch_id']}"
        )

        record = inventory_for(world["branch"]["id"], world["pump"]["id"])
        assert_inventory_units(record, on_hand=10, reserved=3, available=7)
