"""Three quantities that must return to exactly where they started once the
compensating operation runs: core-deposit money, physical inventory units, and the
catalog's total list price."""
from test_helpers import (
    PRICING_ADMIN,
    add_line,
    add_price_file_line,
    allocate_order,
    api_client,
    approve_credit,
    assert_catalog_list_price_sum,
    assert_inventory_units,
    assert_order_money,
    cancel_line,
    decide_return,
    inventory_for,
    list_parts,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_inventory,
    make_part,
    make_price_file,
    make_pricing_tier,
    open_will_call_order,
    read_account,
    read_line,
    read_order,
    read_part,
    read_price_file,
    read_price_file_line,
    read_return_authorization,
    request_return,
    rollback_price_file,
    setup_fulfilled_line,
    validate_success,
)

COMPRESSOR = {
    "part_number": "W10-COMP",
    "oem_code": "WHIRLPOOL",
    "description": "Sealed system compressor",
    "category": "SEALED_SYSTEM",
    "list_price_cents": 320000,
    "weight_grams": 12000,
    "core_required": True,
    "core_deposit_cents": 8500,
}
PUMP = {
    "part_number": "W10-PUMP",
    "oem_code": "WHIRLPOOL",
    "description": "Drain pump assembly",
    "category": "MECHANICAL",
    "list_price_cents": 12999,
    "weight_grams": 5200,
}
MOTOR = {
    "part_number": "W10-MOTOR",
    "oem_code": "WHIRLPOOL",
    "description": "Drive motor",
    "category": "MECHANICAL",
    "list_price_cents": 128000,
    "weight_grams": 9000,
}


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _two_shipped_compressors_with_an_approved_core_return():
    """Two core-required compressors shipped on 2026-08-01, carrying 17,000 cents
    of deposit, with a same-day CORE_RETURN authorization already approved."""
    world = setup_fulfilled_line(
        quantity=2,
        on_hand_units=5,
        part_kwargs=dict(COMPRESSOR),
        account_kwargs={
            "business_name": "Core Exchange Service",
            "core_liability_limit_cents": 5000000,
        },
        cert_kwargs={
            "technician_name": "Sam Ortiz",
            "oem_code": "WHIRLPOOL",
            "cert_level": "SEALED_SYSTEM",
        },
        tracking_ref="WILLCALL-CORE",
    )
    world["return_authorization"] = request_return(
        world["account"], world["line"], 2, "CORE_RETURN", world["branch"]
    )
    decide_return(
        world["return_authorization"]["id"], "APPROVE", waive_restocking_fee=False
    )
    return world


def _allocated_order_with_a_pump_line_and_a_motor_line():
    """An allocated will-call order holding three pumps at one branch position and
    one motor at another."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    branch = make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )
    pump = make_part(**PUMP)
    motor = make_part(**MOTOR)
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_inventory(branch, pump, on_hand_units=10, reorder_point=2)
    make_inventory(branch, motor, on_hand_units=10, reorder_point=2)

    order = open_will_call_order(account, branch)
    pump_line = add_line(order, pump, quantity=3)
    motor_line = add_line(order, motor, quantity=1)
    approve_credit(order)
    allocate_order(order, branch)
    return {
        "branch": branch, "pump": pump, "motor": motor, "account": account,
        "order": order, "pump_line": pump_line, "motor_line": motor_line,
    }


def _two_part_catalog_and_a_draft_increase():
    """A catalog of exactly two parts summing to 140,999 cents, plus a draft price
    file that would lift the pump to 17,999."""
    pump = make_part(**PUMP)
    motor = make_part(**MOTOR)
    price_file = make_price_file(20260801, effective_at="2026-08-01T00:00:00Z")
    price_file_line = add_price_file_line(price_file, pump, 17999)
    return {
        "pump": pump, "motor": motor,
        "price_file": price_file, "price_file_line": price_file_line,
    }


# ---------------------------------------------------------------------------
# Core-deposit money
# ---------------------------------------------------------------------------

class TestCoreDepositLiabilityIsConserved:

    def test_a_full_core_return_drives_the_liability_back_to_zero(self):
        """PRD §3.6: "**Core liability** is maintained as its own account-level
        aggregate. It is the sum, over the account's lines whose `line_status` is
        `SHIPPED` or `RETURNED` and whose resolved part has `core_required` true, of
        the line's `core_deposit_cents` multiplied by its `quantity`, minus the sum
        of `core_deposit_refund_cents` over the account's return authorizations whose
        `ra_status` is `CREDITED` and whose `reason_code` is `CORE_RETURN`. Because
        the refund is computed from the line's snapshotted deposit rather than the
        part's current one, a part shipped with a deposit and later core-returned in
        full brings the account's `core_liability_cents` back to exactly its
        pre-shipment value, and a price file that changes the deposit in between
        cannot break that."
        PRD §3.9: "Separately, `core_deposit_refund_cents` is the line's snapshotted
        `core_deposit_cents` multiplied by the authorization's `quantity` when the
        `reason_code` is `CORE_RETURN`, and 0 otherwise — so a core return has a zero
        gross, a zero fee, a zero credit, and a non-zero deposit refund."

        Design: Difficulty/compensating_invariant/core_deposit_liability_returns_to_zero_after_a_full_core_return
        """
        world = _two_shipped_compressors_with_an_approved_core_return()

        before = read_account(world["account"]["id"])
        assert before["core_liability_cents"] == 17000, (
            f"Expected 8500 x 2 of deposit charged at shipment, got "
            f"{before['core_liability_cents']}"
        )
        order = read_order(world["order"]["id"])
        assert order["core_deposit_total_cents"] == 17000
        assert order["invoiced_total_cents"] == 593000, (
            f"Expected 576000 of goods plus 17000 of deposits, got "
            f"{order['invoiced_total_cents']}"
        )

        ra = read_return_authorization(world["return_authorization"]["id"])
        assert ra["gross_return_cents"] == 0
        assert ra["restocking_fee_cents"] == 0
        assert ra["credit_amount_cents"] == 0
        assert ra["core_deposit_refund_cents"] == 17000, (
            f"Expected the snapshotted 8500 x 2, got "
            f"{ra['core_deposit_refund_cents']}"
        )

        response = api_client.receive_return_authorization(
            world["return_authorization"]["id"],
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_success(response, 200)

        assert read_return_authorization(
            world["return_authorization"]["id"]
        )["ra_status"] == "CREDITED"

        after = read_account(world["account"]["id"])
        assert after["core_liability_cents"] == 0, (
            f"the full core return releases the whole deposit, got "
            f"{after['core_liability_cents']}"
        )

    def test_the_deposit_release_moves_neither_the_goods_nor_the_exposure(self):
        """PRD §3.9: "It stamps `received_at` with the logical clock and restocks
        conditionally: `WRONG_PART` and `NO_LONGER_NEEDED` raise `on_hand_units` at
        the receiving branch's position for the resolved part by the authorization's
        `quantity`, creating that branch-and-part position with `on_hand_units` equal
        to the quantity if none exists; `DEFECTIVE_ON_ARRIVAL` does not restock,
        because the unit is scrapped; and `CORE_RETURN` does not restock either,
        because the core ships onward to the OEM."
        PRD §3.9: "For a non-core reason, the line's `returned_units` rises by the
        authorization's `quantity`, and when `returned_units` reaches the line's full
        `quantity` the line moves `SHIPPED → RETURNED`; a partial return leaves the
        line in `SHIPPED` with `returned_units` below `quantity`."
        PRD §3.5: "Then compute the credits as the sum of `credit_amount_cents` over
        the account's return authorizations whose `ra_status` is `CREDITED`, plus the
        sum of `credit_amount_cents` over the account's warranty claims whose
        `claim_status` is `CREDITED`."

        Design: Difficulty/compensating_invariant/core_deposit_liability_returns_to_zero_after_a_full_core_return
        """
        world = _two_shipped_compressors_with_an_approved_core_return()
        validate_success(
            api_client.receive_return_authorization(
                world["return_authorization"]["id"],
                make_branch_counter_rep_headers(world["branch"]["id"]),
            ),
            200,
        )

        line = read_line(world["line"]["id"])
        assert line["line_status"] == "SHIPPED", (
            f"a core return is not a goods return, got {line['line_status']}"
        )
        assert line["returned_units"] == 0

        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=3, reserved=0, available=3)

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 593000, (
            f"a zero credit amount leaves the invoiced exposure alone, got "
            f"{account['credit_used_cents']}"
        )


# ---------------------------------------------------------------------------
# Inventory units
# ---------------------------------------------------------------------------

class TestInventoryUnitsAreConserved:

    def test_cancelling_an_allocated_line_returns_availability_to_its_prior_value(self):
        """PRD §2.9: "First, **inventory unit conservation**: whenever a reservation
        is released — by a line cancellation, an order cancellation, a credit freeze,
        an obsolescence cascade, or an account suspension — the affected inventory
        record's `reserved_units` falls by exactly the line quantity that had been
        reserved, and its `available_units` returns to exactly its pre-allocation
        value."
        PRD §3.4: "If it had been `ALLOCATED`, its reservation is compensated
        exactly: the holding inventory record's `reserved_units` falls by the line's
        `quantity`, its `available_units` returns to the value it had before the
        allocation, and the line's `allocation_branch_id` is cleared to null."
        PRD §3.3: "The metric allocation actually consults is `available_units`,
        which is always `on_hand_units` minus `reserved_units`."

        Design: Difficulty/compensating_invariant/inventory_units_are_conserved_when_an_allocated_line_is_cancelled
        """
        world = _allocated_order_with_a_pump_line_and_a_motor_line()

        before = inventory_for(world["branch"]["id"], world["pump"]["id"])
        assert_inventory_units(before, on_hand=10, reserved=3, available=7)

        cancel_line(world["pump_line"], world["order"], "servicer sourced it locally")

        line = read_line(world["pump_line"]["id"])
        assert line["line_status"] == "CANCELLED"
        assert line["allocation_branch_id"] is None

        after = inventory_for(world["branch"]["id"], world["pump"]["id"])
        assert_inventory_units(after, on_hand=10, reserved=0, available=10)
        assert after["on_hand_units"] == before["on_hand_units"], (
            "a cancellation moves no physical stock at all"
        )

    def test_the_sibling_reservation_and_the_recomputed_totals_are_left_intact(self):
        """PRD §3.4: "The order's `subtotal_cents`, `freight_cents`, and
        `total_cents` are then recomputed, followed by the account's
        `credit_used_cents`, and both the line's and the order's `version`
        increment."
        PRD §2.9: "Implementers should not generalise a cascade beyond the rows the
        relevant subsection names."

        Design: Difficulty/compensating_invariant/inventory_units_are_conserved_when_an_allocated_line_is_cancelled
        """
        world = _allocated_order_with_a_pump_line_and_a_motor_line()
        assert_order_money(
            read_order(world["order"]["id"]),
            subtotal=133597, freight=0, total=133597,
        )

        cancel_line(world["pump_line"], world["order"], "servicer sourced it locally")

        motor_stock = inventory_for(world["branch"]["id"], world["motor"]["id"])
        assert_inventory_units(motor_stock, on_hand=10, reserved=1, available=9)
        assert read_line(world["motor_line"]["id"])["line_status"] == "ALLOCATED"

        order = read_order(world["order"]["id"])
        assert_order_money(order, subtotal=102400, freight=0, total=102400)
        assert order["fulfillment_status"] == "ALLOCATED", (
            f"one surviving allocated line keeps the order allocated, got "
            f"{order['fulfillment_status']}"
        )

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 102400, (
            f"Expected the exposure to follow the recomputed total, got "
            f"{account['credit_used_cents']}"
        )


# ---------------------------------------------------------------------------
# Catalog list-price sum
# ---------------------------------------------------------------------------

class TestCatalogPriceSumIsConserved:

    def test_publication_lifts_the_catalog_sum_and_records_the_prior_price(self):
        """PRD §3.7: "In the first hop, every line snapshots the part's current
        values into `previous_list_price_cents`, `previous_core_deposit_cents`, and
        `previous_lifecycle_status`, then writes `new_list_price_cents` into the
        part's `list_price_cents`, writes `new_core_deposit_cents` into its
        `core_deposit_cents` where supplied, and writes `new_lifecycle_status` into
        its `lifecycle_status` where supplied, incrementing the part's `version`."
        PRD §3.7: "Three snapshot columns — `previous_list_price_cents`,
        `previous_core_deposit_cents`, and `previous_lifecycle_status` — stay null
        until publication."

        Design: Difficulty/compensating_invariant/catalog_list_price_sum_is_restored_by_a_price_file_rollback
        """
        world = _two_part_catalog_and_a_draft_increase()
        assert_catalog_list_price_sum(list_parts(), 140999)

        validate_success(
            api_client.publish_price_file(world["price_file"]["id"], PRICING_ADMIN),
            200,
        )

        assert read_price_file(
            world["price_file"]["id"]
        )["price_file_status"] == "PUBLISHED"
        assert read_part(world["pump"]["id"])["list_price_cents"] == 17999

        price_file_line = read_price_file_line(world["price_file_line"]["id"])
        assert price_file_line["previous_list_price_cents"] == 12999
        assert price_file_line["previous_lifecycle_status"] == "ACTIVE"

        assert_catalog_list_price_sum(list_parts(), 145999)

    def test_rollback_restores_the_catalog_sum_to_exactly_its_prior_value(self):
        """PRD §2.9: "Second, **catalog price conservation**: rolling back a
        published price file restores every part it touched to its pre-publication
        list price, core deposit, and lifecycle status, so the sum of
        `list_price_cents` across the whole catalog returns to its pre-publication
        value."
        PRD §3.7: "Rollback replays each line's snapshot back onto its part,
        restoring `list_price_cents`, `core_deposit_cents`, and `lifecycle_status`
        and incrementing the part's `version`; moves every substitute request this
        file created from `PENDING` to `WITHDRAWN` and its line from
        `SUBSTITUTE_PENDING` back to `RESOLVED`; releases every order this
        publication had put on hold from `HELD` back to `ALLOCATED` with a
        re-allocation sweep and recomputed totals; and returns every file this
        publication had auto-closed to `PUBLISHED` with its `effective_until` set
        back to null."
        PRD §3.7: "As stated in §2.9, the catalog's total list price is conserved
        across a publish-then-rollback pair."

        Design: Difficulty/compensating_invariant/catalog_list_price_sum_is_restored_by_a_price_file_rollback
        """
        world = _two_part_catalog_and_a_draft_increase()
        validate_success(
            api_client.publish_price_file(world["price_file"]["id"], PRICING_ADMIN),
            200,
        )
        assert_catalog_list_price_sum(list_parts(), 145999)

        rollback_price_file(world["price_file"]["id"], "OEM withdrew the increase")

        assert read_price_file(
            world["price_file"]["id"]
        )["price_file_status"] == "ROLLED_BACK"

        pump = read_part(world["pump"]["id"])
        assert pump["list_price_cents"] == 12999, (
            f"the snapshot is replayed back onto the part, got "
            f"{pump['list_price_cents']}"
        )
        assert pump["lifecycle_status"] == "ACTIVE"

        assert read_part(world["motor"]["id"])["list_price_cents"] == 128000, (
            "the untouched part never moves"
        )

        assert_catalog_list_price_sum(list_parts(), 140999)
