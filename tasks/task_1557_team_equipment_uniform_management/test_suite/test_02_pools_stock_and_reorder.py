"""Inventory pools: availability ledger, recounts, automatic reorder, and
reverse-direction recovery of the reorder_blocked flag."""
from test_helpers import (
    EM,
    TA,
    ApiErrorId,
    assert_pool_conservation,
    committed_units_for,
    create_active_contract,
    create_jersey_and_pants_pools,
    create_kit_order,
    create_player,
    create_pool,
    create_reserved_kit,
    get_contract,
    get_kit,
    get_pool,
    setup_issued_kit,
    setup_reserved_kit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPoolCreation:
    def test_pool_create_computed_availability(self, api):
        """PRD §3.2: "New pools start `ACTIVE` with both `reserved_quantity` and
        `in_laundry_quantity` at zero, so the initial `available_quantity` equals
        the opening stock."
        PRD §2.6: "A fourth, computed quantity, `available_quantity`, is always
        the stock on hand minus the reserved units minus the in-laundry units."

        Design: Corner/entities/pool_create_computed_availability
        """
        pool = validate_success(api.create_inventory_pool(
            {
                "season_label": "2026-FALL",
                "garment_type": "GAME_JERSEY",
                "size_code": "M",
                "stock_on_hand": 10,
                "reorder_point": 2,
                "reorder_batch_size": 3,
            },
            EM,
        ), 201)
        assert pool["reserved_quantity"] == 0
        assert pool["in_laundry_quantity"] == 0
        assert pool["available_quantity"] == 10, (
            "Initial availability equals the opening stock")
        assert pool["reorder_blocked"] is False
        assert pool["status"] == "ACTIVE"
        assert_pool_conservation(pool)


class TestPoolUniqueness:
    def test_pool_duplicate_key_rejected(self, api):
        """PRD §3.2: "The triple of season, garment type, and size code identifies
        a pool uniquely — a duplicate is rejected with `ERR_POOL_ALREADY_EXISTS`."

        Design: Corner/validations/pool_duplicate_key_rejected
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=5)
        resp = api.create_inventory_pool(
            {
                "season_label": "2026-FALL",
                "garment_type": "GAME_JERSEY",
                "size_code": "M",
                "stock_on_hand": 3,
                "reorder_point": 0,
                "reorder_batch_size": 1,
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_POOL_ALREADY_EXISTS)


class TestStockAdjustment:
    def test_stock_adjustment_below_commitments_rejected(self, api):
        """PRD §3.2: "The recounted value must be at least the sum of the pool's
        reserved and in-laundry units, since those units physically exist
        elsewhere; a lower value is rejected with `ERR_STOCK_BELOW_COMMITMENTS`."

        Design: Corner/validations/stock_adjustment_below_commitments_rejected
        """
        ws = setup_reserved_kit(jersey_number=71, jersey_stock=5, player_name="Adj One")
        pool = get_pool(ws["jersey_pool"]["id"])
        assert pool["reserved_quantity"] == 1

        resp = api.create_stock_adjustment(
            pool["id"],
            {"new_stock_on_hand": 0, "expected_pool_version": pool["version"]},
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_STOCK_BELOW_COMMITMENTS)
        after = get_pool(pool["id"])
        assert after["stock_on_hand"] == 5, "The rejected recount leaves stock untouched"
        assert after["reserved_quantity"] == 1

    def test_occ_stock_adjustment_stale_version_rejected(self, api):
        """PRD §2.8: "A stock recount posted against an inventory pool must carry
        `expected_pool_version`, holding the pool `version` the client last
        observed. If the pool's version has advanced beyond that value — because
        another adjustment, a reservation, an issue, a receive, or a laundry
        movement has since landed — the recount is rejected with
        `ERR_STALE_POOL_VERSION` (HTTP 412) rather than silently overwriting a
        newer count."

        Design: Corner/complexity_layers/occ_stock_adjustment_stale_version_rejected
        """
        pool = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                           size_code="M", stock_on_hand=10)
        observed_version = pool["version"]

        first = validate_success(api.create_stock_adjustment(
            pool["id"],
            {"new_stock_on_hand": 8, "expected_pool_version": observed_version},
            EM,
        ))
        assert first["version"] == observed_version + 1, (
            "A successful recount increments the pool version by exactly 1")
        assert first["stock_on_hand"] == 8

        resp = api.create_stock_adjustment(
            pool["id"],
            {"new_stock_on_hand": 6, "expected_pool_version": observed_version},
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_POOL_VERSION)
        after = get_pool(pool["id"])
        assert after["stock_on_hand"] == 8, (
            "The stale recount is rejected and the newer count stands")
        assert after["version"] == observed_version + 1


class TestReorderEngine:
    def test_reorder_forward_looking_quantity_subtracts_inbound(self, api):
        """PRD §3.2: "The authoritative reorder quantity is the forward-looking
        variant: take the shortfall — the reorder point minus the new available
        quantity minus the inbound open units — and add the pool's
        `reorder_batch_size`."
        PRD §3.2: "the total line quantities on kit orders in `SUBMITTED` or
        `PARTIALLY_RECEIVED` status whose season (derived through their
        contract), garment type, and size code match the pool."

        Design: Difficulty/dual_variant_calc/reorder_quantity_onhand_vs_forward_looking
        """
        jersey = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                             size_code="M", stock_on_hand=10, reorder_point=6,
                             reorder_batch_size=5)
        pants = create_pool(season_label="2026-FALL", garment_type="GAME_PANTS",
                            size_code="34", stock_on_hand=50)
        contract = create_active_contract(
            vendor_name="ACME", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 50},
                             {"garment_type": "GAME_PANTS", "max_units": 50}],
            default_lead_time_days=30)
        create_kit_order(contract["id"], quantity=4, garment_type="GAME_JERSEY",
                         size_code="M", unit_price_cents=5000)

        players = [create_player(full_name=f"K {i}") for i in range(1, 5)]
        for i, player in enumerate(players, start=1):
            create_reserved_kit(player["id"], jersey["id"], pants["id"],
                                jersey_number=i)

        pool = get_pool(jersey["id"])
        assert pool["available_quantity"] == 6 and pool["reserved_quantity"] == 4, (
            "Four reservations land the pool exactly on its reorder point")

        data, meta = validate_paginated(api.list_kit_orders(
            EM, params={"supplier_contract_id": contract["id"],
                        "source": "AUTO_REORDER"}))
        assert meta["total_count"] == 1 and len(data) == 1, (
            "Exactly one AUTO_REORDER order is created")
        auto_order = data[0]
        assert auto_order["lines"][0]["quantity"] == 1, (
            "Forward-looking quantity: (6 - 6 - 4 inbound) + 5 batch = 1, "
            "not the on-hand-only 5")
        assert auto_order["status"] == "SUBMITTED"
        assert auto_order["source"] == "AUTO_REORDER"

        contract_after = get_contract(contract["id"])
        assert committed_units_for(contract_after, "GAME_JERSEY") == 5, (
            "Committed units rise to 4 manual + 1 auto")

    def test_reorder_auto_order_line_contents(self, api):
        """PRD §3.2: "Otherwise the system itself creates a kit order with
        `source` `AUTO_REORDER` in `SUBMITTED` status, containing a single line
        with the pool's garment type and size code, the computed quantity, a
        `unit_price_cents` of zero, and a `line_discount_pct` of zero; the
        committed units for that garment type on the selected contract rise by
        the ordered quantity."

        Design: Difficulty/dual_variant_calc/reorder_quantity_onhand_vs_forward_looking
        """
        jersey = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                             size_code="M", stock_on_hand=10, reorder_point=6,
                             reorder_batch_size=5)
        pants = create_pool(season_label="2026-FALL", garment_type="GAME_PANTS",
                            size_code="34", stock_on_hand=50)
        contract = create_active_contract(
            vendor_name="ACME", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 50},
                             {"garment_type": "GAME_PANTS", "max_units": 50}],
            default_lead_time_days=30)
        create_kit_order(contract["id"], quantity=4, garment_type="GAME_JERSEY",
                         size_code="M", unit_price_cents=5000)
        players = [create_player(full_name=f"L {i}") for i in range(1, 5)]
        for i, player in enumerate(players, start=1):
            create_reserved_kit(player["id"], jersey["id"], pants["id"],
                                jersey_number=i)

        data, _meta = validate_paginated(api.list_kit_orders(
            EM, params={"supplier_contract_id": contract["id"],
                        "source": "AUTO_REORDER"}))
        assert len(data) == 1
        line = data[0]["lines"][0]
        assert line["garment_type"] == "GAME_JERSEY"
        assert line["size_code"] == "M"
        assert line["quantity"] == 1
        assert line["unit_price_cents"] == 0, "Auto-reorder lines carry zero price"
        assert line.get("line_discount_pct", 0) == 0
        assert get_pool(jersey["id"])["reorder_blocked"] is False

    def test_stock_adjustment_triggers_auto_reorder(self, api):
        """PRD §3.2: "A successful recount sets `stock_on_hand` to the new value,
        runs the reconciliation and threshold check in whichever direction
        applies, and bumps the pool's `version`."
        PRD §3.2: "Whenever a reconciliation in the decrease direction pushes a
        pool's available quantity across its reorder point — the available
        quantity was strictly above `reorder_point` before the mutation and lands
        at or below it afterwards — the replenishment engine fires."

        Design: Corner/complexity_layers/stock_adjustment_triggers_auto_reorder
        """
        pool = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                           size_code="M", stock_on_hand=10, reorder_point=6,
                           reorder_batch_size=5)
        contract = create_active_contract(
            vendor_name="AUTOCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 50}],
            default_lead_time_days=30)

        adjusted = validate_success(api.create_stock_adjustment(
            pool["id"],
            {"new_stock_on_hand": 5, "expected_pool_version": pool["version"]},
            EM,
        ))
        assert adjusted["stock_on_hand"] == 5
        assert adjusted["available_quantity"] == 5

        data, meta = validate_paginated(api.list_kit_orders(
            EM, params={"supplier_contract_id": contract["id"],
                        "source": "AUTO_REORDER"}))
        assert meta["total_count"] == 1 and len(data) == 1
        assert data[0]["lines"][0]["quantity"] == 6, (
            "Recount 10 -> 5 crosses point 6: (6 - 5 - 0 inbound) + 5 batch = 6")
        assert data[0]["status"] == "SUBMITTED"
        assert committed_units_for(get_contract(contract["id"]), "GAME_JERSEY") == 6

    def test_kit_return_restock_clears_reorder_block(self, api):
        """PRD §3.2: "If no contract qualifies, the pool's `reorder_blocked` flag
        is set to true and no order is created."
        PRD §3.2: "A blocked pool recovers automatically: on any later
        increase-direction reconciliation that lifts its available quantity back
        above the reorder point, `reorder_blocked` flips back to false."

        Design: Difficulty/transitive_cascade/kit_return_restock_clears_reorder_block
        """
        ws = setup_reserved_kit(
            jersey_number=11, jersey_stock=6, pants_stock=50,
            jersey_size="L", pants_size="36", jersey_reorder_point=5,
            jersey_reorder_batch_size=4, player_name="Ret One")
        pool = get_pool(ws["jersey_pool"]["id"])
        assert pool["reorder_blocked"] is True, (
            "The reservation crosses the point with no contract, latching the flag")
        assert pool["available_quantity"] == 5

        validate_success(api.issue_kit_assignment(ws["kit"]["id"], EM))
        returned = validate_success(api.return_kit_assignment(ws["kit"]["id"], EM))
        assert returned["status"] == "RETURNED"

        pool_after = get_pool(ws["jersey_pool"]["id"])
        assert pool_after["stock_on_hand"] == 6
        assert pool_after["available_quantity"] == 6
        assert pool_after["reorder_blocked"] is False, (
            "The return lifts availability above the point and clears the latch")

    def test_kit_return_frees_number_and_restock_is_exactly_once(self, api):
        """PRD §3.4: "Returning moves an issued kit `ISSUED → RETURNED`
        (`ERR_KIT_NOT_ISSUED` from any other state), adding one unit of
        `stock_on_hand` back to each pool, stamping `closed_at`, and freeing the
        number."
        PRD §3.2: "A blocked pool recovers automatically: on any later
        increase-direction reconciliation that lifts its available quantity back
        above the reorder point, `reorder_blocked` flips back to false."

        Design: Difficulty/transitive_cascade/kit_return_restock_clears_reorder_block
        """
        ws = setup_issued_kit(
            jersey_number=11, jersey_stock=6, pants_stock=50,
            jersey_size="L", pants_size="36", jersey_reorder_point=5,
            jersey_reorder_batch_size=4, player_name="Ret Two")
        assert get_pool(ws["jersey_pool"]["id"])["reorder_blocked"] is True

        returned = validate_success(api.return_kit_assignment(ws["kit"]["id"], EM))
        assert returned["status"] == "RETURNED"
        assert returned.get("closed_at"), "closed_at is stamped on the terminal return"

        pool_after = get_pool(ws["jersey_pool"]["id"])
        assert pool_after["stock_on_hand"] == 6 and pool_after["available_quantity"] == 6
        assert pool_after["reorder_blocked"] is False
        assert_pool_conservation(pool_after)

        other = create_player(full_name="Ret Three")
        kit2 = create_reserved_kit(other["id"], ws["jersey_pool"]["id"],
                                   ws["pants_pool"]["id"], jersey_number=11)
        assert kit2["status"] == "RESERVED", (
            "The freed jersey number can be reserved again in the same season")


class TestPoolConservation:
    def test_pool_reserve_issue_return_conservation(self, api):
        """PRD §2.6: "This is a conservation invariant: at every moment, the
        stock on hand of a pool equals the sum of its available, reserved, and
        in-laundry quantities, and every flow in the system preserves it."
        PRD §3.4: "Issue converts the reservations into physical outflow: each
        pool's `reserved_quantity` and `stock_on_hand` each drop by one"

        Design: Difficulty/compensating_invariant/pool_reserve_issue_return_conservation
        """
        ws = setup_reserved_kit(jersey_number=31, jersey_stock=8, pants_stock=8,
                                player_name="Inv One")
        pool = get_pool(ws["jersey_pool"]["id"])
        assert (pool["stock_on_hand"], pool["reserved_quantity"],
                pool["available_quantity"]) == (8, 1, 7)
        assert_pool_conservation(pool)

        validate_success(api.issue_kit_assignment(ws["kit"]["id"], EM))
        pool = get_pool(ws["jersey_pool"]["id"])
        assert (pool["stock_on_hand"], pool["reserved_quantity"],
                pool["available_quantity"]) == (7, 0, 7), (
            "Issue converts the reservation into physical outflow")
        assert_pool_conservation(pool)

        returned = validate_success(api.return_kit_assignment(ws["kit"]["id"], EM))
        assert returned["status"] == "RETURNED"
        pool = get_pool(ws["jersey_pool"]["id"])
        assert (pool["stock_on_hand"], pool["reserved_quantity"],
                pool["in_laundry_quantity"], pool["available_quantity"]) == (8, 0, 0, 8), (
            "Return fully restores the pool")
        assert_pool_conservation(pool)

    def test_pool_counters_conserved_on_both_pools(self, api):
        """PRD §2.6: "This is a conservation invariant: at every moment, the
        stock on hand of a pool equals the sum of its available, reserved, and
        in-laundry quantities, and every flow in the system preserves it."
        PRD §3.4: "Reserving requires at least one available unit in each pool
        (`ERR_POOL_INSUFFICIENT_STOCK`), and it raises each pool's
        `reserved_quantity` by one"

        Design: Difficulty/compensating_invariant/pool_reserve_issue_return_conservation
        """
        ws = setup_reserved_kit(jersey_number=32, jersey_stock=8, pants_stock=8,
                                player_name="Inv Two")
        for key in ("jersey_pool", "pants_pool"):
            pool = get_pool(ws[key]["id"])
            assert pool["reserved_quantity"] == 1
            assert pool["available_quantity"] == 7
            assert_pool_conservation(pool)

        validate_success(api.issue_kit_assignment(ws["kit"]["id"], EM))
        for key in ("jersey_pool", "pants_pool"):
            pool = get_pool(ws[key]["id"])
            assert (pool["stock_on_hand"], pool["reserved_quantity"]) == (7, 0)
            assert_pool_conservation(pool)

        validate_success(api.return_kit_assignment(ws["kit"]["id"], EM))
        for key in ("jersey_pool", "pants_pool"):
            pool = get_pool(ws[key]["id"])
            assert (pool["stock_on_hand"], pool["available_quantity"]) == (8, 8)
            assert_pool_conservation(pool)


class TestReservationReads:
    def test_pool_availability_excludes_reserved_units(self, api):
        """PRD §2.6: "A fourth, computed quantity, `available_quantity`, is
        always the stock on hand minus the reserved units minus the in-laundry
        units."
        PRD §3.4: "it raises each pool's `reserved_quantity` by one"

        Design: Corner/calculations/pool_availability_excludes_reserved_units
        """
        jersey, pants = create_jersey_and_pants_pools(jersey_stock=10, pants_stock=10)
        p1 = create_player(full_name="Av One")
        p2 = create_player(full_name="Av Two", position_group="DEFENSE")
        create_reserved_kit(p1["id"], jersey["id"], pants["id"], jersey_number=51)
        create_reserved_kit(p2["id"], jersey["id"], pants["id"], jersey_number=52)

        pool = get_pool(jersey["id"])
        assert pool["stock_on_hand"] == 10
        assert pool["reserved_quantity"] == 2
        assert pool["available_quantity"] == 8
        assert_pool_conservation(pool)

    def test_immediate_read_after_kit_reserve(self, api):
        """PRD §2.6: "Every mutation that touches any of the three counters — kit
        reservation, issue, release, or return; event completion loads; laundry
        restock; stock recounts; order receiving; disposition write-off —
        immediately runs an availability reconciliation on the touched pool,
        recomputes `available_quantity`, refreshes the pool's `updated_at`, and
        increments the pool's `version` by 1."
        PRD §3.4: "A fresh assignment sits in `RESERVED`."

        Design: Corner/consistency_model/immediate_read_after_kit_reserve
        """
        jersey, pants = create_jersey_and_pants_pools(jersey_stock=5, pants_stock=5)
        player = create_player(full_name="Imm One")
        kit = validate_success(api.create_kit_assignment(
            {
                "player_id": player["id"],
                "season_label": "2026-FALL",
                "jersey_number": 78,
                "jersey_pool_id": jersey["id"],
                "pants_pool_id": pants["id"],
            },
            EM,
        ), 201)
        assert kit["status"] == "RESERVED", (
            "The create response itself carries the RESERVED status")

        pool = get_pool(jersey["id"])
        assert pool["reserved_quantity"] == 1
        assert pool["available_quantity"] == 4, (
            "The very next read reflects the reservation with no delay")


class TestReservationGates:
    def test_kit_reserve_insufficient_stock_rejected(self, api):
        """PRD §3.4: "Reserving requires at least one available unit in each pool
        (`ERR_POOL_INSUFFICIENT_STOCK`), and it raises each pool's
        `reserved_quantity` by one"

        Design: Corner/validations/kit_reserve_insufficient_stock_rejected
        """
        jersey = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                             size_code="M", stock_on_hand=0)
        pants = create_pool(season_label="2026-FALL", garment_type="GAME_PANTS",
                            size_code="34", stock_on_hand=5)
        player = create_player(full_name="Stk One")
        resp = api.create_kit_assignment(
            {
                "player_id": player["id"],
                "season_label": "2026-FALL",
                "jersey_number": 75,
                "jersey_pool_id": jersey["id"],
                "pants_pool_id": pants["id"],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_POOL_INSUFFICIENT_STOCK)
        assert get_pool(pants["id"])["reserved_quantity"] == 0, (
            "The rejection leaves no partial reservation on the pants pool")

    def test_closed_pool_rejects_new_reservation(self, api):
        """PRD §3.4: "Both pools must exist (`ERR_POOL_NOT_FOUND`), must belong
        to the kit's season (`ERR_POOL_SEASON_MISMATCH`), and must be `ACTIVE`
        (`ERR_POOL_CLOSED`)."
        PRD §3.8: "`DONATE` and `DISCARD` write each affected pool's
        `stock_on_hand` off to zero — the total counted into `units_disposed` —
        and close the pools (`ACTIVE → CLOSED`), with zero proceeds."

        Design: Corner/validations/closed_pool_rejects_new_reservation
        """
        jersey = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                             size_code="M", stock_on_hand=2)
        pants = create_pool(season_label="2026-FALL", garment_type="GAME_PANTS",
                            size_code="34", stock_on_hand=5)
        case = validate_success(api.create_disposition_case(
            {"season_label": "2026-FALL", "garment_type": "GAME_JERSEY",
             "size_code": "M", "method": "DONATE"}, EM), 201)
        validate_success(api.approve_disposition_case(case["id"], TA))
        validate_success(api.execute_disposition_case(case["id"], EM))

        closed = get_pool(jersey["id"])
        assert closed["status"] == "CLOSED" and closed["stock_on_hand"] == 0

        player = create_player(full_name="Clo One")
        resp = api.create_kit_assignment(
            {
                "player_id": player["id"],
                "season_label": "2026-FALL",
                "jersey_number": 76,
                "jersey_pool_id": jersey["id"],
                "pants_pool_id": pants["id"],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_POOL_CLOSED)
        after = get_pool(jersey["id"])
        assert after["status"] == "CLOSED" and after["stock_on_hand"] == 0
