"""Kitting and bagging: packaging-cost rounding order, the PICKING/ON_HOLD
branch structure, stock reservation conservation, station-window buffer
semantics, and the warehouse role boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_part_conservation,
    create_kit_job,
    create_part,
    create_site,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]


class TestPackagingCostRounding:
    def _setup_pair(self, api, kit_count):
        """Two components priced at 333 cents each; per-line ceiling applies
        before summing: ceil(250 + 10*3 + 333*4/100) = ceil(293.32) = 294 per
        line, 588 per kit (sum-then-round would yield 587)."""
        site = create_site(api, delivery_mode="LINE_SIDE")
        p1 = create_part(api, unit_price_cents=333, total_stock_qty=10000)
        p2 = create_part(api, unit_price_cents=333, total_stock_qty=10000)
        job = create_kit_job(
            api, site["id"], [p1["id"], p2["id"]],
            qty_per_part=10, kit_count=kit_count,
            station_window_start="2026-08-10T08:00:00Z",
            station_window_end="2026-08-10T09:00:00Z")
        get_success_data(api.start_picking(job["id"], OPERATOR))
        return job

    def test_packaging_cost_rounds_per_line_then_sums(self, api):
        """PRD §3.6: "The charge is built per component line, in the order the
        components are listed: each line is the ceiling — rounding up to a
        whole cent — of 250 cents per bag, plus `qty_per_part` times 3 cents
        per unit, plus four percent of that component part's current
        `unit_price_cents`. The per-line figures are rounded first and then
        summed, and the sum is multiplied by `kit_count` to yield the final
        `packaging_cost_cents`."

        Design: Difficulty/combinatorial_formula/kit_packaging_per_line_round_then_sum
        """
        job = self._setup_pair(api, kit_count=1)
        packed = validate_success(api.pack_kit_job(job["id"], OPERATOR))
        assert packed["status"] == "PACKED"
        assert packed["packaging_cost_cents"] == 588, (
            "per-line ceil gives 294 + 294 = 588; sum-then-round would give "
            "587 and is not correct"
        )

    def test_packaging_cost_multiplies_line_sum_by_kit_count(self, api):
        """PRD §3.6: "The per-line figures are rounded first and then summed,
        and the sum is multiplied by `kit_count` to yield the final
        `packaging_cost_cents`."

        Same two 333-cent components at qty_per_part 10: line sum 588 per kit,
        two kits -> 1176.

        Design: Difficulty/combinatorial_formula/kit_packaging_per_line_round_then_sum
        """
        job = self._setup_pair(api, kit_count=2)
        packed = validate_success(api.pack_kit_job(job["id"], OPERATOR))
        assert packed["status"] == "PACKED"
        assert packed["packaging_cost_cents"] == 1176


class TestPickingHoldBranching:
    def _picking_job(self, api):
        site = create_site(api, delivery_mode="LINE_SIDE")
        part = create_part(api, unit_price_cents=1000, total_stock_qty=1000)
        job = create_kit_job(
            api, site["id"], [part["id"]], qty_per_part=5, kit_count=2,
            station_window_start="2026-08-10T08:00:00Z",
            station_window_end="2026-08-10T09:00:00Z")
        get_success_data(api.start_picking(job["id"], OPERATOR))
        return part, job

    def test_hold_resume_hold_scrap_branch_restores_stock(self, api):
        """PRD §3.6: "Scrapping from `ON_HOLD` performs exactly the same
        compensating release as scrapping from `PICKING`, with the same version
        increments."
        PRD §3.6: "Scrapping from `PICKING` performs the compensating release:
        every component's `reserved_qty` decreases by `qty_per_part` times
        `kit_count` and its `available_qty` increases by the same amount,
        restoring the conservation invariant, and the `version` of the job and
        of each component part increments."

        Design: Difficulty/non_linear_state_machine/kit_job_picking_hold_branching
        """
        part, job = self._picking_job(api)
        get_success_data(api.hold_kit_job(job["id"], OPERATOR))
        get_success_data(api.resume_kit_job(job["id"], OPERATOR))
        get_success_data(api.hold_kit_job(job["id"], OPERATOR))
        scrapped = validate_success(api.scrap_kit_job(job["id"], OPERATOR))
        assert scrapped["status"] == "SCRAPPED"

        part_after = get_success_data(api.get_part(part["id"], ADMIN))
        assert part_after["reserved_qty"] == 0, (
            "scrap-from-hold releases the retained reservation"
        )
        assert part_after["available_qty"] == 1000
        assert part_after["total_stock_qty"] == 1000, (
            "nothing was consumed — the reservation is fully released"
        )

    def test_hold_retains_reservations_then_resume(self, api):
        """PRD §3.6: "A picking job can be paused: holding moves `PICKING` to
        `ON_HOLD` and retains all reservations while held, incrementing the
        job's `version`."
        PRD §3.6: "Resuming returns `ON_HOLD` to `PICKING`, but re-verifies
        that every component part is still `ACTIVE`, rejecting with
        `ERR_QUANTITY_OUT_OF_BOUNDS` if obsolescence intervened."

        Design: Difficulty/non_linear_state_machine/kit_job_picking_hold_branching
        """
        part, job = self._picking_job(api)
        held = validate_success(api.hold_kit_job(job["id"], OPERATOR))
        assert held["status"] == "ON_HOLD"
        part_held = get_success_data(api.get_part(part["id"], ADMIN))
        assert part_held["reserved_qty"] == 10, (
            "reservations are retained while ON_HOLD"
        )
        assert part_held["available_qty"] == 990
        resumed = validate_success(api.resume_kit_job(job["id"], OPERATOR))
        assert resumed["status"] == "PICKING"


class TestStockReservationInvariant:
    def _site_part(self, api):
        site = create_site(api, delivery_mode="LINE_SIDE")
        part = create_part(api, unit_price_cents=1000, total_stock_qty=1000)
        return site, part

    def test_start_then_scrap_restores_stock_invariant(self, api):
        """PRD §2.9: "The distributor's stock of each part obeys a strict
        conservation invariant: for every part, `reserved_qty` plus
        `available_qty` always equals `total_stock_qty`."
        PRD §3.6: "Scrapping from `PICKING` performs the compensating release:
        every component's `reserved_qty` decreases by `qty_per_part` times
        `kit_count` and its `available_qty` increases by the same amount,
        restoring the conservation invariant, and the `version` of the job and
        of each component part increments."

        Design: Difficulty/compensating_invariant/kit_start_then_scrap_restores_part_stock_invariant
        """
        site, part = self._site_part(api)
        job = create_kit_job(api, site["id"], [part["id"]], qty_per_part=5,
                             kit_count=2)
        get_success_data(api.start_picking(job["id"], OPERATOR))
        scrapped = validate_success(api.scrap_kit_job(job["id"], OPERATOR))
        assert scrapped["status"] == "SCRAPPED"
        part_after = get_success_data(api.get_part(part["id"], ADMIN))
        assert part_after["reserved_qty"] == 0
        assert part_after["available_qty"] == 1000
        assert part_after["total_stock_qty"] == 1000
        assert_part_conservation(part_after)

    def test_start_picking_moves_stock_into_reserved(self, api):
        """PRD §3.6: "On success, each component's `reserved_qty` increases by
        that product and its `available_qty` decreases by the same amount,
        preserving the conservation invariant of §2.9, and the `version` of the
        job and of every component part increments by one."

        Design: Difficulty/compensating_invariant/kit_start_then_scrap_restores_part_stock_invariant
        """
        site, part = self._site_part(api)
        job = create_kit_job(api, site["id"], [part["id"]], qty_per_part=5,
                             kit_count=2)
        picking = validate_success(api.start_picking(job["id"], OPERATOR))
        assert picking["status"] == "PICKING"
        part_mid = get_success_data(api.get_part(part["id"], ADMIN))
        assert part_mid["reserved_qty"] == 10, "5 per kit x 2 kits reserved"
        assert part_mid["available_qty"] == 990
        assert_part_conservation(part_mid)


class TestPickingPreconditions:
    def test_insufficient_stock_blocks_kit_picking(self, api):
        """PRD §3.6: "Every component part must still be `ACTIVE` — otherwise
        `ERR_QUANTITY_OUT_OF_BOUNDS` — and each component's `available_qty`
        must cover `qty_per_part` multiplied by `kit_count`; a shortfall on any
        component is rejected with `ERR_INSUFFICIENT_STOCK`."

        Design: Corner/validations/insufficient_stock_blocks_kit_picking
        """
        site = create_site(api, delivery_mode="LINE_SIDE")
        part = create_part(api, unit_price_cents=100, total_stock_qty=8)
        job = create_kit_job(api, site["id"], [part["id"]], qty_per_part=5,
                             kit_count=2)
        resp = api.start_picking(job["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK, 422)
        part_after = get_success_data(api.get_part(part["id"], ADMIN))
        assert part_after["reserved_qty"] == 0, "no partial reservation"
        assert part_after["available_qty"] == 8
        job_after = get_success_data(api.get_kit_job(job["id"], OPERATOR))
        assert job_after["status"] == "DRAFT"

    def test_obsolete_component_blocks_start_picking(self, api):
        """PRD §3.6: "Every component part must still be `ACTIVE` — otherwise
        `ERR_QUANTITY_OUT_OF_BOUNDS` — and each component's `available_qty`
        must cover `qty_per_part` multiplied by `kit_count`; a shortfall on any
        component is rejected with `ERR_INSUFFICIENT_STOCK`."

        Design: Difficulty/cross_entity_state_dependency/kit_picking_requires_all_component_parts_active
        """
        site = create_site(api, delivery_mode="LINE_SIDE")
        pa = create_part(api, sku="SKU-PA", unit_price_cents=1000,
                         total_stock_qty=1000)
        pb = create_part(api, sku="SKU-PB", unit_price_cents=1000,
                         total_stock_qty=1000)
        job = create_kit_job(api, site["id"], [pa["id"], pb["id"]],
                             qty_per_part=1, kit_count=1)
        get_success_data(api.obsolete_part(pb["id"], ADMIN))
        resp = api.start_picking(job["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_QUANTITY_OUT_OF_BOUNDS, 422)
        job_after = get_success_data(api.get_kit_job(job["id"], OPERATOR))
        assert job_after["status"] == "DRAFT"

    def test_rejected_start_picking_leaves_no_partial_reservation(self, api):
        """PRD §3.6: "On success, each component's `reserved_qty` increases by
        that product and its `available_qty` decreases by the same amount,
        preserving the conservation invariant of §2.9, and the `version` of the
        job and of every component part increments by one."
        PRD §2.9: "The distributor's stock of each part obeys a strict
        conservation invariant: for every part, `reserved_qty` plus
        `available_qty` always equals `total_stock_qty`."

        A rejected start-picking is not a success, so no component's figures
        move at all — including the still-ACTIVE sibling component.

        Design: Difficulty/cross_entity_state_dependency/kit_picking_requires_all_component_parts_active
        """
        site = create_site(api, delivery_mode="LINE_SIDE")
        pa = create_part(api, sku="SKU-PA2", unit_price_cents=1000,
                         total_stock_qty=1000)
        pb = create_part(api, sku="SKU-PB2", unit_price_cents=1000,
                         total_stock_qty=1000)
        job = create_kit_job(api, site["id"], [pa["id"], pb["id"]],
                             qty_per_part=1, kit_count=1)
        get_success_data(api.obsolete_part(pb["id"], ADMIN))
        validate_error(api.start_picking(job["id"], OPERATOR),
                       ApiErrorId.ERR_QUANTITY_OUT_OF_BOUNDS, 422)
        pa_after = get_success_data(api.get_part(pa["id"], ADMIN))
        assert pa_after["reserved_qty"] == 0
        assert pa_after["available_qty"] == 1000
        assert_part_conservation(pa_after)


class TestStationWindowBuffer:
    def _site_and_part(self, api):
        site = create_site(api, delivery_mode="LINE_SIDE")
        part = create_part(api, unit_price_cents=1000, total_stock_qty=10000)
        return site, part

    def test_abutting_station_window_rejected(self, api):
        """PRD §3.6: "Station reservations use closed-interval-with-buffer
        semantics, deliberately stricter than the half-open route windows: the
        new job's `station_window_start` must fall at least 15 minutes after
        the `station_window_end` of every existing non-terminal job — one in
        `DRAFT`, `PICKING`, `ON_HOLD`, or `PACKED` — whose window would
        otherwise abut or overlap, and the start must be strictly before the
        end. Violations are rejected with `ERR_STATION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/kit_station_windows_require_buffer_gap
        """
        site, part = self._site_and_part(api)
        create_kit_job(api, site["id"], [part["id"]], kit_name="job one",
                       station_window_start="2026-08-10T08:00:00Z",
                       station_window_end="2026-08-10T09:00:00Z")
        resp = api.create_kit_job(
            {"site_id": site["id"], "kit_name": "job two",
             "component_part_ids": [part["id"]], "qty_per_part": 1,
             "kit_count": 1,
             "station_window_start": "2026-08-10T09:00:00Z",
             "station_window_end": "2026-08-10T10:00:00Z"},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_STATION_WINDOW_CONFLICT, 422)

    def test_station_window_with_full_buffer_accepted(self, api):
        """PRD §3.6: "Station reservations use closed-interval-with-buffer
        semantics, deliberately stricter than the half-open route windows: the
        new job's `station_window_start` must fall at least 15 minutes after
        the `station_window_end` of every existing non-terminal job — one in
        `DRAFT`, `PICKING`, `ON_HOLD`, or `PACKED` — whose window would
        otherwise abut or overlap, and the start must be strictly before the
        end. Violations are rejected with `ERR_STATION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/kit_station_windows_require_buffer_gap
        """
        site, part = self._site_and_part(api)
        create_kit_job(api, site["id"], [part["id"]], kit_name="job one",
                       station_window_start="2026-08-10T08:00:00Z",
                       station_window_end="2026-08-10T09:00:00Z")
        resp = api.create_kit_job(
            {"site_id": site["id"], "kit_name": "job two",
             "component_part_ids": [part["id"]], "qty_per_part": 1,
             "kit_count": 1,
             "station_window_start": "2026-08-10T09:15:00Z",
             "station_window_end": "2026-08-10T10:15:00Z"},
            OPERATOR)
        created = validate_success(resp, 201)
        assert created["status"] == "DRAFT", (
            "exactly the 15-minute buffer after the prior window end satisfies "
            "the closed-interval-with-buffer rule"
        )


class TestKitRoleBoundary:
    def test_distributor_admin_cannot_drive_kit_lifecycle(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403);
        the per-endpoint role assignments are listed in §4."
        PRD §4: POST /vmi/kit-jobs/{id}/start-picking — Authorized Role(s):
        WarehouseOperator.

        Design: Corner/roles/distributor_admin_cannot_drive_kit_lifecycle
        """
        site = create_site(api, delivery_mode="LINE_SIDE")
        part = create_part(api, unit_price_cents=100, total_stock_qty=100)
        job = create_kit_job(api, site["id"], [part["id"]], qty_per_part=1,
                             kit_count=1)
        resp = api.start_picking(job["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
