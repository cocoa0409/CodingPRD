"""The money arithmetic: which contract discount a category selects, where the
half-cent goes, how the discount cap bites, which branch wins a line, which lines
feed the freight buckets, and what a warranty claim locks in."""
from test_helpers import (
    WARRANTY_ADMIN,
    add_line,
    api_client,
    approve_credit,
    assert_inventory_units,
    assert_order_money,
    decide_return,
    inventory_for,
    make_account,
    make_branch,
    make_branch_counter_rep_headers,
    make_certification,
    make_claim,
    make_inventory,
    make_part,
    make_pricing_tier,
    make_servicer_headers,
    open_drop_ship_order,
    open_will_call_order,
    order_line_payload,
    read_claim,
    read_line,
    read_order,
    read_part,
    read_return_authorization,
    receive_return,
    record_supersession,
    request_return,
    set_clock,
    setup_fulfilled_line,
    validate_success,
)


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _gold_tier():
    return make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )


def _st_louis():
    return make_branch(
        code="STL", name="St Louis DC", region_code="MW",
        will_call_enabled=True, cutoff_hour_utc=20, overnight_surcharge_cents=300,
    )


def _dallas():
    return make_branch(
        code="DAL", name="Dallas DC", region_code="SW",
        will_call_enabled=True, cutoff_hour_utc=18, overnight_surcharge_cents=100,
    )


def _pump():
    return make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )


def _certified_ge_account_and_an_empty_order():
    """An account authorized for GE, holding an effective ADVANCED GE
    certification, with one empty will-call order and an electrical board."""
    tier = _gold_tier()
    branch = _st_louis()
    board = make_part(
        part_number="GE-BOARD", oem_code="GE", description="Main control board",
        category="ELECTRICAL", list_price_cents=128000, weight_grams=400,
    )
    account = make_account(
        tier, business_name="Board Repair Specialists",
        oem_authorizations=["GE"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_certification(
        account, technician_name="Lee Park", oem_code="GE", cert_level="ADVANCED",
        training_completed_at="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z",
    )
    return {
        "branch": branch, "part": board, "account": account,
        "order": open_will_call_order(account, branch, purchase_order_ref="PO-3001"),
    }


def _two_branches_holding_nine_and_four_units():
    """A credit-approved drop-ship order for three pumps with a deep expensive
    branch and a shallow cheap one competing for it."""
    tier = _gold_tier()
    deep = _st_louis()
    cheap = _dallas()
    pump = _pump()
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_inventory(deep, pump, on_hand_units=9, reorder_point=2)
    make_inventory(cheap, pump, on_hand_units=4, reorder_point=2)

    order = open_drop_ship_order(account, "63101", purchase_order_ref="PO-3002")
    line = add_line(order, pump, quantity=3)
    approve_credit(order)
    return {
        "deep": deep, "cheap": cheap, "part": pump, "account": account,
        "order": order, "line": line,
    }


def _drop_ship_order_with_one_stocked_and_one_unstocked_line():
    """A credit-approved drop-ship order whose second line has no inventory
    position anywhere and must therefore backorder."""
    tier = _gold_tier()
    branch = _dallas()
    pump = _pump()
    hose = make_part(
        part_number="W10-HOSE", oem_code="WHIRLPOOL", description="Fill hose",
        category="MECHANICAL", list_price_cents=2999, weight_grams=9000,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_inventory(branch, pump, on_hand_units=10, reorder_point=2)

    order = open_drop_ship_order(account, "75201", purchase_order_ref="PO-3003")
    stocked = add_line(order, pump, quantity=3)
    unstocked = add_line(order, hose, quantity=1)
    approve_credit(order)
    return {
        "branch": branch, "pump": pump, "hose": hose, "account": account,
        "order": order, "stocked": stocked, "unstocked": unstocked,
    }


def _two_drop_ship_orders_below_and_at_the_waiver():
    """Two drop-ship orders out of one late-cutoff branch, one quoted at 40,000
    cents and one landing exactly on the 50,000-cent free-freight threshold."""
    set_clock("2026-08-01T19:00:00Z")
    tier = _gold_tier()
    branch = _dallas()
    valve = make_part(
        part_number="W10-VALVE", oem_code="WHIRLPOOL",
        description="Inlet valve", category="MECHANICAL",
        list_price_cents=12500, weight_grams=5000,
    )
    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    make_inventory(branch, valve, on_hand_units=20, reorder_point=2)

    below = open_drop_ship_order(account, "75201", purchase_order_ref="PO-3006B")
    add_line(below, valve, quantity=4)
    approve_credit(below)

    at_threshold = open_drop_ship_order(
        account, "75201", purchase_order_ref="PO-3006A"
    )
    add_line(at_threshold, valve, quantity=5)
    approve_credit(at_threshold)
    return {
        "branch": branch, "part": valve, "account": account,
        "below": below, "at_threshold": at_threshold,
    }


def _two_hop_supersession_chain():
    """Three pumps wired A → B → C, with only C left ACTIVE."""
    tier = _gold_tier()
    branch = _st_louis()
    terminal = make_part(
        part_number="W10-PUMP-C", oem_code="WHIRLPOOL",
        description="Drain pump assembly rev C", category="MECHANICAL",
        list_price_cents=13000, weight_grams=5200,
    )
    middle = make_part(
        part_number="W10-PUMP-B", oem_code="WHIRLPOOL",
        description="Drain pump assembly rev B", category="MECHANICAL",
        list_price_cents=12500, weight_grams=5200,
    )
    original = make_part(
        part_number="W10-PUMP-A", oem_code="WHIRLPOOL",
        description="Drain pump assembly rev A", category="MECHANICAL",
        list_price_cents=12000, weight_grams=5200,
    )
    record_supersession(middle, terminal)
    record_supersession(original, middle)

    account = make_account(
        tier, business_name="Ace Appliance Repair",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    return {
        "branch": branch, "terminal": terminal, "middle": middle,
        "original": original, "account": account,
        "order": open_will_call_order(account, branch, purchase_order_ref="PO-3007"),
    }


def _three_shipped_units_with_one_already_credited_back():
    """Three pumps shipped and invoiced, one of them returned as a wrong part and
    credited, with a draft warranty claim standing against the line."""
    world = setup_fulfilled_line(
        quantity=3,
        branch_kwargs={
            "code": "STL", "name": "St Louis DC", "region_code": "MW",
            "will_call_enabled": True, "cutoff_hour_utc": 20,
            "overnight_surcharge_cents": 300,
        },
        on_hand_units=10,
        account_kwargs={"core_liability_limit_cents": 5000000},
        cert_kwargs={
            "technician_name": "Dana Ruiz",
            "oem_code": "WHIRLPOOL",
            "cert_level": "BASIC",
        },
        purchase_order_ref="PO-3008",
        tracking_ref="WILLCALL-3008",
    )
    ra = request_return(
        world["account"], world["line"], 1, "WRONG_PART", world["branch"]
    )
    decide_return(ra["id"], "APPROVE", waive_restocking_fee=False)
    receive_return(ra["id"], world["branch"])
    world["return_authorization"] = ra
    world["claim"] = make_claim(
        world["account"], world["line"], defect_code="PUMP-SEIZED",
        appliance_model_number="WTW5000DW1",
    )
    return world


# ---------------------------------------------------------------------------
# Which discount the category selects
# ---------------------------------------------------------------------------

class TestCategorySelectsTheContractDiscount:

    def test_an_electrical_line_prices_off_the_electrical_percentage(self):
        """PRD §3.4: "Select the base discount percentage from the tier by the
        part's `category`: `discount_pct_electrical` for `ELECTRICAL`,
        `discount_pct_mechanical` for `MECHANICAL`, `discount_pct_cosmetic` for
        `COSMETIC`, and `discount_pct_sealed_system` for `SEALED_SYSTEM`."
        PRD §3.4: "Multiply the part's `list_price_cents` by one minus the effective
        discount and round the result half up to a whole cent; that is the line's
        `unit_price_cents`."
        PRD §3.6: "A `WILL_CALL` order never carries freight at all: its
        `freight_cents` is zero, full stop, because the customer collects."

        Design: Corner/calculations/electrical_line_price_uses_the_electrical_contract_discount
        """
        world = _certified_ge_account_and_an_empty_order()

        response = api_client.add_order_line(
            world["order"]["id"],
            order_line_payload(world["part"]["id"], 1, world["order"]["version"]),
            make_servicer_headers(world["account"]["id"]),
        )
        line = validate_success(response, 201)

        assert line["unit_price_cents"] == 108800, (
            f"Expected 128000 x (1 - 0.15) on the electrical percentage, got "
            f"{line['unit_price_cents']}"
        )
        assert line["extended_price_cents"] == 108800
        assert line["line_status"] == "RESOLVED"

        assert_order_money(
            read_order(world["order"]["id"]),
            subtotal=108800, freight=0, total=108800,
        )


class TestDiscountCap:

    def test_the_volume_bonus_cannot_push_the_discount_past_forty_five_percent(self):
        """PRD §3.4: "Add a volume bonus of 0.02 when the line's `quantity` is ten
        units or more, and nothing at all when it is fewer than ten."
        PRD §3.4: "Take the smaller of that sum and 0.45 as the effective discount —
        no combination of contract discount and volume bonus may ever exceed
        forty-five percent."

        Design: Corner/calculations/stacked_discount_is_capped_at_the_max_discount_constant
        """
        tier = make_pricing_tier(
            tier_code="MAXX", name="Maximum Contract",
            electrical=0.10, mechanical=0.10, cosmetic=0.44, sealed_system=0.10,
            min_annual_volume_cents=5000000,
        )
        branch = _st_louis()
        panel = make_part(
            part_number="W10-PANEL", oem_code="WHIRLPOOL",
            description="Console panel", category="COSMETIC",
            list_price_cents=10000, weight_grams=500,
        )
        account = make_account(
            tier, business_name="Cosmetic Repairs",
            oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
            credit_limit_cents=10000000, core_liability_limit_cents=5000000,
        )
        order = open_will_call_order(account, branch, purchase_order_ref="PO-3004")

        response = api_client.add_order_line(
            order["id"],
            order_line_payload(panel["id"], 10, order["version"]),
            make_servicer_headers(account["id"]),
        )
        line = validate_success(response, 201)

        assert line["unit_price_cents"] == 5500, (
            f"0.44 + 0.02 clamps to 0.45, so the unit is 5500 and not 5400, got "
            f"{line['unit_price_cents']}"
        )
        assert line["extended_price_cents"] == 55000

        assert_order_money(
            read_order(order["id"]), subtotal=55000, freight=0, total=55000
        )


class TestRoundingOrder:

    def test_a_half_cent_unit_price_rounds_up_before_the_quantity_multiply(self):
        """PRD §2.5: "Wherever a monetary amount is produced by multiplying by a
        percentage, the result is rounded **half up** to a whole cent."
        PRD §2.5: "Line pricing rounds the **unit** price to a whole cent first, and
        only then multiplies the rounded unit price by the line quantity. It never
        multiplies first and rounds once at the end."
        PRD §2.5: "Aggregates such as an order subtotal are plain integer sums of
        amounts that are already rounded; they are never re-rounded."

        Design: Corner/calculations/unit_price_rounds_half_up_before_the_quantity_multiply
        """
        tier = _gold_tier()
        branch = _st_louis()
        knob_a = make_part(
            part_number="W10-KNOB-A", oem_code="WHIRLPOOL",
            description="Control knob A", category="COSMETIC",
            list_price_cents=1002, weight_grams=60,
        )
        knob_b = make_part(
            part_number="W10-KNOB-B", oem_code="WHIRLPOOL",
            description="Control knob B", category="COSMETIC",
            list_price_cents=1006, weight_grams=60,
        )
        account = make_account(
            tier, business_name="Ace Appliance Repair",
            oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
            credit_limit_cents=10000000, core_liability_limit_cents=5000000,
        )
        order = open_will_call_order(account, branch, purchase_order_ref="PO-3005")

        first = add_line(order, knob_a, quantity=3)
        response = api_client.add_order_line(
            order["id"],
            order_line_payload(
                knob_b["id"], 3, read_order(order["id"])["version"]
            ),
            make_servicer_headers(account["id"]),
        )
        second = validate_success(response, 201)

        assert read_line(first["id"])["unit_price_cents"] == 752, (
            "1002 x 0.75 is exactly 751.5 and rounds up"
        )
        assert read_line(first["id"])["extended_price_cents"] == 2256
        assert second["unit_price_cents"] == 755, (
            f"1006 x 0.75 is exactly 754.5 and rounds up, got "
            f"{second['unit_price_cents']}"
        )
        assert second["extended_price_cents"] == 2265

        assert_order_money(
            read_order(order["id"]), subtotal=4521, freight=0, total=4521
        )


# ---------------------------------------------------------------------------
# Which branch wins a line
# ---------------------------------------------------------------------------

class TestBranchRanking:

    def test_stock_depth_outranks_the_cheaper_overnight_surcharge(self):
        """PRD §3.6: "Otherwise the candidates are ranked by three keys in strict
        order: `available_units` descending, so the deepest stock is drawn first;
        then the branch's `overnight_surcharge_cents` ascending, so the cheapest
        branch to ship from wins a tie on depth; then the branch's `created_at`
        ascending as the deterministic final tie-break."
        PRD §3.6: "The base bucket is a flat 1,495 cents."
        PRD §3.6: "The weight bucket takes the shipment weight in grams, divides by
        5,000 grams (five kilograms) to a **rounded-up** whole number of blocks, and
        charges 250 cents per block."
        PRD §3.6: "The surcharge bucket takes the distinct `allocation_branch_id`
        values of those same lines and charges the **largest**
        `overnight_surcharge_cents` among their branches — one truck per order, so
        the worst branch sets the price."

        Design: Corner/calculations/branch_allocation_ranks_inventory_depth_before_overnight_surcharge
        """
        world = _two_branches_holding_nine_and_four_units()

        response = api_client.allocate_part_order(
            world["order"]["id"],
            make_branch_counter_rep_headers(world["deep"]["id"]),
        )
        validate_success(response, 200)

        line = read_line(world["line"]["id"])
        assert line["allocation_branch_id"] == world["deep"]["id"], (
            "nine available units beat four even though the cheaper branch is the "
            "one holding four"
        )
        assert line["line_status"] == "ALLOCATED"

        deep_stock = inventory_for(world["deep"]["id"], world["part"]["id"])
        assert_inventory_units(deep_stock, on_hand=9, reserved=3, available=6)
        cheap_stock = inventory_for(world["cheap"]["id"], world["part"]["id"])
        assert_inventory_units(cheap_stock, on_hand=4, reserved=0, available=4)

        assert_order_money(
            read_order(world["order"]["id"]),
            subtotal=31197, freight=2795, total=33992,
        )


class TestFreightIgnoresUnallocatedLines:

    def test_a_backordered_line_feeds_the_subtotal_but_not_the_weight_blocks(self):
        """PRD §3.6: "The shipment weight is the sum, over the order's lines whose
        `line_status` is `ALLOCATED` or `SHIPPED`, of the resolved part's
        `weight_grams` multiplied by the line's `quantity`; lines sitting in
        `BACKORDERED` or `SUBSTITUTE_PENDING` contribute neither weight nor branch
        surcharge."
        PRD §3.6: "If the candidate set is empty the line becomes `BACKORDERED`, its
        `allocation_branch_id` stays null, and no inventory is touched."
        PRD §3.4: "The `subtotal_cents` is the sum of `extended_price_cents` over
        the order's lines whose `line_status` is `RESOLVED`, `ALLOCATED`,
        `BACKORDERED`, `SHIPPED`, or `RETURNED` — which is to say it excludes
        `CANCELLED` lines and excludes `SUBSTITUTE_PENDING` lines, and that
        exclusion is precisely why an obsolescence cascade lowers an order's total."
        PRD §3.6: "The weight bucket takes the shipment weight in grams, divides by
        5,000 grams (five kilograms) to a **rounded-up** whole number of blocks, and
        charges 250 cents per block."

        Design: Corner/calculations/freight_weight_blocks_ignore_backordered_lines
        """
        world = _drop_ship_order_with_one_stocked_and_one_unstocked_line()

        response = api_client.allocate_part_order(
            world["order"]["id"],
            make_branch_counter_rep_headers(world["branch"]["id"]),
        )
        validate_success(response, 200)

        order = read_order(world["order"]["id"])
        assert order["fulfillment_status"] == "ALLOCATED"

        stocked = read_line(world["stocked"]["id"])
        assert stocked["line_status"] == "ALLOCATED"
        assert stocked["allocation_branch_id"] == world["branch"]["id"]

        unstocked = read_line(world["unstocked"]["id"])
        assert unstocked["line_status"] == "BACKORDERED"
        assert unstocked["allocation_branch_id"] is None
        assert unstocked["extended_price_cents"] == 2399

        assert_order_money(order, subtotal=33596, freight=2595, total=36191)


class TestFreeFreightWaiver:

    def test_the_waiver_fires_at_the_threshold_and_spares_only_the_late_bucket(self):
        """PRD §3.6: "If the order's `subtotal_cents` is at least 50,000 cents (five
        hundred dollars), the base, weight, and surcharge buckets are all waived and
        `freight_cents` is the late bucket alone — the late-cutoff charge
        **survives** free freight."
        PRD §3.6: "Otherwise `freight_cents` is the sum of all four buckets."
        PRD §3.6: "The late bucket charges 500 cents when the UTC hour of the
        logical clock is greater than or equal to the **smallest** `cutoff_hour_utc`
        among those same branches, and nothing otherwise."

        Design: Corner/calculations/free_freight_waiver_fires_exactly_at_the_fifty_thousand_subtotal
        """
        world = _two_drop_ship_orders_below_and_at_the_waiver()
        branch_headers = make_branch_counter_rep_headers(world["branch"]["id"])

        validate_success(
            api_client.allocate_part_order(world["below"]["id"], branch_headers), 200
        )
        response = api_client.allocate_part_order(
            world["at_threshold"]["id"], branch_headers
        )
        validate_success(response, 200)

        assert_order_money(
            read_order(world["below"]["id"]),
            subtotal=40000, freight=3095, total=43095,
        )
        assert_order_money(
            read_order(world["at_threshold"]["id"]),
            subtotal=50000, freight=500, total=50500,
        )

        stock = inventory_for(world["branch"]["id"], world["part"]["id"])
        assert_inventory_units(stock, on_hand=20, reserved=9, available=11)


# ---------------------------------------------------------------------------
# What the line prices off
# ---------------------------------------------------------------------------

class TestSupersessionWalkFeedsPricing:

    def test_two_hops_land_on_the_terminal_part_and_price_off_its_list(self):
        """PRD §3.1: "If it is `ACTIVE`, the walk stops and the current part is the
        resolved part."
        PRD §3.1: "Whatever part the walk stops on becomes the line's
        `resolved_part_id`, and the number of pointers followed to get there becomes
        its `supersession_hops` — zero when the requested part was already `ACTIVE`
        or already `OBSOLETE`."
        PRD §3.4: "Take the line's resolved part and the account's current pricing
        tier."

        Design: Corner/calculations/supersession_walk_resolves_two_hops_to_the_active_terminal_part
        """
        world = _two_hop_supersession_chain()

        response = api_client.add_order_line(
            world["order"]["id"],
            order_line_payload(
                world["original"]["id"], 1, world["order"]["version"]
            ),
            make_servicer_headers(world["account"]["id"]),
        )
        line = validate_success(response, 201)

        assert line["requested_part_id"] == world["original"]["id"]
        assert line["resolved_part_id"] == world["terminal"]["id"], (
            "the walk runs to the only ACTIVE part in the chain"
        )
        assert line["supersession_hops"] == 2
        assert line["unit_price_cents"] == 10400, (
            f"Expected the terminal 13000 x 0.80 rather than the requested part's "
            f"12000, got {line['unit_price_cents']}"
        )
        assert line["extended_price_cents"] == 10400

        assert read_part(world["original"]["id"])["lifecycle_status"] == "SUPERSEDED"
        assert read_part(world["middle"]["id"])["lifecycle_status"] == "SUPERSEDED"
        assert read_part(world["terminal"]["id"])["lifecycle_status"] == "ACTIVE"


class TestWarrantyClaimAmount:

    def test_the_locked_claim_amount_nets_off_the_units_already_returned(self):
        """PRD §3.8: "Submission stamps `submitted_at` with the logical clock and
        **locks** the claim amount: `claim_amount_cents` is the line's
        `invoiced_unit_price_cents` multiplied by the line's `quantity` minus its
        `returned_units`, so that the OEM is never billed for units the distributor
        has already taken back for credit."
        PRD §3.8: "That figure reads the invoiced unit price, never the quoted one,
        and it is frozen at first submission — units returned afterwards do not
        change it, and a resubmission does not recompute it."
        PRD §3.9: "Otherwise consult the pinned `days_since_fulfilled_at_request`: a
        count of 15 days or fewer gives a rate of 0.10, and a count above 15 gives
        0.20."
        PRD §3.9: "Multiply it by `gross_return_cents` and round half up to a whole
        cent to get `restocking_fee_cents`, then take `credit_amount_cents` as
        `gross_return_cents` minus `restocking_fee_cents` — an exact integer
        remainder, so fee plus credit always reconstitutes the gross exactly."

        Design: Corner/calculations/warranty_claim_amount_excludes_units_already_credited_back
        """
        world = _three_shipped_units_with_one_already_credited_back()

        ra = read_return_authorization(world["return_authorization"]["id"])
        assert ra["restocking_fee_cents"] == 1040, (
            f"Expected the day-zero 0.10 rate on a 10399 gross, got "
            f"{ra['restocking_fee_cents']}"
        )
        assert ra["credit_amount_cents"] == 9359

        line = read_line(world["line"]["id"])
        assert line["returned_units"] == 1
        assert line["line_status"] == "SHIPPED", (
            "one of three units back is a partial return"
        )

        response = api_client.submit_warranty_claim(
            world["claim"]["id"], {"oem_reference": "WP-CLAIM-3008"}, WARRANTY_ADMIN
        )
        validate_success(response, 200)

        claim = read_claim(world["claim"]["id"])
        assert claim["claim_status"] == "SUBMITTED"
        assert claim["claim_amount_cents"] == 20798, (
            f"Expected 10399 x (3 - 1) rather than the full 31197, got "
            f"{claim['claim_amount_cents']}"
        )
        assert claim["credit_amount_cents"] is None, (
            "nothing is credited until the claim is closed"
        )
