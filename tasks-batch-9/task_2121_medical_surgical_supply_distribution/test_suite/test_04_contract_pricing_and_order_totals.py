"""The contract unit-price selector and formula, and order totalling."""

from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_contract_line,
    add_order_line,
    approve_formulary_item,
    assert_order_line,
    create_contract,
    create_item,
    create_order,
    create_order_line_payload,
    create_supply_room,
    make_materials_manager_headers,
    read_order,
    setup_draft_order,
    setup_priced_catalogue,
    validate_error,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def test_contract_scoped_to_another_member_class_never_enters_the_candidate_set(api):
    """PRD §3.2: "The candidate set is every contract line whose `item_id`
    matches the line's item, whose `activation_state` is `ACTIVE`, whose parent
    contract's `status` is `ACTIVE`, whose parent contract's
    `member_class_scope` equals the destination room's `gpo_member_class`, and
    whose parent contract's closed effective period contains *T*."
    PRD §3.2: "An empty candidate set is a hard failure —
    `ERR_NO_ACTIVE_CONTRACT_PRICE` (HTTP 422) — never a zero price."

    Design: Corner/calculations/unit_price_input_set_excludes_contracts_scoped_to_another_member_class
    """
    world = setup_draft_order(
        room_overrides={
            "facility_code": "FAC-300", "room_code": "GEN-300",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
        },
        item_overrides={
            "sku": "SKU-CL1-CS", "description": "Class filter probe",
            "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
            "handling_class": "AMBIENT", "units_per_parent": 10,
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": "CTR-NA",
            "tier": "TIER_1", "member_class_scope": "NON_ACUTE",
        },
        tier_price_cents=3000,
        floor_price_cents=2000,
        formulary_overrides={"facility_item_code": "FAC-CL1", "par_qty": 50,
                             "reorder_point": 10},
    )

    response = api.create_order_line(
        world["order"]["id"],
        create_order_line_payload(world["item"]["id"], 1, world["order"]["version"]),
        make_materials_manager_headers(world["room"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_CONTRACT_PRICE.value, 422)

    after = read_order(world["order"]["id"])
    assert after["order_total_cents"] == 0
    assert after["version"] == world["order"]["version"], (
        "a refused line write must not advance the order's version"
    )


def test_price_selector_takes_the_lowest_tier_price_across_manufacturers(api):
    """PRD §3.2: "Because cross-manufacturer overlap is legal, that set can
    genuinely hold more than one row, so ranking is fixed and total: lowest
    `tier_price_cents` first; ties broken by the later parent-contract
    `effective_from`; remaining ties broken by the earlier contract-line
    `created_at`."
    PRD §3.2: "Contracts from **different** manufacturers may legitimately be
    active over the same item at the same instant; the rule never fires across
    manufacturers, and the price selector below is what decides between them."

    Design: Corner/calculations/unit_price_selector_ranks_lowest_tier_price_then_latest_effective_from
    """
    room = create_supply_room(
        facility_code="FAC-301", room_code="GEN-301", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )
    item = create_item(
        sku="SKU-RNK-X-CS", description="Ranking probe X",
        manufacturer_code="MFR-ACME", uom="CS", wac_cents=9000,
        handling_class="AMBIENT", units_per_parent=10,
    )

    dearer = create_contract(
        manufacturer_code="MFR-ACME", contract_code="CTR-HI", tier="TIER_1",
        member_class_scope="ACUTE",
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-12-31T23:59:59Z",
    )
    dearer_line = add_contract_line(
        dearer["id"], item["id"], tier_price_cents=3000, floor_price_cents=1000
    )
    activate_contract(dearer["id"])

    cheaper = create_contract(
        manufacturer_code="MFR-OMNI", contract_code="CTR-LO", tier="TIER_1",
        member_class_scope="ACUTE",
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-12-31T23:59:59Z",
    )
    cheaper_line = add_contract_line(
        cheaper["id"], item["id"], tier_price_cents=2800, floor_price_cents=1000
    )
    activate_contract(cheaper["id"])

    approve_formulary_item(
        room["id"], item["id"], facility_item_code="FAC-RNK-X", par_qty=50,
        reorder_point=10,
    )
    order = create_order(room["id"])
    line = add_order_line(order["id"], room["id"], item["id"], 1, order["version"])
    assert_order_line(line)

    assert line["pinned_contract_line_id"] == cheaper_line["id"]
    assert line["pinned_contract_line_id"] != dearer_line["id"]
    assert line["pinned_unit_price_cents"] == 2800
    assert line["extended_price_cents"] == 2800
    assert line["line_fee_cents"] == 77
    assert read_order(order["id"])["order_total_cents"] == 2877


def test_wholesale_acquisition_cost_caps_the_computed_unit_price(api):
    """PRD §3.2: "The sum of the rounded tier price and the two adders is then
    raised to the contract line's `floor_price_cents` if it falls below it, and
    only after that is it capped at the item's `wac_cents` if it exceeds it. The
    floor is applied before the ceiling; reversing those two steps is wrong."
    PRD §3.1: "The wholesale acquisition cost does double duty: it is the hard
    ceiling on any contract-derived unit price, and it is the baseline against
    which the manufacturer chargeback in §3.9 is computed."

    Design: Corner/calculations/unit_price_wac_ceiling_caps_the_computed_price
    """
    world = setup_draft_order(
        room_overrides={
            "facility_code": "FAC-302", "room_code": "ICU-302",
            "gpo_member_class": "ACUTE", "room_type": "ICU", "refrigerated": True,
        },
        item_overrides={
            "sku": "SKU-CAP-EA", "description": "WAC ceiling probe, each",
            "manufacturer_code": "MFR-BIO", "uom": "EA", "wac_cents": 4600,
            "handling_class": "COLD_CHAIN", "units_per_parent": 1,
        },
        contract_overrides={
            "manufacturer_code": "MFR-BIO", "contract_code": "CTR-CAP",
            "tier": "TIER_3", "member_class_scope": "ACUTE",
        },
        tier_price_cents=4000,
        floor_price_cents=3500,
        formulary_overrides={"facility_item_code": "FAC-CAP", "par_qty": 50,
                             "reorder_point": 10, "lum_enabled": True},
    )

    line = add_order_line(
        world["order"]["id"], world["room"]["id"], world["item"]["id"], 1,
        world["order"]["version"],
    )

    assert line["pinned_unit_price_cents"] == 4600, (
        "the raw price of 4652 is capped at the item's wac_cents of 4600"
    )
    assert line["extended_price_cents"] == 4600
    assert line["line_fee_cents"] == 127
    assert read_order(world["order"]["id"])["order_total_cents"] == 4727


class TestUnitPriceFormulaNesting:
    """The tier multiplier, the two adders, the contract floor and the WAC
    ceiling compose in a pinned order."""

    @staticmethod
    def _cold_chain_world():
        return setup_priced_catalogue(
            [
                {
                    "item": {
                        "sku": "SKU-VAX-A-EA",
                        "description": "Refrigerated biologic A, each",
                        "manufacturer_code": "MFR-BIO", "uom": "EA",
                        "wac_cents": 5000, "handling_class": "COLD_CHAIN",
                        "units_per_parent": 1,
                    },
                    "tier_price_cents": 4000,
                    "floor_price_cents": 3500,
                    "formulary": {"facility_item_code": "FAC-VAX-A", "par_qty": 50,
                                  "reorder_point": 10, "lum_enabled": True},
                },
                {
                    "item": {
                        "sku": "SKU-VAX-B-EA",
                        "description": "Refrigerated biologic B, each",
                        "manufacturer_code": "MFR-BIO", "uom": "EA",
                        "wac_cents": 5000, "handling_class": "COLD_CHAIN",
                        "units_per_parent": 1,
                    },
                    "tier_price_cents": 100,
                    "floor_price_cents": 500,
                    "formulary": {"facility_item_code": "FAC-VAX-B", "par_qty": 50,
                                  "reorder_point": 10, "lum_enabled": True},
                },
            ],
            room_overrides={
                "facility_code": "FAC-003", "room_code": "ICU-3",
                "gpo_member_class": "ACUTE", "room_type": "ICU", "refrigerated": True,
            },
            contract_overrides={
                "manufacturer_code": "MFR-BIO", "contract_code": "CTR-T3",
                "tier": "TIER_3", "member_class_scope": "ACUTE",
            },
        )

    @classmethod
    def _write_both_lines(cls):
        world = cls._cold_chain_world()
        order = create_order(world["room"]["id"])
        line_a = add_order_line(
            order["id"], world["room"]["id"], world["items"][0]["id"], 1,
            order["version"],
        )
        line_b = add_order_line(
            order["id"], world["room"]["id"], world["items"][1]["id"], 1
        )
        return world, order, line_a, line_b

    def test_tier_multiplier_and_both_adders_apply_when_no_bound_binds(self, api):
        """PRD §3.2: "Once the top-ranked line is chosen, its price is built in a
        pinned order of operations. Start from that line's `tier_price_cents` as
        the base. Multiply the base by the tier multiplier — `TIER_1` multiplies
        by 1.00, `TIER_2` by 1.06, `TIER_3` by 1.13 — and **round that product
        half up to a whole cent immediately**."
        PRD §3.2: "The cold-handling adder applies only when the item's
        `handling_class` is `COLD_CHAIN` or `CONTROLLED_COLD`, and equals
        whichever is larger of 45 cents and three percent of the **unmultiplied
        base** rounded half up to a whole cent; otherwise it is zero."
        PRD §3.2: "The low-unit-of-measure adder is 12 cents, and it applies only
        when the item's `uom` is `EA` **and** the destination room's formulary
        mapping for that item has `lum_enabled` set to true; otherwise it is
        zero."

        Design: Difficulty/combinatorial_formula/unit_price_nested_max_then_min_with_lum_and_cold_adders
        """
        _world, _order, line_a, _line_b = self._write_both_lines()

        assert line_a["pinned_unit_price_cents"] == 4652, (
            "4000 * 1.13 = 4520, plus the 12-cent LUM adder and the 120-cent "
            "cold adder, with neither the 3500 floor nor the 5000 ceiling binding"
        )
        assert line_a["line_fee_cents"] == 128

    def test_contract_floor_lifts_a_price_that_falls_below_it(self, api):
        """PRD §3.2: "The sum of the rounded tier price and the two adders is
        then raised to the contract line's `floor_price_cents` if it falls below
        it, and only after that is it capped at the item's `wac_cents` if it
        exceeds it. The floor is applied before the ceiling; reversing those two
        steps is wrong."
        PRD §3.2: "Note that the floor is genuinely permitted to exceed the base
        price, in which case it binds after the tier multiplier and the handling
        adders have been applied."

        Design: Difficulty/combinatorial_formula/unit_price_nested_max_then_min_with_lum_and_cold_adders
        """
        _world, _order, _line_a, line_b = self._write_both_lines()

        assert line_b["pinned_unit_price_cents"] == 500, (
            "100 * 1.13 = 113, plus 12 and 45 gives a raw 170, which the "
            "contract floor of 500 lifts"
        )
        assert line_b["line_fee_cents"] == 14

    def test_order_total_sums_both_bounded_lines(self, api):
        """PRD §3.4: "The order's `order_total_cents` is the sum, over the
        participating lines, of extended price plus line fee."
        PRD §3.4: "For each participating line the extended price is its
        `pinned_unit_price_cents` multiplied by that quantity basis, and the line
        fee is the distribution fee of 2.75 percent applied to that extended
        price and **rounded half up to a whole cent on that line, before
        anything is summed**."

        Design: Difficulty/combinatorial_formula/unit_price_nested_max_then_min_with_lum_and_cold_adders
        """
        _world, order, line_a, line_b = self._write_both_lines()

        assert line_a["extended_price_cents"] == 4652
        assert line_b["extended_price_cents"] == 500
        assert read_order(order["id"])["order_total_cents"] == 5294, (
            "4652 + 128 + 500 + 14"
        )


class TestPerLineFeeRounding:
    """The distribution fee is rounded on each line before anything is summed."""

    @staticmethod
    def _two_two_hundred_cent_lines():
        world = setup_priced_catalogue(
            [
                {
                    "item": {
                        "sku": "SKU-TAPE-CS", "description": "Surgical tape, case",
                        "manufacturer_code": "MFR-ACME", "uom": "CS",
                        "wac_cents": 5000, "handling_class": "AMBIENT",
                        "units_per_parent": 12,
                    },
                    "tier_price_cents": 200,
                    "floor_price_cents": 100,
                    "formulary": {"facility_item_code": "FAC-TAPE", "par_qty": 60,
                                  "reorder_point": 12},
                },
                {
                    "item": {
                        "sku": "SKU-SWAB-CS", "description": "Prep swab, case",
                        "manufacturer_code": "MFR-ACME", "uom": "CS",
                        "wac_cents": 5000, "handling_class": "AMBIENT",
                        "units_per_parent": 12,
                    },
                    "tier_price_cents": 200,
                    "floor_price_cents": 100,
                    "formulary": {"facility_item_code": "FAC-SWAB", "par_qty": 60,
                                  "reorder_point": 12},
                },
            ],
            room_overrides={
                "facility_code": "FAC-004", "room_code": "GEN-STORE-4",
                "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
            },
            contract_overrides={
                "manufacturer_code": "MFR-ACME", "contract_code": "CTR-T1",
                "tier": "TIER_1", "member_class_scope": "ACUTE",
            },
        )
        order = create_order(world["room"]["id"])
        line_a = add_order_line(
            order["id"], world["room"]["id"], world["items"][0]["id"], 1,
            order["version"],
        )
        line_b = add_order_line(
            order["id"], world["room"]["id"], world["items"][1]["id"], 1
        )
        return order, line_a, line_b

    def test_each_line_rounds_its_own_fee_half_up(self, api):
        """PRD §3.4: "For each participating line the extended price is its
        `pinned_unit_price_cents` multiplied by that quantity basis, and the line
        fee is the distribution fee of 2.75 percent applied to that extended
        price and **rounded half up to a whole cent on that line, before
        anything is summed**."
        PRD §2.6: "Wherever a rate multiplication produces a fraction, the result
        is rounded **half up** to a whole cent — a value of exactly one half cent
        rounds away from zero, upward."

        Design: Difficulty/combinatorial_formula/order_total_rounds_distribution_fee_per_line_before_summing
        """
        _order, line_a, line_b = self._two_two_hundred_cent_lines()

        assert line_a["extended_price_cents"] == 200
        assert line_a["line_fee_cents"] == 6, "2.75% of 200 is 5.5, rounded half up"
        assert line_b["extended_price_cents"] == 200
        assert line_b["line_fee_cents"] == 6

    def test_order_total_is_per_line_rounded_never_sum_rounded(self, api):
        """PRD §3.4: "Summing the extended prices first and rounding a single fee
        over the sum is explicitly wrong and produces a different answer: two
        lines each extending to 200 cents total 412 cents per-line-rounded, and
        411 cents if the fee is rounded once over the sum."
        PRD §2.6: "Rounding placement matters as much as rounding mode, and the
        two places it matters most are stated where the formulas live: the
        distribution fee is rounded once per order line and only then summed
        (§3.4), and the chargeback administrative fee is rounded exactly once,
        after the bracket has been selected (§3.9)."

        Design: Difficulty/combinatorial_formula/order_total_rounds_distribution_fee_per_line_before_summing
        """
        order, _line_a, _line_b = self._two_two_hundred_cent_lines()
        total = read_order(order["id"])["order_total_cents"]

        assert total == 412
        assert total != 411, (
            "411 is the answer produced by rounding one fee over the summed "
            "extended prices, which the contract forbids"
        )
