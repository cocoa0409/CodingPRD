"""Item-fee quote composition, pinned rounding order, and allowance boundary."""
from test_helpers import (
    add_item,
    consume_allowance,
    create_draft_request,
    create_household,
    create_route_day,
    get_ledger_row,
    get_request_items,
    make_resident_headers,
    set_clock,
    setup_submitted_request,
    submit_request,
    validate_success,
)

class TestPerItemFeeMultiBranch:
    def test_over_allowance_mattress_and_refrigerant_oversize_prices(self, api):
        """PRD §3.3: "With the allowance outcome known, the **scheduled
        variant** of the item-fee quote reruns: the same per-item composition
        and per-item-then-sum rounding as §3.2, but now honoring each item's
        actual `within_allowance` flag and the frozen `amnesty_applied`"
        PRD §3.2: "for each item composes its fee from up to four components:
        an over-allowance fee of 2500 cents when the item is not within the
        free allowance; a refrigerant recovery fee of 4500 cents when the
        category is `APPLIANCE_WITH_REFRIGERANT`; an oversize fee of 1500
        cents when `is_oversize` is true; and a mattress fee of 1200 cents
        when the category is `MATTRESS`."

        Design: Difficulty/combinatorial_formula/per_item_fee_multi_branch_mode_a
        """
        set_clock("2026-01-05T00:00:00Z")
        hh = create_household("7 Pine Rd", "ZONE_SOUTH", annual_allowance_items=4)
        # Consume the full 2026 allowance (4 slots) in January.
        consume_allowance(hh["id"], 4, service_zone="ZONE_SOUTH")

        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_SOUTH", route_date="2026-08-20")

        req2 = create_draft_request(hh["id"])
        it1 = add_item(hh["id"], req2["id"], 1, "MATTRESS", False, True)
        it2 = add_item(hh["id"], req2["id"], 2, "APPLIANCE_WITH_REFRIGERANT", True, True)
        submit_request(hh["id"], req2["id"])

        resp = api.schedule_pickup_request(
            req2["id"],
            {"route_day_id": rd["id"], "expected_route_day_version": rd["version"]},
            make_resident_headers(hh["id"]),
        )
        data = validate_success(resp)
        assert data["provisional_total_cents"] == 13238

        after_items = get_request_items(req2["id"], make_resident_headers(hh["id"]))
        by_seq = {i["sequence_no"]: i for i in after_items}
        assert by_seq[1]["item_fee_cents"] == 4015
        assert by_seq[1]["within_allowance"] is False
        assert by_seq[2]["item_fee_cents"] == 9223
        assert by_seq[2]["within_allowance"] is False

        ledger = get_ledger_row(hh["id"], 2026)
        assert ledger["items_consumed"] == 4
        assert ledger["over_allowance_items"] == 2

    def test_branch_interaction_in_allowance_vs_over_allowance(self, api):
        """PRD §3.2: "The item's subtotal is the sum of whichever components
        apply, and the municipal processing surcharge of 8.5 percent is then
        applied to that subtotal and rounded half-up to a whole cent for that
        item; the item's `item_fee_cents` is its subtotal plus its surcharge."

        Design: Difficulty/combinatorial_formula/per_item_fee_multi_branch_mode_a
        """
        set_clock("2026-08-05T00:00:00Z")
        # Fresh household, full allowance: fridge+oversize item is free of the
        # 2500 over-allowance component -> 4500+1500=6000, surcharge 510.
        hh, req, items = setup_submitted_request(
            street_address="7B Pine Rd", service_zone="ZONE_SOUTH",
            annual_allowance_items=4,
            items=((1, "APPLIANCE_WITH_REFRIGERANT", True, True),),
        )
        rd = create_route_day(service_zone="ZONE_SOUTH", route_date="2026-08-20")
        resp = api.schedule_pickup_request(
            req["id"],
            {"route_day_id": rd["id"], "expected_route_day_version": rd["version"]},
            make_resident_headers(hh["id"]),
        )
        data = validate_success(resp)
        assert data["provisional_total_cents"] == 6510
        after_items = get_request_items(req["id"], make_resident_headers(hh["id"]))
        assert after_items[0]["item_fee_cents"] == 6510
        assert after_items[0]["within_allowance"] is True

class TestPerItemThenSumRounding:
    def test_per_item_rounding_then_sum_pinned(self, api):
        """PRD §2.6: "Where a calculation produces a fraction of a cent (only
        the per-item municipal surcharge does), the result is rounded
        **half-up to a whole cent at the per-item level before any
        summation**: each item's surcharge-inclusive fee is rounded first, and
        only then are item fees summed into a request total. This
        per-item-then-sum rounding order is pinned and must not be inverted."

        Design: Difficulty/combinatorial_formula/per_line_vs_sum_rounding_mode_b
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("3 Birch Ln", "ZONE_WEST", annual_allowance_items=1)
        # Consume the single 2026 slot so both asserted items are over-allowance.
        consume_allowance(hh["id"], 1, service_zone="ZONE_WEST",
                          route_date="2026-08-14")

        rd = create_route_day(service_zone="ZONE_WEST", route_date="2026-08-21")

        req = create_draft_request(hh["id"])
        add_item(hh["id"], req["id"], 1, "APPLIANCE_WITH_REFRIGERANT", True, True)
        add_item(hh["id"], req["id"], 2, "MATTRESS", False, True)
        submit_request(hh["id"], req["id"])

        resp = api.schedule_pickup_request(
            req["id"],
            {"route_day_id": rd["id"], "expected_route_day_version": rd["version"]},
            make_resident_headers(hh["id"]),
        )
        data = validate_success(resp)
        # 8500 -> surcharge round_half_up(722.5)=723 -> 9223
        # 3700 -> surcharge round_half_up(314.5)=315 -> 4015
        assert data["provisional_total_cents"] == 13238

    def test_per_item_fees_are_individually_rounded(self, api):
        """PRD §3.2: "The request's `provisional_total_cents` is the sum of
        the per-item fees. Because the rounding happens per item before
        summing, two requests with identical components in different groupings
        can legitimately quote different totals, and implementations must
        reproduce the pinned order exactly."

        Design: Difficulty/combinatorial_formula/per_line_vs_sum_rounding_mode_b
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("3B Birch Ln", "ZONE_WEST", annual_allowance_items=1)
        consume_allowance(hh["id"], 1, service_zone="ZONE_WEST",
                          route_date="2026-08-14")

        rd = create_route_day(service_zone="ZONE_WEST", route_date="2026-08-21")

        req = create_draft_request(hh["id"])
        add_item(hh["id"], req["id"], 1, "APPLIANCE_WITH_REFRIGERANT", True, True)
        add_item(hh["id"], req["id"], 2, "MATTRESS", False, True)
        submit_request(hh["id"], req["id"])

        resp = api.schedule_pickup_request(
            req["id"],
            {"route_day_id": rd["id"], "expected_route_day_version": rd["version"]},
            make_resident_headers(hh["id"]),
        )
        validate_success(resp)
        items = get_request_items(req["id"], make_resident_headers(hh["id"]))
        by_seq = {i["sequence_no"]: i for i in items}
        assert by_seq[1]["item_fee_cents"] == 9223
        assert by_seq[2]["item_fee_cents"] == 4015

class TestAllowanceZeroRemainingBoundary:
    def test_item_taking_consumption_to_allowance_is_free(self, api):
        """PRD §3.3: "while the household's remaining free slots for the year
        — `annual_allowance_items` minus `items_consumed` — are at least 1,
        the next item in order takes a slot, its `within_allowance` becomes
        true, and `items_consumed` rises by 1; the item that lifts
        `items_consumed` from one below the allowance to exactly the allowance
        is still free, and the very next item is fee-bearing, its
        `within_allowance` false and `over_allowance_items` rising by 1
        instead."

        Design: Difficulty/boundary_precision_check/allowance_zero_remaining_boundary
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        hh, req, _ = setup_submitted_request(
            street_address="15 Juniper Way", service_zone="ZONE_NORTH",
            annual_allowance_items=1,
            items=(
                (1, "STANDARD_FURNITURE", False, True),
                (2, "STANDARD_FURNITURE", False, True),
            ),
        )
        resp = api.schedule_pickup_request(
            req["id"],
            {"route_day_id": rd["id"], "expected_route_day_version": rd["version"]},
            make_resident_headers(hh["id"]),
        )
        validate_success(resp)
        items = get_request_items(req["id"], make_resident_headers(hh["id"]))
        by_seq = {i["sequence_no"]: i for i in items}
        assert by_seq[1]["within_allowance"] is True
        assert by_seq[1]["item_fee_cents"] == 0

    def test_next_item_after_allowance_is_fee_bearing(self, api):
        """PRD §3.3: "the item that lifts `items_consumed` from one below the
        allowance to exactly the allowance is still free, and the very next
        item is fee-bearing, its `within_allowance` false and
        `over_allowance_items` rising by 1 instead."
        PRD §3.2: "an over-allowance fee of 2500 cents when the item is not
        within the free allowance"

        Design: Difficulty/boundary_precision_check/allowance_zero_remaining_boundary
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        hh, req, _ = setup_submitted_request(
            street_address="15B Juniper Way", service_zone="ZONE_NORTH",
            annual_allowance_items=1,
            items=(
                (1, "STANDARD_FURNITURE", False, True),
                (2, "STANDARD_FURNITURE", False, True),
            ),
        )
        resp = api.schedule_pickup_request(
            req["id"],
            {"route_day_id": rd["id"], "expected_route_day_version": rd["version"]},
            make_resident_headers(hh["id"]),
        )
        validate_success(resp)
        items = get_request_items(req["id"], make_resident_headers(hh["id"]))
        by_seq = {i["sequence_no"]: i for i in items}
        # 2500 + round_half_up(2500*0.085)=round_half_up(212.5)=213 -> 2713
        assert by_seq[2]["within_allowance"] is False
        assert by_seq[2]["item_fee_cents"] == 2713
        ledger = get_ledger_row(hh["id"], 2026)
        assert ledger["items_consumed"] == 1
        assert ledger["over_allowance_items"] == 1
