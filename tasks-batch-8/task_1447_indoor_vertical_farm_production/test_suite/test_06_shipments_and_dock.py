"""Shipments: dock windows, day capacity, invoice rounding, reservation pools,
same-day discipline, and contract OCC (PRD §2.9, §3.4, §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_crop_with_active_recipe, create_loop_rack, create_growing_batch,
    mark_harvest_ready, harvest_batch, safety_release, pack_batch,
    set_clock, schedule_cycle, start_cycle, record_cycle_result,
    setup_packed_batch, create_contract, create_shipment, get_shipment_lines,
    confirm_pack, setup_reserved_shipment, setup_packed_shipment,
    fresh_contract_version,
    SEED_CLOCK, SANITATION_USER_1,
)

FM = TEST_USERS["farm_manager_headers"]
GR = TEST_USERS["grower_headers"]
CM = TEST_USERS["contracts_manager_headers"]


class TestShipWindowBoundary:
    def _two_packed_shipments(self, api):
        """One crop, one 8-tower rack on one loop; two batches (4 towers each), both
        packed and RELEASED under the same PASSED sanitation cycle; one contract; two
        PACKED shipments."""
        crop, _ = create_crop_with_active_recipe()
        loop, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=8)
        cy1 = schedule_cycle(loop["id"], "2026-08-22T01:00:00Z", "2026-08-22T03:00:00Z")
        b1 = create_growing_batch(crop["id"], [t["id"] for t in towers[0:4]], seed_clock=SEED_CLOCK)
        b2 = create_growing_batch(crop["id"], [t["id"] for t in towers[4:8]], seed_clock=SEED_CLOCK)
        start_cycle(cy1["id"], "2026-08-22T01:00:00Z")
        record_cycle_result(cy1["id"], "PASSED", 0, "2026-08-22T03:30:00Z",
                            recorded_by=SANITATION_USER_1)
        for b, pounds in ((b1, 46.0), (b2, 20.0)):
            mark_harvest_ready(b["id"])
            harvest_batch(b["id"], pounds)
            safety_release(b["id"])
            pack_batch(b["id"], pounds)
        contract = create_contract(crop["id"])
        s1 = create_shipment(contract["id"], [{"batch_id": b1["id"], "reserved_lb": 46.0}])
        s2 = create_shipment(contract["id"], [{"batch_id": b2["id"], "reserved_lb": 20.0}])
        confirm_pack(s1["id"])
        confirm_pack(s2["id"])
        return contract, s1, s2

    def test_ship_at_exactly_window_end_succeeds(self, api):
        """PRD §2.6: "A shipment's dock window admits shipping at or after
        `window_start_at` and at exactly `window_end_at`; any instant after
        `window_end_at` is rejected."

        Design: Difficulty/boundary_precision_check/ship_window_end_inclusive_boundary
        """
        _, s1, _ = self._two_packed_shipments(api)
        set_clock("2026-08-24T20:00:00Z")
        shipped = validate_success(api.ship_shipment(s1["id"], CM))
        assert shipped["shipment_status"] == "SHIPPED"

    def test_ship_one_second_after_window_end_rejected(self, api):
        """PRD §2.6: "any instant after `window_end_at` is rejected." PRD §3.5: "window
        violations surface as `ERR_SHIPMENT_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/ship_window_end_inclusive_boundary
        """
        _, _, s2 = self._two_packed_shipments(api)
        set_clock("2026-08-24T20:00:01Z")
        resp = api.ship_shipment(s2["id"], CM)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_WINDOW_CLOSED)
        after = validate_success(api.get_shipment(s2["id"], CM))
        assert after["shipment_status"] == "PACKED"


class TestDockDayCapacity:
    def _packed_batch_and_contract(self, api):
        ctx = setup_packed_batch(packed_lb=100.0, tower_count=4)
        contract = create_contract(ctx["crop"]["id"])
        return ctx, contract

    def test_three_overlapping_window_shipments_accepted(self, api):
        """PRD §3.5: "The dock works on aggregate capacity rather than interval
        arithmetic: a `ship_date` already carrying three shipments in `RESERVED`,
        `PACKED`, or `SHIPPED` rejects a fourth with `ERR_DOCK_CAPACITY_EXCEEDED`,
        regardless of how the requested windows interleave."

        Design: Difficulty/resource_temporal_overlap/dock_day_aggregate_capacity_quota
        """
        ctx, contract = self._packed_batch_and_contract(api)
        for _ in range(3):
            shipment = create_shipment(
                contract["id"], [{"batch_id": ctx["batch"]["id"], "reserved_lb": 1.0}],
                window_start="2026-08-24T08:00:00Z", window_end="2026-08-24T12:00:00Z")
            assert shipment["shipment_status"] == "RESERVED", \
                "fully overlapping windows are irrelevant to the day quota"

    def test_fourth_shipment_same_day_rejected(self, api):
        """PRD §3.5: "a `ship_date` already carrying three shipments in `RESERVED`,
        `PACKED`, or `SHIPPED` rejects a fourth with `ERR_DOCK_CAPACITY_EXCEEDED`".

        Design: Difficulty/resource_temporal_overlap/dock_day_aggregate_capacity_quota
        """
        ctx, contract = self._packed_batch_and_contract(api)
        for _ in range(3):
            create_shipment(contract["id"], [{"batch_id": ctx["batch"]["id"], "reserved_lb": 1.0}],
                            window_start="2026-08-24T08:00:00Z", window_end="2026-08-24T12:00:00Z")
        version = fresh_contract_version(contract["id"])
        resp = api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T18:00:00Z", "window_end_at": "2026-08-24T20:00:00Z",
             "expected_contract_version": version,
             "lines": [{"batch_id": ctx["batch"]["id"], "reserved_lb": 1.0}]}, CM)
        validate_error(resp, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED)


class TestShipmentInvoiceRounding:
    def _shipped_invoice_scenario(self, api):
        ctx = setup_packed_batch(packed_lb=36.25, grade_a_lb=36.25, tower_count=4)
        contract = create_contract(ctx["crop"]["id"], price_per_pound_cents=245)
        shipment = create_shipment(contract["id"], [
            {"batch_id": ctx["batch"]["id"], "reserved_lb": 10.55},
            {"batch_id": ctx["batch"]["id"], "reserved_lb": 20.15},
            {"batch_id": ctx["batch"]["id"], "reserved_lb": 5.55},
        ])
        confirm_pack(shipment["id"])
        set_clock("2026-08-24T15:00:00Z")
        return shipment

    def test_invoice_total_rounds_per_line_then_sums(self, api):
        """PRD §3.5: "for each shipped line the amount is the line's `shipped_lb` times
        the contract's `price_per_pound_cents`, rounded half-up to whole cents per line
        first, and only then summed — summing first and rounding once would be a
        different, incorrect number."

        Design: Difficulty/combinatorial_formula/shipment_invoice_per_line_rounding
        """
        shipment = self._shipped_invoice_scenario(api)
        shipped = validate_success(api.ship_shipment(shipment["id"], CM))
        # round(10.55x245)=2585 + round(20.15x245)=4937 + round(5.55x245)=1360
        assert shipped["invoice_total_cents"] == 8882
        assert shipped["shipment_status"] == "SHIPPED"

    def test_invoice_lines_shipped_with_packed_pounds(self, api):
        """PRD §3.5: "Shipping moves each line to `SHIPPED` with `shipped_lb` equal to
        its `packed_lb`".

        Design: Difficulty/combinatorial_formula/shipment_invoice_per_line_rounding
        """
        shipment = self._shipped_invoice_scenario(api)
        validate_success(api.ship_shipment(shipment["id"], CM))
        lines = get_shipment_lines(shipment["id"])
        by_reserved = sorted(lines, key=lambda ln: ln["reserved_lb"])
        assert [ln["line_status"] for ln in by_reserved] == ["SHIPPED"] * 3
        for ln in by_reserved:
            assert ln["shipped_lb"] == pytest.approx(ln["packed_lb"])
        reread = validate_success(api.get_shipment(shipment["id"], CM))
        assert reread["invoice_total_cents"] == 8882, "invoice is fixed at ship time"


class TestShipValidationPriority:
    def _quarantined_packed_shipment(self, api):
        ctx = setup_packed_batch(packed_lb=46.0, grade_a_lb=40.0, grade_b_lb=6.0, cull_lb=3.0)
        ship_ctx = setup_reserved_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=10.0)
        confirm_pack(ship_ctx["shipment"]["id"])
        cy2 = schedule_cycle(ctx["loop"]["id"], "2026-08-24T13:00:00Z", "2026-08-24T15:00:00Z")
        start_cycle(cy2["id"], "2026-08-24T13:00:00Z")
        record_cycle_result(cy2["id"], "FAILED", 400, "2026-08-24T15:30:00Z",
                            recorded_by=SANITATION_USER_1)
        return ship_ctx

    def test_ship_quarantine_beats_window_closed(self, api):
        """PRD §2.10: tier 7 "Food-safety gates" ("Batch safety release, quarantine and
        condemnation checks, the same-day pack rule, and sanitation recency") precedes
        tier 9 "Temporal windows and overlaps" ("Interval overlap rules, earliness
        rules, and calendar window validity"), and "the server evaluates them in a fixed
        tier order and reports the first failure encountered."

        Design: Difficulty/priority_pair_validation_conflict/ship_safety_violation_beats_window_closed
        """
        ship_ctx = self._quarantined_packed_shipment(api)
        set_clock("2026-08-24T20:00:01Z")  # one second past the window end
        resp = api.ship_shipment(ship_ctx["shipment"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_BATCH_QUARANTINED)

    def test_ship_quarantined_batch_inside_window(self, api):
        """PRD §3.5: ship requires "every line's batch is safety-`RELEASED` (otherwise
        `ERR_BATCH_SAFETY_PENDING`, `ERR_BATCH_QUARANTINED`, or `ERR_BATCH_CONDEMNED`
        according to the batch's state)".

        Design: Difficulty/priority_pair_validation_conflict/ship_safety_violation_beats_window_closed
        """
        ship_ctx = self._quarantined_packed_shipment(api)
        set_clock("2026-08-24T16:00:00Z")  # inside the 08:00-20:00 window
        resp = api.ship_shipment(ship_ctx["shipment"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_BATCH_QUARANTINED)


class TestShipmentCropMismatch:
    def _basil_batch_and_kale_contract(self, api):
        basil_ctx = setup_packed_batch(
            packed_lb=100.0, tower_count=4,
            crop_overrides={"crop_code": "BASIL-01", "display_name": "Basil", "category": "HERB",
                            "margin_cents_per_lb": 500, "floor_price_cents_per_lb": 200},
            recipe_overrides={"light_hours_per_day": 14, "expected_yield_lb_per_tower": 10.0})
        kale = validate_success(api.create_crop(
            {"crop_code": "KALE-01", "display_name": "Kale", "category": "LEAFY_GREEN",
             "margin_cents_per_lb": 300, "floor_price_cents_per_lb": 100}, FM), expected_status=201)
        contract = create_contract(kale["id"])
        return basil_ctx, contract

    def test_crop_mismatch_beats_commitment_overflow(self, api):
        """PRD §2.10: tier 8 "Reference coherence ... (`ERR_SHIPMENT_CROP_MISMATCH` ...)"
        precedes tier 10 "Capacity, quota, and uniqueness ...
        (`ERR_CONTRACT_COMMITMENT_EXCEEDED` ... `ERR_BATCH_POUNDS_INSUFFICIENT`)", and
        "the server evaluates them in a fixed tier order and reports the first failure
        encountered."

        Design: Difficulty/priority_pair_validation_conflict/shipment_crop_mismatch_beats_commitment_overflow
        """
        basil_ctx, contract = self._basil_batch_and_kale_contract(api)
        version = fresh_contract_version(contract["id"])
        resp = api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T08:00:00Z", "window_end_at": "2026-08-24T20:00:00Z",
             "expected_contract_version": version,
             "lines": [{"batch_id": basil_ctx["batch"]["id"], "reserved_lb": 600.0}]}, CM)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_CROP_MISMATCH)

    def test_crop_mismatch_alone_rejected(self, api):
        """PRD §3.5: "every line's batch ... must grow the contract's crop
        (`ERR_SHIPMENT_CROP_MISMATCH`)".

        Design: Difficulty/priority_pair_validation_conflict/shipment_crop_mismatch_beats_commitment_overflow
        """
        basil_ctx, contract = self._basil_batch_and_kale_contract(api)
        version = fresh_contract_version(contract["id"])
        resp = api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T08:00:00Z", "window_end_at": "2026-08-24T20:00:00Z",
             "expected_contract_version": version,
             "lines": [{"batch_id": basil_ctx["batch"]["id"], "reserved_lb": 10.0}]}, CM)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_CROP_MISMATCH)


class TestReservationPoolInvariant:
    def test_reserve_debits_batch_and_contract_pools(self, api):
        """PRD §3.5: "each batch's `reserved_lb` rises and its `packed_available_lb`
        falls by the reserved pounds, the contract's `week_reserved_lb` is recomputed";
        the contract's `week_reserved_lb` tracks "the live reserved pounds of its
        `RESERVED` and `PACKED` shipments whose `ship_date` falls inside the week
        containing the current clock date."

        Design: Difficulty/compensating_invariant/contract_week_pounds_conserved_under_reserve_cancel
        """
        ctx = setup_packed_batch(packed_lb=100.0, tower_count=4)
        contract = create_contract(ctx["crop"]["id"])
        batch0 = validate_success(api.get_batch(ctx["batch"]["id"], GR))
        assert batch0["packed_available_lb"] == pytest.approx(100.00)

        create_shipment(contract["id"], [{"batch_id": ctx["batch"]["id"], "reserved_lb": 10.0}])
        contract_mid = validate_success(api.get_contract(contract["id"], CM))
        assert contract_mid["week_reserved_lb"] == pytest.approx(10.00)
        batch_mid = validate_success(api.get_batch(ctx["batch"]["id"], GR))
        assert batch_mid["packed_available_lb"] == pytest.approx(90.00)

    def test_cancel_restores_batch_and_contract_pools(self, api):
        """PRD §3.5: "Canceling a `RESERVED` or `PACKED` shipment releases every line in
        `RESERVED`, `PACKED`, or `SHORTED` — each release subtracts the line's reserved
        pounds from the batch's `reserved_lb` and returns any packed pounds to
        `packed_available_lb` — and recomputes the contract's `week_reserved_lb`."

        Design: Difficulty/compensating_invariant/contract_week_pounds_conserved_under_reserve_cancel
        """
        ctx = setup_packed_batch(packed_lb=100.0, tower_count=4)
        contract = create_contract(ctx["crop"]["id"])
        shipment = create_shipment(contract["id"],
                                   [{"batch_id": ctx["batch"]["id"], "reserved_lb": 10.0}])

        validate_success(api.cancel_shipment(shipment["id"], CM))
        contract_end = validate_success(api.get_contract(contract["id"], CM))
        assert contract_end["week_reserved_lb"] == pytest.approx(0.00)
        batch_end = validate_success(api.get_batch(ctx["batch"]["id"], GR))
        assert batch_end["reserved_lb"] == pytest.approx(0.00)
        assert batch_end["packed_available_lb"] == pytest.approx(100.00), \
            "compensating release restores the batch pool exactly"


class TestShipmentLifecycle:
    def test_shipment_ship_twice_rejected(self, api):
        """PRD §3.5: ship moves a shipment "From `RESERVED` or `PACKED`" — a `SHIPPED`
        shipment admits no further ship, so the repeat is an invalid lifecycle
        transition (PRD §2.10 tier 5). "fixes the `invoice_total_cents`" at ship time.

        Design: Corner/state_machines/shipment_ship_twice_rejected
        """
        ctx = setup_packed_batch(packed_lb=46.0, tower_count=4)
        ship_ctx = setup_packed_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=10.0)
        set_clock("2026-08-24T15:00:00Z")
        shipped = validate_success(api.ship_shipment(ship_ctx["shipment"]["id"], CM))
        assert shipped["invoice_total_cents"] == 2450  # round(10.00 x 245)

        resp = api.ship_shipment(ship_ctx["shipment"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        reread = validate_success(api.get_shipment(ship_ctx["shipment"]["id"], CM))
        assert reread["invoice_total_cents"] == 2450, "rejected re-ship must not move the invoice"

    def test_confirm_pack_shortage_releases_difference(self, api):
        """PRD §3.5: "a line whose packed pounds equal its reserved pounds moves to
        `PACKED`, while a shortfall moves it to `SHORTED` and returns the difference to
        the batch's `packed_available_lb`. The shipment advances from `RESERVED` to
        `PACKED`, `has_shortage` is recomputed — true exactly when any line is
        `SHORTED`".

        Design: Corner/endpoints/confirm_pack_shortage_releases_difference
        """
        ctx = setup_packed_batch(packed_lb=100.0, tower_count=4)
        ship_ctx = setup_reserved_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=20.0)
        line_id = ship_ctx["lines"][0]["id"]

        shipment = validate_success(api.confirm_pack_shipment(
            ship_ctx["shipment"]["id"], {"lines": [{"line_id": line_id, "packed_lb": 15.0}]}, CM))
        assert shipment["shipment_status"] == "PACKED"
        assert shipment["has_shortage"] is True

        line = get_shipment_lines(ship_ctx["shipment"]["id"])[0]
        assert line["line_status"] == "SHORTED"
        assert line["packed_lb"] == pytest.approx(15.00)

        batch = validate_success(api.get_batch(ctx["batch"]["id"], GR))
        assert batch["packed_available_lb"] == pytest.approx(85.00), \
            "the 5.00 lb shortfall returns to the batch pool"

    def test_line_not_packed_blocks_ship(self, api):
        """PRD §3.5: "a shipment ships only when every line has already been through
        confirm-pack — a line still `RESERVED` at ship time is rejected with
        `ERR_LINE_NOT_PACKED`".

        Design: Corner/errors/line_not_packed_blocks_ship
        """
        ctx = setup_packed_batch(packed_lb=46.0, tower_count=4)
        ship_ctx = setup_reserved_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=10.0)
        set_clock("2026-08-24T15:00:00Z")
        resp = api.ship_shipment(ship_ctx["shipment"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_PACKED)
        after = validate_success(api.get_shipment(ship_ctx["shipment"]["id"], CM))
        assert after["shipment_status"] == "RESERVED"


class TestShipmentCreationGates:
    def test_ship_date_mismatch_rejected(self, api):
        """PRD §3.5: "the `ship_date` must equal the harvest UTC date of every line's
        batch, and both window endpoints must fall on `ship_date` with the start before
        the end — any mismatch is `ERR_SHIP_DATE_MISMATCH`."

        Design: Corner/errors/ship_date_mismatch_rejected
        """
        ctx = setup_packed_batch(packed_lb=46.0, tower_count=1)
        contract = create_contract(ctx["crop"]["id"])
        version = fresh_contract_version(contract["id"])
        resp = api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-25",
             "window_start_at": "2026-08-25T08:00:00Z", "window_end_at": "2026-08-25T20:00:00Z",
             "expected_contract_version": version,
             "lines": [{"batch_id": ctx["batch"]["id"], "reserved_lb": 10.0}]}, CM)
        validate_error(resp, ApiErrorId.ERR_SHIP_DATE_MISMATCH)

    def test_batch_not_packed_blocks_shipment_create(self, api):
        """PRD §3.5: "every line's batch must be in `production_status` `PACKED`
        (`ERR_BATCH_NOT_PACKED`)".

        Design: Corner/errors/batch_not_packed_blocks_shipment_create
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        mark_harvest_ready(batch["id"])
        batch = harvest_batch(batch["id"], 46.0)
        safety_release(batch["id"])  # RELEASED but never packed

        contract = create_contract(crop["id"])
        version = fresh_contract_version(contract["id"])
        resp = api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T08:00:00Z", "window_end_at": "2026-08-24T20:00:00Z",
             "expected_contract_version": version,
             "lines": [{"batch_id": batch["id"], "reserved_lb": 10.0}]}, CM)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_PACKED)

    def test_batch_pounds_insufficient_exact_boundary(self, api):
        """PRD §3.5: "Per batch, the lines' combined `reserved_lb` may not exceed that
        batch's `packed_available_lb`, else `ERR_BATCH_POUNDS_INSUFFICIENT`."

        Design: Corner/errors/batch_pounds_insufficient_exact_boundary
        """
        ctx = setup_packed_batch(packed_lb=100.0, tower_count=1)
        contract = create_contract(ctx["crop"]["id"], weekly_commitment_lb=600)
        # Exactly the available pool: allowed ("may not exceed" is inclusive).
        ok = create_shipment(contract["id"], [{"batch_id": ctx["batch"]["id"], "reserved_lb": 100.0}],
                             window_start="2026-08-24T08:00:00Z",
                             window_end="2026-08-24T12:00:00Z")
        assert ok["shipment_status"] == "RESERVED"
        # A further 0.01 lb exceeds the now-empty pool.
        version = fresh_contract_version(contract["id"])
        resp = api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T13:00:00Z", "window_end_at": "2026-08-24T20:00:00Z",
             "expected_contract_version": version,
             "lines": [{"batch_id": ctx["batch"]["id"], "reserved_lb": 0.01}]}, CM)
        validate_error(resp, ApiErrorId.ERR_BATCH_POUNDS_INSUFFICIENT)

    def test_contract_commitment_exact_boundary_then_exceeded(self, api):
        """PRD §3.5: "if the new lines would push the week's reserved pounds above
        `weekly_commitment_lb`, creation fails with `ERR_CONTRACT_COMMITMENT_EXCEEDED`"
        — exactly at the commitment does not exceed it.

        Design: Corner/errors/contract_commitment_exact_boundary_then_exceeded
        """
        ctx = setup_packed_batch(packed_lb=600.0, grade_a_lb=600.0, tower_count=1)
        contract = create_contract(ctx["crop"]["id"], weekly_commitment_lb=500)
        s1 = create_shipment(contract["id"], [{"batch_id": ctx["batch"]["id"], "reserved_lb": 300.0}],
                             window_start="2026-08-24T08:00:00Z",
                             window_end="2026-08-24T10:00:00Z")
        assert s1["shipment_status"] == "RESERVED"
        s2 = create_shipment(contract["id"], [{"batch_id": ctx["batch"]["id"], "reserved_lb": 200.0}],
                             window_start="2026-08-24T10:00:00Z",
                             window_end="2026-08-24T12:00:00Z")
        assert s2["shipment_status"] == "RESERVED"
        contract_mid = validate_success(api.get_contract(contract["id"], CM))
        assert contract_mid["week_reserved_lb"] == pytest.approx(500.00), \
            "cumulative reservations exactly at the commitment are allowed"

        version = fresh_contract_version(contract["id"])
        resp = api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T13:00:00Z", "window_end_at": "2026-08-24T20:00:00Z",
             "expected_contract_version": version,
             "lines": [{"batch_id": ctx["batch"]["id"], "reserved_lb": 0.01}]}, CM)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_COMMITMENT_EXCEEDED)


class TestShipmentCreateOcc:
    def test_occ_shipment_create_stale_contract_version(self, api):
        """PRD §2.9: "Creating a shipment requires `expected_contract_version`, the
        client-observed `version` of the parent `RetailContract`" and "If the supplied
        value does not equal the parent entity's current `version` ... the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the
        parent and retry." PRD §3.5: "the contract's `version` increments by one."

        Design: Corner/cross_cutting_layers/occ_shipment_create_stale_contract_version
        """
        ctx = setup_packed_batch(packed_lb=100.0, tower_count=1)
        contract = create_contract(ctx["crop"]["id"])
        v1 = contract["version"]

        s1 = validate_success(api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T08:00:00Z", "window_end_at": "2026-08-24T12:00:00Z",
             "expected_contract_version": v1,
             "lines": [{"batch_id": ctx["batch"]["id"], "reserved_lb": 10.0}]}, CM),
            expected_status=201)
        assert s1["shipment_status"] == "RESERVED"

        stale = api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T13:00:00Z", "window_end_at": "2026-08-24T20:00:00Z",
             "expected_contract_version": v1,
             "lines": [{"batch_id": ctx["batch"]["id"], "reserved_lb": 5.0}]}, CM)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        v2 = fresh_contract_version(contract["id"])
        assert v2 == v1 + 1, "shipment creation increments the contract version by one"
        s2 = validate_success(api.create_shipment(
            {"contract_id": contract["id"], "ship_date": "2026-08-24",
             "window_start_at": "2026-08-24T13:00:00Z", "window_end_at": "2026-08-24T20:00:00Z",
             "expected_contract_version": v2,
             "lines": [{"batch_id": ctx["batch"]["id"], "reserved_lb": 5.0}]}, CM),
            expected_status=201)
        assert s2["shipment_status"] == "RESERVED"
