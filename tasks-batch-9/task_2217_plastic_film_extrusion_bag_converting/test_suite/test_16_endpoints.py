"""Endpoint surfaces: registry round trips, computed reads and actions."""
import pytest

from test_helpers import (
    ADMIN,
    CONVERTER,
    EXTRUDER,
    PRINTER,
    QUALITY,
    ApiErrorId,
    create_bag_lot_payload,
    create_print_press_payload,
    get_success_data,
    non_food_product_payload,
    read_bag_lot_version,
    set_logical_clock,
    setup_bag_lot_converting,
    setup_food_run_completed,
    setup_non_food_run_completed,
    setup_print_job_completed,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPrintPressRoundTrip:
    """A press has no state machine, so create, read and list is all of it."""

    def test_create_then_read_returns_the_registered_limits(self, api):
        """Every press limit posted comes back on the read.

        PRD: "A `PlantAdmin` registers each **press** with a `press_code`, a
        `cylinder_capacity` of print stations available concurrently (at least
        one), a `max_colors` limit on a single plate set (at least one)".

        Design: Corner/endpoints/print_press_create_then_read_then_list_round_trips
        """
        set_logical_clock(api, "2026-08-05T06:00:00Z")
        created = validate_success(
            api.create_print_press(create_print_press_payload(), ADMIN), 201)
        assert created["version"] == 1

        press = validate_success(api.get_print_press(created["id"], PRINTER), 200)
        assert press["cylinder_capacity"] == 8
        assert press["max_colors"] == 6
        assert press["registration_tolerance_micron"] == pytest.approx(80.0, abs=0.01)
        assert press["max_delta_e"] == pytest.approx(2.0, abs=0.01)

    def test_the_collection_read_reports_the_single_row(self, api):
        """One press means one page and nothing beyond it.

        PRD: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`."

        Design: Corner/endpoints/print_press_create_then_read_then_list_round_trips
        """
        set_logical_clock(api, "2026-08-05T06:00:00Z")
        get_success_data(api.create_print_press(create_print_press_payload(), ADMIN))

        rows, meta = validate_paginated(
            api.list_print_presses(PRINTER, params={"limit": 10, "offset": 0}))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert rows[0]["press_code"] == "PR-1"


class TestPoolBalanceComputedRead:
    """The balance projection is re-derived from the ledger, not stored blind."""

    def test_the_balance_reconciles_a_single_scrap_generation(self, api):
        """100.0 kg in and nothing out leaves 100.000 kg available.

        PRD: "`available_kg` is `cumulative_in_kg` minus `cumulative_out_kg`,
        rounded to three decimals — this is the pool's first invariant, and it
        must hold at every observable moment." And: "A dedicated computed read
        re-derives all of these from the rows and returns the reconciled pool, so
        a caller can verify the balance without trusting the stored copy."

        Design: Corner/endpoints/pool_balance_read_matches_the_ledger_derived_figures
        """
        world = setup_non_food_run_completed(api)

        balance = validate_success(
            api.get_regrind_pool_balance(world["pool"]["id"], EXTRUDER), 200)
        assert balance["available_kg"] == pytest.approx(100.000, abs=0.001)
        assert balance["cumulative_in_kg"] == pytest.approx(100.000, abs=0.001)
        assert balance["cumulative_out_kg"] == pytest.approx(0.000, abs=0.001)
        assert balance["cumulative_in_pcr_kg"] == pytest.approx(0.000, abs=0.001)
        assert balance["embedded_pcr_pct"] == pytest.approx(0.000, abs=0.001)
        assert balance["generation_count"] == 1
        assert balance["reincorporation_count"] == 0

    def test_the_single_inbound_row_is_the_runs_process_scrap(self, api):
        """The closure booked exactly one row, for exactly the scrap mass.

        PRD: "A regrind transaction is booked into the eligible pool with
        `direction` `IN` and `origin_kind` `EXTRUSION_SCRAP`, carrying `kg` equal
        to `scrap_kg`".

        Design: Corner/endpoints/pool_balance_read_matches_the_ledger_derived_figures
        """
        world = setup_non_food_run_completed(api)

        rows, meta = validate_paginated(api.list_regrind_transactions(
            EXTRUDER, params={"pool_id": world["pool"]["id"], "direction": "IN"}))
        assert meta["total_count"] == 1
        assert rows[0]["origin_kind"] == "EXTRUSION_SCRAP"
        assert rows[0]["kg"] == pytest.approx(100.000, abs=0.001)


class TestPackoutIsGatedOnTheLotVerdict:
    """A current version and a modest request are not enough on their own."""

    def test_packout_before_the_verdict_is_refused(self, api):
        """The lot is still CONVERTING with no seal panel at all.

        PRD: "the lot must be `QUALIFIED`, `CONDITIONAL` or already `PACKED`, and
        any other status is refused with `ERR_BAG_LOT_STATE_INVALID`."

        Design: Corner/endpoints/packout_on_a_lot_that_has_not_been_qualified_is_refused
        """
        world = setup_bag_lot_converting(api)
        lot_id = world["bag_lot"]["id"]
        version = read_bag_lot_version(api, lot_id)

        error = validate_error(api.packout_bag_lot(lot_id, 500, version, CONVERTER),
                               ApiErrorId.ERR_BAG_LOT_STATE_INVALID, 409)
        assert error["error_id"] != ApiErrorId.ERR_STALE_BAG_LOT_VERSION
        assert error["error_id"] != ApiErrorId.ERR_PACKOUT_EXCEEDS_UNPACKED

        lot = get_success_data(api.get_bag_lot(lot_id, CONVERTER))
        assert lot["status"] == "CONVERTING"
        assert lot["packed_bag_count"] == 0
        assert lot["packed_case_count"] == 0
        assert lot["bag_count_unpacked"] == 46000


class TestBagLotProductLink:
    """The lot's product must be the product its plate set was cut for."""

    def test_naming_an_unrelated_product_is_a_link_conflict(self, api):
        """Both rows resolve; the link between them does not cohere.

        PRD: "a lot whose `product_id` differs from the product of its print
        job's plate set is refused with `ERR_PRODUCT_MISMATCH`."

        Design: Corner/endpoints/a_bag_lot_must_name_the_same_product_as_its_print_jobs_plate_set
        """
        world = setup_print_job_completed(api)
        other = get_success_data(
            api.create_product(non_food_product_payload(), ADMIN))

        error = validate_error(api.create_bag_lot(
            create_bag_lot_payload(world["print_job"]["id"], other["id"], 1000,
                                   lot_code="BL-M"), CONVERTER),
            ApiErrorId.ERR_PRODUCT_MISMATCH, 409)
        assert error["error_id"] != ApiErrorId.ERR_PRODUCT_NOT_FOUND
        assert error["error_id"] != ApiErrorId.ERR_PRINT_JOB_NOT_FOUND

        _rows, meta = validate_paginated(api.list_bag_lots(
            CONVERTER, params={"print_job_id": world["print_job"]["id"]}))
        assert meta["total_count"] == 0


class TestScrappingARollIntoANamedPool:
    """The optional pool identifier routes the scrapped mass explicitly."""

    def test_the_roll_is_scrapped_and_its_mass_lands_in_the_pool(self, api):
        """50.0 kg of roll piles onto the 12.0 kg of process scrap.

        PRD: "Scrapping books a row with `direction` `IN` and `origin_kind`
        `ROLL_SCRAP`, an `origin_ref_id` naming the roll, and a `kg` equal to the
        roll's `net_kg`, then re-derives the pool."

        Design: Corner/endpoints/scrapping_a_wound_roll_books_its_mass_into_the_named_pool
        """
        world = setup_food_run_completed(api)
        roll = world["rolls"][3]

        scrapped = validate_success(
            api.scrap_film_roll(roll["id"], QUALITY,
                                pool_id=world["pool"]["id"]), 200)
        assert scrapped["status"] == "SCRAPPED"

        balance = get_success_data(
            api.get_regrind_pool_balance(world["pool"]["id"], QUALITY))
        assert balance["cumulative_in_kg"] == pytest.approx(62.000, abs=0.001)
        assert balance["available_kg"] == pytest.approx(62.000, abs=0.001)

    def test_the_pool_now_counts_two_inbound_generations(self, api):
        """Two IN rows, of 12.000 and 50.000 kilograms.

        PRD: "multiplied by one hundred, rounded to three decimals.
        `generation_count` counts the non-reversed inbound rows and
        `reincorporation_count` the non-reversed outbound rows."

        Design: Corner/endpoints/scrapping_a_wound_roll_books_its_mass_into_the_named_pool
        """
        world = setup_food_run_completed(api)
        get_success_data(api.scrap_film_roll(world["rolls"][3]["id"], QUALITY,
                                             pool_id=world["pool"]["id"]))

        balance = get_success_data(
            api.get_regrind_pool_balance(world["pool"]["id"], QUALITY))
        assert balance["generation_count"] == 2
        assert balance["embedded_pcr_pct"] == pytest.approx(0.000, abs=0.001)

        rows, meta = validate_paginated(api.list_regrind_transactions(
            QUALITY, params={"pool_id": world["pool"]["id"], "direction": "IN"}))
        assert meta["total_count"] == 2
        assert sorted(row["kg"] for row in rows) == [pytest.approx(12.000, abs=0.001),
                                                     pytest.approx(50.000, abs=0.001)]
