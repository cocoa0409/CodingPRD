"""Pallet spec engineering constants, lifecycle, and price-index windows."""
import pytest

from test_helpers import (
    CLOCK_DEFAULT,
    PLANT,
    PRO,
    ApiErrorId,
    api_client,
    assert_pallet_spec,
    create_active_spec,
    create_lumber_index_payload,
    create_new_build_lot,
    create_seasonal_index_payload,
    create_spec,
    get_lot,
    publish_lumber_index,
    set_clock,
    setup_pricing_world,
    validate_error,
    validate_success,
)


class TestSpecCreation:

    def test_spec_creation_computes_engineering_constants(self):
        """PRD §3.1: "The `unit_cube_cuft` is the trailer cube one pallet of
        this spec occupies: the product of `length_in`, `width_in`, and
        `height_in` divided by 1,728 cubic inches per cubic foot, rounded
        half-up to 4 decimal places."
        PRD §3.1: "The `board_feet_per_pallet` derives nominal lumber
        consumption from the build: the deck takes the `board_count` multiplied
        by six-tenths, rounded up to a whole number of deck boards, and the
        remaining boards are stringers."
        PRD §3.1: "A spec is born in `DRAFT` status."
        PRD §3.1: "an optional `requires_heat_treatment_default` flag that
        defaults to false and governs whether order lines for this spec require
        heat-treated stock by default."

        Design: Corner/entities/spec_creation_computes_board_feet_and_cube
        """
        resp = api_client.create_spec(
            {
                "spec_code": "GMA-48X40-15B",
                "length_in": 48,
                "width_in": 40,
                "height_in": 6.0,
                "board_count": 15,
                "lumber_species": "PINE",
            },
            PLANT,
        )
        data = validate_success(resp, expected_status=201)
        assert_pallet_spec(data)
        # deck = ceil(15 * 0.6) = 9 boards, stringers = 6; bf = 5.25 + 10.5
        assert data["board_feet_per_pallet"] == pytest.approx(15.75, abs=1e-9), (
            f"board_feet_per_pallet must be 15.75, "
            f"got {data['board_feet_per_pallet']}"
        )
        # 48 * 40 * 6 / 1728 = 6.6667 (4dp round-half-up)
        assert data["unit_cube_cuft"] == pytest.approx(6.6667, abs=1e-9), (
            f"unit_cube_cuft must be 6.6667, got {data['unit_cube_cuft']}"
        )
        assert data["status"] == "DRAFT"
        assert data["requires_heat_treatment_default"] is False


class TestSpecLifecycle:

    def test_double_activate_spec_rejected(self):
        """PRD §3.1: "Activation by a `PlantManager` moves `DRAFT` to `ACTIVE`
        and requires the spec to currently be `DRAFT`, otherwise
        `ERR_SPEC_NOT_DRAFT`; only `ACTIVE` specs are selectable when creating
        inventory lots or order lines."

        Design: Corner/errors/error_spec_not_draft_on_double_activate
        """
        spec = create_spec()
        activate_resp = api_client.activate_spec(spec["id"], PLANT)
        validate_success(activate_resp)
        resp = api_client.activate_spec(spec["id"], PLANT)
        validate_error(resp, ApiErrorId.ERR_SPEC_NOT_DRAFT)
        assert resp.status_code == 409

    def test_retire_spec_with_available_stock_rejected(self):
        """PRD §3.1: "any inventory lot referencing the spec that is still
        `AVAILABLE` blocks retirement with `ERR_SPEC_HAS_STOCK`, and any order
        line referencing the spec in `OPEN` or `ALLOCATED` status blocks it
        with `ERR_SPEC_ON_OPEN_ORDER`."

        Design: Corner/state_machines/spec_retire_blocked_by_available_stock
        """
        spec = setup_pricing_world()
        create_new_build_lot(spec["id"], 10)
        resp = api_client.retire_spec(spec["id"], PLANT)
        validate_error(resp, ApiErrorId.ERR_SPEC_HAS_STOCK)
        assert resp.status_code == 409
        after = validate_success(api_client.get_spec(spec["id"], PLANT))
        assert after["status"] == "ACTIVE", (
            f"blocked retire must leave the spec ACTIVE, got {after['status']}"
        )


class TestLumberIndexWindows:

    def test_overlapping_same_species_window_rejected(self):
        """PRD §3.2: "Windows for the same species must not overlap — half-open
        adjacency, where one row's `effective_to` equals the next row's
        `effective_from`, is permitted — and an overlapping publication is
        rejected with `ERR_INDEX_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/lumber_index_half_open_window_overlap
        """
        publish_lumber_index(price_per_mbf_cents=400000)
        resp = api_client.create_lumber_index(
            create_lumber_index_payload(
                price_per_mbf_cents=410000,
                effective_from="2026-08-15T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z"),
            PRO,
        )
        validate_error(resp, ApiErrorId.ERR_INDEX_WINDOW_OVERLAP)
        assert resp.status_code == 409

    def test_adjacent_window_and_other_species_overlap_accepted(self):
        """PRD §3.2: "Windows for the same species must not overlap — half-open
        adjacency, where one row's `effective_to` equals the next row's
        `effective_from`, is permitted — and an overlapping publication is
        rejected with `ERR_INDEX_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/lumber_index_half_open_window_overlap
        """
        publish_lumber_index(price_per_mbf_cents=400000)
        # Half-open adjacency: existing [07-01, 09-01), new [09-01, 11-01).
        adjacent = api_client.create_lumber_index(
            create_lumber_index_payload(
                price_per_mbf_cents=420000,
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-11-01T00:00:00Z"),
            PRO,
        )
        adj_data = validate_success(adjacent, expected_status=201)
        assert adj_data["species"] == "PINE"
        # Same dates on a different species are a different resource partition.
        oak = api_client.create_lumber_index(
            create_lumber_index_payload(
                species="OAK", price_per_mbf_cents=410000,
                effective_from="2026-08-15T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z"),
            PRO,
        )
        oak_data = validate_success(oak, expected_status=201)
        assert oak_data["species"] == "OAK"


class TestHalfOpenWindowBoundary:

    def test_lot_created_one_second_before_window_end_is_priced(self):
        """PRD §3.2: "The window is half-open: a row applies at instants on or
        after `effective_from` and strictly before `effective_to`."
        PRD §3.5: "The `unit_cost_cents` is the raw cost multiplied by one plus
        the applicable overhead rate, rounded half-up to whole cents."

        Design: Difficulty/boundary_precision_check/lumber_index_half_open_window_boundary
        """
        set_clock()
        publish_lumber_index(price_per_mbf_cents=400000)
        spec = create_active_spec()
        set_clock("2026-08-31T23:59:59Z")
        resp = api_client.create_inventory_lot(
            {
                "spec_id": spec["id"],
                "origin_type": "NEW_BUILD",
                "quantity_total": 10,
                "quality_grade": "NEW",
            },
            PLANT,
        )
        lot = validate_success(resp, expected_status=201)
        # 15.75 bf * 400 cents/bf = 6300 raw; qty 10 < 100 -> 18% overhead
        assert lot["unit_cost_cents"] == 7434, (
            f"one second before effective_to the window still covers: "
            f"expected 7434, got {lot['unit_cost_cents']}"
        )

    def test_lot_created_exactly_at_window_end_rejected(self):
        """PRD §3.2: "The window is half-open: a row applies at instants on or
        after `effective_from` and strictly before `effective_to`."
        PRD §3.5: "The system locates the `LumberPriceIndex` row whose
        `species` matches the spec's `lumber_species` and whose half-open
        window covers the lot's `created_at`; when no row covers that instant
        the creation fails with `ERR_PRICE_INDEX_MISSING`."

        Design: Difficulty/boundary_precision_check/lumber_index_half_open_window_boundary
        """
        set_clock()
        publish_lumber_index(price_per_mbf_cents=400000)
        spec = create_active_spec()
        set_clock("2026-09-01T00:00:00Z")  # exactly effective_to
        resp = api_client.create_inventory_lot(
            {
                "spec_id": spec["id"],
                "origin_type": "NEW_BUILD",
                "quantity_total": 10,
                "quality_grade": "NEW",
            },
            PLANT,
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_INDEX_MISSING)
        assert resp.status_code == 422


class TestSeasonalIndex:

    def test_seasonal_band_overlap_rejected(self):
        """PRD §3.2: "Seasonal bands must not overlap regardless of
        `season_code`; a colliding band is rejected with
        `ERR_SEASON_WINDOW_OVERLAP`."

        Design: Corner/validations/seasonal_window_overlap_rejected
        """
        first = api_client.create_seasonal_index(
            create_seasonal_index_payload(), PLANT)
        validate_success(first, expected_status=201)
        resp = api_client.create_seasonal_index(
            create_seasonal_index_payload(
                season_code="LATE-SUMMER", multiplier_bp=10500,
                effective_from="2026-08-15T00:00:00Z",
                effective_to="2026-09-15T00:00:00Z"),
            PLANT,
        )
        validate_error(resp, ApiErrorId.ERR_SEASON_WINDOW_OVERLAP)
        assert resp.status_code == 409


class TestLogicalClockDefault:

    def test_default_clock_prices_lot_without_clock_call(self):
        """PRD §2.5: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; before any clock-set call has been made, every
        read of the logical clock returns exactly this default, and the server
        never falls back to wall-clock time."
        PRD §3.5: "The `unit_cost_cents` is the raw cost multiplied by one plus
        the applicable overhead rate, rounded half-up to whole cents."

        Design: Corner/endpoints/clock_default_is_2026_08_01
        """
        # Deliberately no set_clock call: the startup default must apply.
        publish_lumber_index(price_per_mbf_cents=400000)
        spec = create_active_spec()
        resp = api_client.create_inventory_lot(
            {
                "spec_id": spec["id"],
                "origin_type": "NEW_BUILD",
                "quantity_total": 10,
                "quality_grade": "NEW",
            },
            PLANT,
        )
        lot = validate_success(resp, expected_status=201)
        assert lot["unit_cost_cents"] == 7434, (
            f"default clock {CLOCK_DEFAULT} falls inside the lumber window: "
            f"expected 7434, got {lot['unit_cost_cents']}"
        )


class TestNewBuildUnitCostTiers:

    def test_new_build_unit_cost_below_tier_boundary(self):
        """PRD §3.5: "An overhead tier then applies on top, banded by the lot's
        `quantity_total`: fewer than one hundred pallets carries eighteen
        percent overhead, one hundred up to but not including five hundred
        carries twelve percent, and five hundred or more carries nine percent."

        Design: Difficulty/combinatorial_formula/new_build_cost_tier_and_index_lookup
        """
        spec = setup_pricing_world()
        assert spec["board_feet_per_pallet"] == pytest.approx(15.75, abs=1e-9)
        resp = api_client.create_inventory_lot(
            {
                "spec_id": spec["id"],
                "origin_type": "NEW_BUILD",
                "quantity_total": 99,
                "quality_grade": "NEW",
            },
            PLANT,
        )
        lot99 = validate_success(resp, expected_status=201)
        # 15.75 bf * 400 cents/bf * 1.18 = 7434 (round-half-up, tier 1)
        assert lot99["unit_cost_cents"] == 7434, (
            f"qty 99 sits in the 18% tier: expected 7434, "
            f"got {lot99['unit_cost_cents']}"
        )

    def test_new_build_unit_cost_at_tier_boundary(self):
        """PRD §3.5: "An overhead tier then applies on top, banded by the lot's
        `quantity_total`: fewer than one hundred pallets carries eighteen
        percent overhead, one hundred up to but not including five hundred
        carries twelve percent, and five hundred or more carries nine percent."

        Design: Difficulty/combinatorial_formula/new_build_cost_tier_and_index_lookup
        """
        spec = setup_pricing_world()
        resp = api_client.create_inventory_lot(
            {
                "spec_id": spec["id"],
                "origin_type": "NEW_BUILD",
                "quantity_total": 100,
                "quality_grade": "NEW",
            },
            PLANT,
        )
        lot100 = validate_success(resp, expected_status=201)
        # 15.75 * 400 * 1.12 = 7056: qty 100 belongs to the 12% tier.
        assert lot100["unit_cost_cents"] == 7056, (
            f"qty 100 crosses into the 12% tier: expected 7056, "
            f"got {lot100['unit_cost_cents']}"
        )
        lot99 = create_new_build_lot(spec["id"], 99)
        assert lot100["unit_cost_cents"] < lot99["unit_cost_cents"], (
            "tier boundary at 100 must lower the per-unit overhead rate"
        )
