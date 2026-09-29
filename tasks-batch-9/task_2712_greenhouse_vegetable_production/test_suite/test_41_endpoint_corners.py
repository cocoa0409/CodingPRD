"""Endpoint-shape corners: the allocation run's ordered array, conditional actions,
computed reads and the pagination contract on a collection listing.
"""

from test_helpers import (
    CLOCK_EPOCH,
    TEST_USERS,
    ApiErrorId,
    assert_four_decimal_places,
    assert_money,
    assert_round_then_sum_baseline,
    create_bio_control_release_payload,
    create_commitment_week,
    create_crop_cycle,
    create_retail_program,
    create_scout_worker,
    create_variety,
    create_zone,
    file_observation,
    find_allocations,
    make_ipm_scout_headers,
    read_lot,
    read_week,
    read_zone,
    run_allocation,
    set_clock,
    setup_cold_held_lot,
    setup_precooled_lot,
    transition_crop_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]
QI = TEST_USERS["quality_inspector_headers"]


def test_allocation_run_returns_every_week_it_evaluated_in_priority_order(api):
    """PRD §3.10: "The run returns every week it evaluated, in the same `priority_rank` ascending then program `created_at` ascending order, with `allocated_lbs`, `fill_rate_pct`, `provisional_shortfall_lbs` and `provisional_penalty_usd` all recomputed."

    Design: Corner/endpoints/allocation_run_returns_every_affected_week_in_one_ordered_array
    """
    state = setup_cold_held_lot(
        production_clock="2026-08-31T06:00:00Z",
        lot_overrides={"harvest_date": "2026-08-31", "gross_weight_lbs": 2000.00},
        grade_overrides={"grade_a_lbs": 1200.00, "grade_b_lbs": 700.00, "cull_lbs": 100.00},
    )
    first_program = create_retail_program(
        program_code="BK-1", weekly_commitment_lbs=500.00, priority_rank=1
    )
    second_program = create_retail_program(
        retailer_name="Southgate Markets",
        program_code="BK-2",
        weekly_commitment_lbs=500.00,
        price_per_lb_usd=1.70,
        shortfall_penalty_per_lb_usd=0.30,
        priority_rank=2,
    )
    first_week = create_commitment_week(
        first_program["id"], iso_week="2026-W36", week_start_date="2026-08-31"
    )
    second_week = create_commitment_week(
        second_program["id"], iso_week="2026-W36", week_start_date="2026-08-31"
    )

    response = api.create_allocation_run({"week_start_date": "2026-08-31"}, GM)
    evaluated = validate_success(response, 200)

    assert response.json()["response_type"] == "array"
    assert len(evaluated) == 2, f"both weeks were evaluated, got {len(evaluated)}"
    assert evaluated[0]["id"] == first_week["id"], (
        "the priority_rank 1 week is returned first"
    )
    assert evaluated[1]["id"] == second_week["id"], (
        "the priority_rank 2 week is returned second"
    )
    assert evaluated[0]["status"] == "ALLOCATED"
    assert evaluated[1]["status"] == "ALLOCATED"
    assert_money(evaluated[0]["allocated_lbs"], 500.00, "first week allocated_lbs")
    assert_money(evaluated[1]["allocated_lbs"], 500.00, "second week allocated_lbs")

    lot = read_lot(state["lot"]["id"])
    assert_money(lot["allocated_a_lbs"], 1000.00, "allocated_a_lbs")
    assert_money(lot["available_a_lbs"], 200.00, "available_a_lbs")

    rows = find_allocations()
    assert len(rows) == 2, f"one allocation row per week, got {len(rows)}"
    assert all(row["status"] == "PROVISIONAL" for row in rows), (
        "a freshly minted allocation row is PROVISIONAL"
    )
    assert {row["commitment_week_id"] for row in rows} == {
        first_week["id"],
        second_week["id"],
    }


def test_release_request_citing_an_observation_from_another_compartment_is_rejected(api):
    """PRD §3.6: "The justifying observation must have `release_required` true, or the request is rejected with `ERR_OBSERVATION_BELOW_THRESHOLD`; only if it passes that test is its compartment compared with the request's `zone_id`, a disagreement being rejected with `ERR_OBSERVATION_ZONE_MISMATCH`."

    Design: Corner/endpoints/bio_control_release_citing_an_observation_from_another_zone_is_rejected
    """
    set_clock("2026-08-06T00:00:00Z")
    zone_a = create_zone(code="ZC-41A")
    zone_b = create_zone(code="ZC-41B")
    variety = create_variety()
    cycle_a = create_crop_cycle(zone_a["id"], variety["id"])
    transition_crop_cycle(cycle_a["id"], "TRANSPLANTED")
    cycle_b = create_crop_cycle(zone_b["id"], variety["id"])
    transition_crop_cycle(cycle_b["id"], "TRANSPLANTED")
    scout = create_scout_worker()
    observation = file_observation(
        zone_b["id"],
        cycle_b["id"],
        scout["id"],
        observed_at="2026-08-06T08:00:00Z",
        pest_code="WHITEFLY",
        pest_count_per_plant=0.800,
    )
    assert observation["release_required"] is True, (
        "the justifying round must be at or above threshold for this corner"
    )

    response = api.create_bio_control_release(
        create_bio_control_release_payload(zone_a["id"], observation["id"]),
        make_ipm_scout_headers(scout["id"]),
    )

    validate_error(response, ApiErrorId.ERR_OBSERVATION_ZONE_MISMATCH.value)

    _, meta = validate_paginated(api.list_bio_control_releases(GM))
    assert meta["total_count"] == 0, "the rejected request must not write a release row"
    assert read_zone(zone_a["id"])["ipm_posture"] == "NORMAL", (
        "the compartment that was never scouted keeps a NORMAL pest gate"
    )


def test_week_cannot_ship_on_provisional_pounds_alone(api):
    """PRD §3.10: "At least one allocation row on the week must be `CONFIRMED`, or the request is rejected with `ERR_NO_CONFIRMED_ALLOCATIONS`."

    Design: Corner/endpoints/commitment_week_ship_without_a_confirmed_allocation_is_rejected
    """
    setup_precooled_lot(
        production_clock="2026-08-31T06:00:00Z",
        lot_overrides={"harvest_date": "2026-08-31", "gross_weight_lbs": 2000.00},
        grade_overrides={"grade_a_lbs": 1200.00, "grade_b_lbs": 700.00, "cull_lbs": 100.00},
    )
    program = create_retail_program(
        program_code="CA-1", weekly_commitment_lbs=1000.00, priority_rank=1
    )
    week = create_commitment_week(
        program["id"], iso_week="2026-W36", week_start_date="2026-08-31"
    )

    evaluated = run_allocation("2026-08-31")
    assert evaluated[0]["status"] == "ALLOCATED", (
        f"the week must be ALLOCATED before shipping is attempted, got {evaluated[0]['status']}"
    )
    rows = find_allocations(commitment_week_id=week["id"])
    assert all(row["status"] == "PROVISIONAL" for row in rows), (
        "a merely pre-cooled lot cannot have its rows confirmed, so they stay PROVISIONAL"
    )

    response = api.transition_commitment_week(
        week["id"], {"to_status": "SHIPPED", "shipped_at": "2026-09-01T08:00:00Z"}, QI
    )

    validate_error(response, ApiErrorId.ERR_NO_CONFIRMED_ALLOCATIONS.value)

    after = read_week(week["id"])
    assert after["status"] == "ALLOCATED", (
        f"the rejected shipment leaves the week ALLOCATED, got {after['status']}"
    )
    assert_money(after["shipped_lbs"], 0.00, "shipped_lbs")
    assert after["shipped_at"] is None, "nothing shipped, so shipped_at stays null"


def test_crop_cycle_read_exposes_each_weekly_yield_figure_rounded_on_its_own(api):
    """PRD §3.2: "Third, each element of `expected_weekly_yield_lbs` is the corresponding element of the cultivar's `yield_curve_lbs_per_sqft`, multiplied by `area_sqft`, multiplied by `density_factor`, and rounded half up to two decimal places — **each week is rounded before anything is summed**."

    Design: Corner/endpoints/crop_cycle_read_exposes_the_computed_weekly_yield_curve
    """
    set_clock(CLOCK_EPOCH)
    zone = create_zone(code="ZC-43", area_sqft=9450)
    variety = create_variety(
        plant_density_per_sqft=0.24,
        yield_curve_lbs_per_sqft=[0.4, 0.8, 1.1, 1.3, 1.3, 1.2, 1.0, 0.9, 0.7, 0.5],
    )
    cycle = create_crop_cycle(
        zone["id"], variety["id"], transplant_date="2026-08-03", plants_transplanted=2157
    )

    fetched = validate_success(api.get_crop_cycle(cycle["id"], GM), 200)

    assert_four_decimal_places(fetched["density_factor"], 0.9511, "density_factor")
    expected_weekly = [
        3595.16,
        7190.32,
        9886.68,
        11684.26,
        11684.26,
        10785.47,
        8987.90,
        8089.11,
        6291.53,
        4493.95,
    ]
    weekly = fetched["expected_weekly_yield_lbs"]
    assert len(weekly) == len(expected_weekly), (
        f"one figure per production week, expected {len(expected_weekly)}, got {len(weekly)}"
    )
    for index, expected in enumerate(expected_weekly):
        assert_money(weekly[index], expected, f"expected_weekly_yield_lbs[{index}]")


def test_baseline_total_yield_is_the_sum_of_the_already_rounded_weeks(api):
    """PRD §3.2: "Fourth, `baseline_total_yield_lbs` is the sum of those already-rounded weekly figures, itself rounded half up to two decimal places."

    Design: Corner/endpoints/crop_cycle_read_exposes_the_computed_weekly_yield_curve
    """
    set_clock(CLOCK_EPOCH)
    zone = create_zone(code="ZC-43", area_sqft=9450)
    variety = create_variety(
        plant_density_per_sqft=0.24,
        yield_curve_lbs_per_sqft=[0.4, 0.8, 1.1, 1.3, 1.3, 1.2, 1.0, 0.9, 0.7, 0.5],
    )
    cycle = create_crop_cycle(
        zone["id"], variety["id"], transplant_date="2026-08-03", plants_transplanted=2157
    )

    fetched = validate_success(api.get_crop_cycle(cycle["id"], GM), 200)

    assert_money(fetched["baseline_total_yield_lbs"], 82688.64, "baseline_total_yield_lbs")
    assert_round_then_sum_baseline(fetched)


def test_a_freshly_planned_cycle_expects_its_full_baseline_yield(api):
    """PRD §3.2: "Fifth, `expected_total_yield_lbs` is `baseline_total_yield_lbs` multiplied by the quantity one minus `pollination_haircut_pct` divided by one hundred, rounded half up to two decimal places; since `pollination_haircut_pct` is `0.00` until a pollination check moves it, a newly planned cycle's `expected_total_yield_lbs` equals its `baseline_total_yield_lbs`."

    Design: Corner/endpoints/crop_cycle_read_exposes_the_computed_weekly_yield_curve
    """
    set_clock(CLOCK_EPOCH)
    zone = create_zone(code="ZC-43", area_sqft=9450)
    variety = create_variety(
        plant_density_per_sqft=0.24,
        yield_curve_lbs_per_sqft=[0.4, 0.8, 1.1, 1.3, 1.3, 1.2, 1.0, 0.9, 0.7, 0.5],
    )
    cycle = create_crop_cycle(
        zone["id"], variety["id"], transplant_date="2026-08-03", plants_transplanted=2157
    )

    fetched = validate_success(api.get_crop_cycle(cycle["id"], GM), 200)

    assert_money(fetched["pollination_haircut_pct"], 0.00, "pollination_haircut_pct")
    assert_money(
        fetched["expected_total_yield_lbs"],
        fetched["baseline_total_yield_lbs"],
        "expected_total_yield_lbs",
    )
    assert_money(fetched["expected_total_yield_lbs"], 82688.64, "expected_total_yield_lbs")


class TestZoneListingPagination:
    """The compartment listing's page window, ordering and row counts."""

    @staticmethod
    def _three_compartments():
        set_clock(CLOCK_EPOCH)
        first = create_zone(
            code="ZC-50",
            area_sqft=9450,
            glazing_type="GLASS",
            has_thermal_screen=True,
            has_supplemental_lighting=True,
            chp_connected=True,
            hive_slot_capacity=8,
            labor_budget_usd=20000.00,
        )
        second = create_zone(
            code="ZC-51",
            area_sqft=4000,
            glazing_type="POLY",
            has_thermal_screen=False,
            has_supplemental_lighting=False,
            chp_connected=False,
            hive_slot_capacity=4,
            labor_budget_usd=8000.00,
        )
        third = create_zone(
            code="ZC-52",
            area_sqft=6000,
            glazing_type="GLASS",
            has_thermal_screen=True,
            has_supplemental_lighting=False,
            chp_connected=False,
            hive_slot_capacity=6,
            labor_budget_usd=9000.00,
        )
        return first, second, third

    def test_an_unqualified_listing_returns_ten_rows_at_most(self, api):
        """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."

        Design: Corner/endpoints/zone_list_pagination_defaults_and_upper_bound
        """
        self._three_compartments()

        rows, meta = validate_paginated(api.list_zones(GM))

        assert meta["limit"] == 10, f"limit defaults to 10, got {meta['limit']}"
        assert len(rows) == 3, (
            f"three compartments exist and all fit inside the default page, got {len(rows)}"
        )

    def test_an_unqualified_listing_starts_at_the_first_row(self, api):
        """PRD §2.3: "`offset` is the number of rows to skip before the first returned row; it defaults to 0."

        Design: Corner/endpoints/zone_list_pagination_defaults_and_upper_bound
        """
        first, _second, _third = self._three_compartments()

        rows, meta = validate_paginated(api.list_zones(GM))

        assert meta["offset"] == 0, f"offset defaults to 0, got {meta['offset']}"
        assert rows[0]["id"] == first["id"], (
            "with nothing skipped the oldest compartment heads the page"
        )

    def test_row_count_and_remainder_flag_describe_the_whole_result_set(self, api):
        """PRD §2.3: "`total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true exactly when rows remain beyond the current page."

        Design: Corner/endpoints/zone_list_pagination_defaults_and_upper_bound
        """
        self._three_compartments()

        full_rows, full_meta = validate_paginated(api.list_zones(GM))
        partial_rows, partial_meta = validate_paginated(
            api.list_zones(GM, params={"limit": 2})
        )

        assert full_meta["total_count"] == 3, (
            f"three compartments were registered, meta says {full_meta['total_count']}"
        )
        assert full_meta["has_more"] is False, "the default page holds every compartment"
        assert len(full_rows) == 3

        assert partial_meta["total_count"] == 3, (
            "the count ignores the narrower page window, "
            f"got {partial_meta['total_count']}"
        )
        assert partial_meta["has_more"] is True, (
            "a third compartment remains beyond a two-row page"
        )
        assert len(partial_rows) == 2

    def test_compartments_are_listed_oldest_first(self, api):
        """PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."

        Design: Corner/endpoints/zone_list_pagination_defaults_and_upper_bound
        """
        first, second, third = self._three_compartments()

        rows, _meta = validate_paginated(api.list_zones(GM))

        assert [row["id"] for row in rows] == [first["id"], second["id"], third["id"]], (
            "compartments come back in registration order, got "
            f"{[row['code'] for row in rows]}"
        )
