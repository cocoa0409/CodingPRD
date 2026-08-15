"""Stock cutting, allocation selector, remnants, and the approval material
cascade (PRD §3.4-3.5)."""
from test_helpers import (
    ADMIN,
    ADVISOR,
    ApiErrorId,
    approve_quote,
    assert_inventory_item,
    assert_stock_reservation,
    create_inventory_item,
    create_shop,
    get_success_data,
    make_customer_headers,
    open_work_order,
    setup_approved,
    setup_master_data,
    create_cylinder,
    create_stock_reservation_payload,
    setup_quote_sent,
    validate_error,
    validate_paginated,
    validate_success,
)


def _reservations(api, work_order_id):
    return validate_paginated(
        api.list_stock_reservations(ADVISOR, params={"work_order_id": work_order_id})
    )


class TestApprovalMaterialCascade:
    def test_approve_creates_open_reservation_for_rod(self, api):
        """PRD §3.4: "An approved quote fires the material cascade. The quote
        moves from `SENT` to `APPROVED`, the work order moves from `QUOTE_SENT`
        to `APPROVED`, and the system automatically creates one `OPEN` stock
        reservation for the rod when the teardown's `rod_needed` is set — cut to
        `rod_cut_length_mm` from chrome-rod stock of the cylinder's
        `rod_diameter_mm` — and one for the tube when `tube_needed` is set — cut
        to `tube_cut_length_mm` from honing-tube stock of the cylinder's
        `bore_mm` — each allocated by the procedure in §3.5."

        Design: Difficulty/transitive_cascade/quote_approval_cascade_depth3
        """
        sc = setup_approved()  # rod 500mm needed; one 1000mm piece @42c/mm
        assert sc.quote["status"] == "APPROVED"
        assert sc.work_order["status"] == "APPROVED"
        data, meta = _reservations(api, sc.work_order["id"])
        assert meta["total_count"] == 1, f"expected exactly one reservation, got {data}"
        reservation = data[0]
        assert_stock_reservation(reservation)
        assert reservation["status"] == "OPEN"
        assert reservation["cut_length_mm"] == 500
        assert reservation["inventory_item_id"] == sc.rod_item["id"]
        assert reservation["material"] == "CHROME_ROD"
        assert reservation["diameter_mm"] == 45

    def test_approve_cuts_the_selected_inventory_piece(self, api):
        """PRD §3.5: "The item's `length_mm` is reduced by the required length
        (cut plus kerf). When the remainder is shorter than `min_remnant_mm` —
        300 millimetres by default — it is unusable: the remainder is recorded on
        the reservation as `scrap_length_mm`, charged as `scrap_charge_cents`
        equal to the scrap length multiplied by the item's `cost_per_mm_cents`,
        and the item is set to zero length and `DEPLETED`."

        Design: Difficulty/transitive_cascade/quote_approval_cascade_depth3
        """
        sc = setup_approved()
        item = get_success_data(api.get_inventory_item(sc.rod_item["id"], ADVISOR))
        # 1000 - (500 + 3 kerf) = 497; remainder 497 >= 300 stays AVAILABLE.
        assert item["length_mm"] == 497
        assert item["status"] == "AVAILABLE"
        data, _meta = _reservations(api, sc.work_order["id"])
        assert data[0]["scrap_length_mm"] == 0
        assert data[0]["scrap_charge_cents"] == 0


class TestRemnantReleaseConservation:
    def test_release_returns_cut_piece_as_remnant(self, api):
        """PRD §3.5: "When the reservation's `cut_length_mm` is at least
        `min_remnant_mm`, the cut piece returns to stock as a new `AVAILABLE`
        inventory item with `origin` `REMNANT`, a `length_mm` equal to the cut
        length, and the same material, diameter, and `cost_per_mm_cents` as the
        source piece."

        Design: Difficulty/compensating_invariant/material_length_conservation_reserve_release
        """
        sc = setup_approved()
        data, _meta = _reservations(api, sc.work_order["id"])
        reservation = data[0]
        released = validate_success(api.release_stock_reservation(reservation["id"], ADVISOR))
        assert released["status"] == "RELEASED"
        assert released["scrap_length_mm"] == 0
        items, meta = validate_paginated(
            api.list_inventory_items(
                ADVISOR, params={"material": "CHROME_ROD", "status": "AVAILABLE", "limit": 100}
            )
        )
        assert meta["total_count"] == 2
        remnant = next(i for i in items if i["id"] != sc.rod_item["id"])
        assert_inventory_item(remnant)
        assert remnant["length_mm"] == 500
        assert remnant["origin"] == "REMNANT"
        assert remnant["material"] == "CHROME_ROD"
        assert remnant["diameter_mm"] == 45
        assert remnant["cost_per_mm_cents"] == 42

    def test_release_conserves_total_material_length(self, api):
        """PRD §3.5: "The shop's stock ledger stays conservative throughout: the
        total millimetres ever received always equal the lengths still available,
        plus the cut lengths on `OPEN` and `CONSUMED` reservations, plus all
        recorded scrap, plus all kerf consumed."

        Design: Difficulty/compensating_invariant/material_length_conservation_reserve_release
        """
        sc = setup_approved()
        data, _meta = _reservations(api, sc.work_order["id"])
        validate_success(api.release_stock_reservation(data[0]["id"], ADVISOR))
        source = get_success_data(api.get_inventory_item(sc.rod_item["id"], ADVISOR))
        # The release does not change the drawn-down source piece.
        assert source["length_mm"] == 497
        items, _meta = validate_paginated(
            api.list_inventory_items(
                ADVISOR, params={"material": "CHROME_ROD", "status": "AVAILABLE", "limit": 100}
            )
        )
        available = sum(i["length_mm"] for i in items)
        # 497 + 500 available, 0 scrap recorded, 3 kerf consumed == 1000 received.
        assert available + 0 + 3 == 1000


class TestAllocationSelector:
    def test_remnant_boundary_299_scraps_300_survives(self, api):
        """PRD §3.5: "When the remainder is shorter than `min_remnant_mm` — 300
        millimetres by default — it is unusable: the remainder is recorded on the
        reservation as `scrap_length_mm`, charged as `scrap_charge_cents` equal
        to the scrap length multiplied by the item's `cost_per_mm_cents`, and the
        item is set to zero length and `DEPLETED`."

        Design: Corner/calculations/remnant_boundary_299_scraps_300_survives
        """
        md = setup_master_data()
        cylinder = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-M01")
        wo = open_work_order(cylinder["id"], tier="STANDARD", promised_hours=96)
        item_a = create_inventory_item(length_mm=800)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-01T00:00:01Z"}, ADMIN))
        item_b = create_inventory_item(length_mm=800)
        # Cut 497 -> required 500 -> remainder exactly 300 on the earlier piece.
        res1 = validate_success(
            api.create_stock_reservation(
                create_stock_reservation_payload(wo["id"], cut_length_mm=497), ADVISOR
            ),
            201,
        )
        assert res1["inventory_item_id"] == item_a["id"]
        assert res1["scrap_length_mm"] == 0
        item_a_after = get_success_data(api.get_inventory_item(item_a["id"], ADVISOR))
        assert item_a_after["length_mm"] == 300
        assert item_a_after["status"] == "AVAILABLE"
        # Cut 498 -> required 501 -> remainder 299 < 300 on the second piece.
        res2 = validate_success(
            api.create_stock_reservation(
                create_stock_reservation_payload(wo["id"], cut_length_mm=498), ADVISOR
            ),
            201,
        )
        assert res2["inventory_item_id"] == item_b["id"]
        assert res2["scrap_length_mm"] == 299
        assert res2["scrap_charge_cents"] == 12558  # 299 x 42
        item_b_after = get_success_data(api.get_inventory_item(item_b["id"], ADVISOR))
        assert item_b_after["length_mm"] == 0
        assert item_b_after["status"] == "DEPLETED"

    def test_allocation_selector_smallest_sufficient_with_created_at_tiebreak(self, api):
        """PRD §3.5: "The selector picks the smallest sufficient piece — shortest
        `length_mm` first, ties broken by earliest `created_at` — and an empty
        candidate set is rejected with `ERR_NO_STOCK_FITS`."

        Design: Corner/calculations/allocation_selector_smallest_sufficient_with_created_at_tiebreak
        """
        md = setup_master_data()
        cylinder = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-M04")
        wo = open_work_order(cylinder["id"], tier="STANDARD", promised_hours=96)
        create_inventory_item(length_mm=1200)  # t0
        get_success_data(api.set_clock({"to_iso8601": "2026-08-01T00:00:01Z"}, ADMIN))
        first_800 = create_inventory_item(length_mm=800)  # t0+1s
        get_success_data(api.set_clock({"to_iso8601": "2026-08-01T00:00:02Z"}, ADMIN))
        create_inventory_item(length_mm=800)  # t0+2s
        res = validate_success(
            api.create_stock_reservation(
                create_stock_reservation_payload(wo["id"], cut_length_mm=400), ADVISOR
            ),
            201,
        )
        # Smallest sufficient is 800 (not 1200); the tie between the two 800s is
        # broken by earliest created_at.
        assert res["inventory_item_id"] == first_800["id"]
        item = get_success_data(api.get_inventory_item(first_800["id"], ADVISOR))
        assert item["length_mm"] == 397  # 800 - (400 + 3)

    def test_no_stock_piece_large_enough_rejected(self, api):
        """PRD §3.5: "The selector picks the smallest sufficient piece — shortest
        `length_mm` first, ties broken by earliest `created_at` — and an empty
        candidate set is rejected with `ERR_NO_STOCK_FITS`."

        Design: Corner/calculations/no_stock_piece_large_enough_rejected
        """
        md = setup_master_data()
        cylinder = create_cylinder(md.customer["id"], md.kit["id"], serial_number="CYL-M05")
        wo = open_work_order(cylinder["id"], tier="STANDARD", promised_hours=96)
        create_inventory_item(length_mm=1000)
        # Required = 2000 + 3 = 2003 > 1000: empty candidate set.
        resp = api.create_stock_reservation(
            create_stock_reservation_payload(wo["id"], cut_length_mm=2000), ADVISOR
        )
        validate_error(resp, ApiErrorId.ERR_NO_STOCK_FITS)
        _data, meta = _reservations(api, wo["id"])
        assert meta["total_count"] == 0
