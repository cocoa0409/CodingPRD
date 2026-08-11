"""Fleet creation defaults, list pagination, and the assignment selector policy."""
from test_helpers import (
    TEST_USERS,
    add_item,
    assert_equipment_item,
    create_equipment_item_payload,
    make_customer,
    make_equipment_item,
    make_reservation,
    validate_paginated,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
MGR = TEST_USERS["manager_headers"]


class TestFleetCreationDefaults:
    def test_new_unit_enters_available(self, api):
        """PRD Building and Maintaining the Fleet: "New units enter as `AVAILABLE`
        with `accrued_rental_days` at zero."

        Design: Corner/state_machines/equipment_initial_state_available
        """
        resp = api.create_equipment_item(
            create_equipment_item_payload(gear_type="BOOT", size_label="26.5",
                                          din_min=0, din_max=0,
                                          purchase_price_cents=25000,
                                          base_daily_rate_cents=1500),
            MGR,
        )
        data = validate_success(resp, expected_status=201)
        assert_equipment_item(data)
        assert data["status"] == "AVAILABLE"
        assert data["accrued_rental_days"] == 0
        assert data["version"] == 1

    def test_client_supplied_system_fields_ignored(self, api):
        """PRD Common Resource Properties: "`id` (string): a unique, server-generated
        identifier formatted as a UUID, with no type prefix."
        PRD Building and Maintaining the Fleet: "New units enter as `AVAILABLE` with
        `accrued_rental_days` at zero."

        Design: Corner/entities/equipment_create_system_fields_input_ignored
        """
        supplied_id = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        payload = create_equipment_item_payload()
        payload.update({"id": supplied_id, "status": "RETIRED", "version": 99})
        resp = api.create_equipment_item(payload, MGR)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "AVAILABLE"
        assert data["version"] == 1
        assert data["id"] != supplied_id


class TestPagination:
    def test_reservation_list_limit_offset_envelope(self, api):
        """PRD Pagination: "Paginated list responses carry four fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/reservation_list_pagination_envelope
        """
        customer = make_customer()
        for start, end in (("2026-12-01", "2026-12-02"), ("2026-12-10", "2026-12-11"),
                           ("2026-12-20", "2026-12-21")):
            make_reservation(customer, start_date=start, end_date=end)

        page1, meta1 = validate_paginated(api.list_reservations(
            FD, params={"customer_id": customer["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_reservations(
            FD, params={"customer_id": customer["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_list_defaults_limit_10_offset_0(self, api):
        """PRD Pagination: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter sets how many items to skip and defaults to 0."

        Design: Corner/endpoints/pagination_defaults_limit_10
        """
        for _ in range(11):
            make_equipment_item()
        data, meta = validate_paginated(api.list_equipment_items(FD))
        assert len(data) == 10
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 11
        assert meta["has_more"] is True


class TestSelectorPolicy:
    def test_auto_assign_picks_oldest_created_eligible_unit(self, api):
        """PRD Booking a Rental: "the oldest-created eligible `AVAILABLE` unit wins —
        and since `id` values are identity-only, "oldest-created" is always decided by
        `created_at`."

        Design: Corner/cross_cutting_layers/selector_assigns_oldest_created_unit
        """
        customer = make_customer()
        u1 = make_equipment_item()
        u2 = make_equipment_item()
        reservation = make_reservation(customer)
        item = add_item(reservation)
        resp = api.assign_reservation_item(item["id"], {}, FD)
        assigned = validate_success(resp)
        assert assigned["equipment_item_id"] == u1["id"], (
            f"expected oldest-created unit {u1['id']}, got {assigned['equipment_item_id']}"
        )
        assert assigned["equipment_item_id"] != u2["id"]


class TestFleetStatusBucketConservation:
    def _setup_three_units_one_assigned(self, api):
        customer = make_customer()
        units = [make_equipment_item() for _ in range(3)]
        reservation = make_reservation(customer)
        item = add_item(reservation)
        assign_resp = api.assign_reservation_item(item["id"], {}, FD)
        assigned = validate_success(assign_resp)
        return customer, units, reservation, assigned

    def test_assign_moves_exactly_one_unit_to_reserved(self, api):
        """PRD Building and Maintaining the Fleet: "A rental assignment moves a unit
        from `AVAILABLE` to `RESERVED`" and "The fleet list can be filtered by
        `status`, `gear_type`, and `tier`."

        Design: Difficulty/compensating_invariant/fleet_status_bucket_conservation
        """
        _, units, _, assigned = self._setup_three_units_one_assigned(api)
        assert assigned["status"] == "ASSIGNED"

        _, reserved_meta = validate_paginated(
            api.list_equipment_items(FD, params={"status": "RESERVED"}))
        _, available_meta = validate_paginated(
            api.list_equipment_items(FD, params={"status": "AVAILABLE"}))
        assert reserved_meta["total_count"] == 1
        assert available_meta["total_count"] == 2
        assert reserved_meta["total_count"] + available_meta["total_count"] == len(units)

    def test_release_restores_bucket_totals(self, api):
        """PRD Booking a Rental: "Releasing a line — again only while the parent
        reservation is `DRAFT` or `CONFIRMED` — moves the line from `ASSIGNED` to
        `RELEASED` and, when no other assigned window keeps it committed, frees the
        unit from `RESERVED` back to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/fleet_status_bucket_conservation
        """
        _, units, _, assigned = self._setup_three_units_one_assigned(api)
        released = validate_success(api.release_reservation_item(assigned["id"], FD))
        assert released["status"] == "RELEASED"

        _, reserved_meta = validate_paginated(
            api.list_equipment_items(FD, params={"status": "RESERVED"}))
        _, available_meta = validate_paginated(
            api.list_equipment_items(FD, params={"status": "AVAILABLE"}))
        assert reserved_meta["total_count"] == 0
        assert available_meta["total_count"] == 3
        # Conserved quantity: the assign/release pair never creates or destroys units.
        assert reserved_meta["total_count"] + available_meta["total_count"] == len(units)
