"""Multi-hop cascades: a price-file publication that obsoletes a part all the way
through to account exposure, and a return credit that lifts a credit freeze."""
from test_helpers import (
    PRICING_ADMIN,
    add_line,
    add_price_file_line,
    allocate_order,
    api_client,
    assert_same_instant,
    approve_credit,
    assert_inventory_units,
    fulfill_order,
    inventory_for,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_inventory,
    make_part,
    make_price_file,
    make_pricing_tier,
    open_will_call_order,
    patch_account,
    read_account,
    read_line,
    read_order,
    read_part,
    read_price_file_line,
    read_return_authorization,
    request_return,
    decide_return,
    list_substitute_requests,
    validate_success,
)


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _allocated_order_and_a_draft_obsoleting_price_file():
    """An allocated two-line order plus a draft price file that will turn the
    first line's part OBSOLETE at the same list price."""
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
        list_price_cents=12999, weight_grams=5200,
    )
    motor = make_part(
        part_number="W10-MOTOR", oem_code="WHIRLPOOL", description="Drive motor",
        category="MECHANICAL", list_price_cents=128000, weight_grams=9000,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    pump_stock = make_inventory(branch, pump, on_hand_units=10, reorder_point=2)
    motor_stock = make_inventory(branch, motor, on_hand_units=10, reorder_point=2)

    order = open_will_call_order(account, branch)
    pump_line = add_line(order, pump, quantity=1)
    motor_line = add_line(order, motor, quantity=1)
    approve_credit(order)
    allocate_order(order, branch)

    price_file = make_price_file(20260801, effective_at="2026-08-01T00:00:00Z")
    price_file_line = add_price_file_line(
        price_file, pump, 12999, new_lifecycle_status="OBSOLETE"
    )
    return {
        "branch": branch, "pump": pump, "motor": motor, "account": account,
        "order": order, "pump_line": pump_line, "motor_line": motor_line,
        "pump_stock": pump_stock, "motor_stock": motor_stock,
        "price_file": price_file, "price_file_line": price_file_line,
    }


def _frozen_account_with_an_approved_return():
    """A tight-limit account with one invoiced order and one order frozen by a
    CREDIT_HOLD, plus an approved no-longer-needed return against the first."""
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
        list_price_cents=12999, weight_grams=5200,
    )
    account = make_account(
        tier, business_name="Tight Credit Repairs",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=22000, core_liability_limit_cents=5000000,
    )
    make_inventory(branch, pump, on_hand_units=10, reorder_point=2)

    shipped_order = open_will_call_order(account, branch, purchase_order_ref="PO-O1")
    shipped_line = add_line(shipped_order, pump, quantity=1)
    approve_credit(shipped_order)
    allocate_order(shipped_order, branch)
    fulfill_order(shipped_order, branch, tracking_ref="WILLCALL-O1")

    frozen_order = open_will_call_order(account, branch, purchase_order_ref="PO-O2")
    frozen_line = add_line(frozen_order, pump, quantity=1)
    approve_credit(frozen_order)
    allocate_order(frozen_order, branch)

    patch_account(account["id"], account_status="CREDIT_HOLD")

    ra = request_return(account, shipped_line, 1, "NO_LONGER_NEEDED", branch)
    decide_return(ra["id"], "APPROVE", waive_restocking_fee=False)
    return {
        "branch": branch, "pump": pump, "account": account,
        "shipped_order": shipped_order, "shipped_line": shipped_line,
        "frozen_order": frozen_order, "frozen_line": frozen_line,
        "return_authorization": ra,
    }


# ---------------------------------------------------------------------------
# Publication cascade
# ---------------------------------------------------------------------------

class TestPublicationObsolescenceCascade:

    def test_publication_snapshots_the_part_then_pends_the_line_and_frees_its_reservation(self):
        """PRD §3.7: "In the first hop, every line snapshots the part's current
        values into `previous_list_price_cents`, `previous_core_deposit_cents`, and
        `previous_lifecycle_status`, then writes `new_list_price_cents` into the
        part's `list_price_cents`, writes `new_core_deposit_cents` into its
        `core_deposit_cents` where supplied, and writes `new_lifecycle_status` into
        its `lifecycle_status` where supplied, incrementing the part's `version`."
        PRD §3.7: "In the second hop, for every part whose `lifecycle_status` has
        just become `OBSOLETE`, every order line whose `resolved_part_id` is that
        part and whose `line_status` is `RESOLVED` or `ALLOCATED` moves to
        `SUBSTITUTE_PENDING`; a line that had been `ALLOCATED` releases its
        reservation, lowering the holding inventory record's `reserved_units` by
        the line's `quantity` and clearing its `allocation_branch_id` to null; and
        a `PENDING` substitute request is opened for each such line with `source`
        equal to `PRICE_FILE_OBSOLESCENCE` and `created_by_price_file_id` naming
        this file."

        Design: Difficulty/transitive_cascade/price_file_publish_obsoletes_part_holds_order_and_moves_exposure
        """
        world = _allocated_order_and_a_draft_obsoleting_price_file()

        response = api_client.publish_price_file(
            world["price_file"]["id"], PRICING_ADMIN
        )
        published = validate_success(response, 200)
        assert published["price_file_status"] == "PUBLISHED"
        assert_same_instant(
            published["published_at"], "2026-08-01T00:00:00Z", "published_at"
        )

        price_file_line = read_price_file_line(world["price_file_line"]["id"])
        assert price_file_line["previous_lifecycle_status"] == "ACTIVE"
        assert price_file_line["previous_list_price_cents"] == 12999

        assert read_part(world["pump"]["id"])["lifecycle_status"] == "OBSOLETE"

        line = read_line(world["pump_line"]["id"])
        assert line["line_status"] == "SUBSTITUTE_PENDING"
        assert line["allocation_branch_id"] is None

        requests = list_substitute_requests(
            created_by_price_file_id=world["price_file"]["id"]
        )
        assert len(requests) == 1, (
            f"the publication must open exactly one substitute request, got "
            f"{len(requests)}"
        )
        assert requests[0]["request_status"] == "PENDING"
        assert requests[0]["source"] == "PRICE_FILE_OBSOLESCENCE"
        assert requests[0]["order_line_id"] == world["pump_line"]["id"]

        stock = inventory_for(world["branch"]["id"], world["pump"]["id"])
        assert_inventory_units(stock, on_hand=10, reserved=0, available=10)

    def test_publication_holds_the_order_and_moves_exposure_leaving_other_lines_alone(self):
        """PRD §3.7: "In the third hop, each of those lines' orders moves
        `ALLOCATED → HELD` with `hold_reason` set to `SUBSTITUTE_PENDING`, and
        their `subtotal_cents` and `total_cents` are recomputed with the
        now-`SUBSTITUTE_PENDING` lines excluded. In the fourth hop, each of those
        orders' accounts has `credit_used_cents` recomputed."
        PRD §3.7: "What publication emphatically does **not** do is reprice
        existing order lines: every `unit_price_cents` already quoted stays exactly
        as it was, and only hand-over reprices, on the `SHIP_DATE` basis."

        Design: Difficulty/transitive_cascade/price_file_publish_obsoletes_part_holds_order_and_moves_exposure
        """
        world = _allocated_order_and_a_draft_obsoleting_price_file()
        validate_success(
            api_client.publish_price_file(world["price_file"]["id"], PRICING_ADMIN), 200
        )

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "HELD"
        assert order["hold_reason"] == "SUBSTITUTE_PENDING"
        assert order["subtotal_cents"] == 102400, (
            f"the pended pump line drops out, leaving the motor's 102400, got "
            f"{order['subtotal_cents']}"
        )
        assert order["total_cents"] == 102400

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 102400, (
            f"Expected exposure to follow the recomputed total, got "
            f"{account['credit_used_cents']}"
        )

        motor_line = read_line(world["motor_line"]["id"])
        assert motor_line["line_status"] == "ALLOCATED", (
            "the untouched line keeps its allocation"
        )
        assert motor_line["extended_price_cents"] == 102400
        motor_stock = inventory_for(world["branch"]["id"], world["motor"]["id"])
        assert_inventory_units(motor_stock, on_hand=10, reserved=1, available=9)


# ---------------------------------------------------------------------------
# Return-credit cascade
# ---------------------------------------------------------------------------

class TestReturnCreditCascade:

    def test_receipt_credits_the_authorization_and_returns_the_line(self):
        """PRD §3.9: "It stamps `received_at` with the logical clock and restocks
        conditionally: `WRONG_PART` and `NO_LONGER_NEEDED` raise `on_hand_units` at
        the receiving branch's position for the resolved part by the
        authorization's `quantity`, creating that branch-and-part position with
        `on_hand_units` equal to the quantity if none exists;
        `DEFECTIVE_ON_ARRIVAL` does not restock, because the unit is scrapped; and
        `CORE_RETURN` does not restock either, because the core ships onward to the
        OEM."
        PRD §3.9: "For a non-core reason, the line's `returned_units` rises by the
        authorization's `quantity`, and when `returned_units` reaches the line's
        full `quantity` the line moves `SHIPPED → RETURNED`; a partial return
        leaves the line in `SHIPPED` with `returned_units` below `quantity`."

        Design: Difficulty/transitive_cascade/return_credit_posting_releases_credit_hold_and_re_reserves_inventory
        """
        world = _frozen_account_with_an_approved_return()

        response = api_client.receive_return_authorization(
            world["return_authorization"]["id"],
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_success(response, 200)

        ra = read_return_authorization(world["return_authorization"]["id"])
        assert ra["ra_status"] == "CREDITED", (
            f"crediting happens in the very same request, got {ra['ra_status']}"
        )
        assert_same_instant(ra["received_at"], "2026-08-01T00:00:00Z", "received_at")
        assert ra["restocking_fee_cents"] == 1040, (
            f"Expected 10399 x 0.10 rounded half up to 1040, got "
            f"{ra['restocking_fee_cents']}"
        )
        assert ra["credit_amount_cents"] == 9359

        line = read_line(world["shipped_line"]["id"])
        assert line["returned_units"] == 1
        assert line["line_status"] == "RETURNED"

    def test_the_credit_lifts_the_freeze_and_the_sweep_re_reserves_the_held_order(self):
        """PRD §3.9: "Second, the account's `credit_used_cents` falls by
        `credit_amount_cents` and its `core_liability_cents` falls by
        `core_deposit_refund_cents`. Third, if the account's `account_status` is
        `CREDIT_HOLD` and its exposure has now fallen to or below the floor of
        `credit_limit_cents` multiplied by 0.90, the account moves
        `CREDIT_HOLD → ACTIVE`. Fourth, that release moves every order of the
        account sitting in `HELD` with `hold_reason` equal to `CREDIT_HOLD` back
        toward `ALLOCATED`. Fifth, the re-allocation sweep on those orders
        re-reserves branch inventory line by line, leaving lines that still find no
        stock in `BACKORDERED` and leaving orders where no line could reserve in
        `HELD` with `hold_reason` rewritten to `BACKORDER`."

        Design: Difficulty/transitive_cascade/return_credit_posting_releases_credit_hold_and_re_reserves_inventory
        """
        world = _frozen_account_with_an_approved_return()
        validate_success(
            api_client.receive_return_authorization(
                world["return_authorization"]["id"],
                make_branch_counter_rep_headers(world["branch"]["id"]),
            ),
            200,
        )

        account = read_account(world["account"]["id"])
        assert account["credit_used_cents"] == 11439, (
            f"Expected 10399 invoiced plus 10399 open minus the 9359 credit, got "
            f"{account['credit_used_cents']}"
        )
        assert account["account_status"] == "ACTIVE", (
            "11439 is at or below the floor of 22000 x 0.90, so the freeze lifts"
        )

        frozen_order = read_order(world["frozen_order"]["id"])
        assert frozen_order["fulfillment_status"] == "ALLOCATED"
        assert frozen_order["hold_reason"] is None

        frozen_line = read_line(world["frozen_line"]["id"])
        assert frozen_line["line_status"] == "ALLOCATED"
        assert frozen_line["allocation_branch_id"] == world["branch"]["id"]

        stock = inventory_for(world["branch"]["id"], world["pump"]["id"])
        assert_inventory_units(stock, on_hand=10, reserved=1, available=9)

        shipped_order = read_order(world["shipped_order"]["id"])
        assert shipped_order["settlement_status"] == "INVOICED", (
            "the return credit does not settle the invoice"
        )
