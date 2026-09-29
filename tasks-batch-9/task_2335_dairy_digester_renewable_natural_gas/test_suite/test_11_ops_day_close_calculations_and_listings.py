"""The daily reckoning: loading-rate aggregation over accepted loads only, the stability
score and its posture cascade, the separation divide, the day-level guards and the listings."""
from test_helpers import (
    ADMIN,
    OPERATOR,
    SCHEDULER,
    VERIFIER,
    book_delivery,
    close_day,
    create_facility,
    create_ops_day,
    setup_closed_day,
    setup_day_at_hydraulic_headroom,
    setup_open_day_with_delivery,
    setup_plant,
    setup_planned_nutrient_application,
    validate_error,
    validate_paginated,
    validate_success,
)

CANONICAL_CLOSE = {
    "avg_digester_temp_c": 38.4,
    "temp_excursion_minutes": 15,
    "vfa_mg_per_l": 2400.0,
    "alkalinity_mg_per_l": 8000.0,
    "raw_biogas_scf": 196000.000,
    "raw_ch4_pct": 62.0,
    "raw_co2_pct": 36.5,
    "raw_h2s_ppm": 1800.0,
    "raw_moisture_lb_per_mmscf": 120.0,
}

SECOND_LOAD = {
    "gross_tonnes": 100.000,
    "tare_tonnes": 0.000,
    "total_solids_pct": 7.2,
    "volatile_solids_pct_of_ts": 80.0,
}


def test_01_one_close_runs_loading_stability_and_raw_energy_in_order(api):
    """A single call produces the loading rate, the stress score and the raw energy.

    PRD: "Entering `RAW` derives `raw_hhv_btu_per_scf` as `raw_ch4_pct` divided by 100 and multiplied by the higher heating value of pure methane, 1010.0 British thermal units per standard cubic foot, rounded to 2 decimal places, and `raw_gas_mmbtu` as `raw_biogas_scf` multiplied by `raw_hhv_btu_per_scf` and divided by one million, rounded to 3 decimal places."

    Design: Corner/calculations/calc_close_produces_loading_rate_stability_and_raw_energy_in_one_pass
    """
    plant = setup_open_day_with_delivery()

    closed = validate_success(
        api.close_ops_day(plant["ops_day"]["id"], dict(CANONICAL_CLOSE), OPERATOR)
    )
    assert closed["organic_loading_rate"] == 1.640
    assert closed["vfa_alkalinity_ratio"] == 0.300
    assert closed["thermal_status"] == "IN_BAND"
    assert closed["stress_points"] == 1
    assert closed["stability_status"] == "STABLE"
    assert closed["raw_hhv_btu_per_scf"] == 626.20
    assert closed["raw_gas_mmbtu"] == 122.735

    delivery = validate_success(api.get_delivery(plant["delivery"]["id"], OPERATOR))
    assert delivery["net_tonnes"] == 150.000
    assert delivery["vs_tonnes"] == 9.840
    assert delivery["haul_tonne_km"] == 1800.00

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["ops_posture"] == "STABLE"


def test_02_rejecting_a_load_drops_it_out_of_the_loading_rate(api):
    """Two loads give 2.600 and the repudiated one takes the day back to 1.640.

    PRD: "Only deliveries on that day whose `status` is `ACCEPTED` participate; `REJECTED` and `CANCELLED` loads are excluded entirely."

    Design: Corner/calculations/calc_rejected_load_leaves_the_loading_rate_input_set
    """
    plant = setup_open_day_with_delivery()
    second = book_delivery(plant["agreement"]["id"], plant["ops_day"]["id"], **SECOND_LOAD)
    assert second["vs_tonnes"] == 5.760

    both_loads = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert both_loads["organic_loading_rate"] == 2.600

    rejected = validate_success(
        api.reject_delivery(second["id"], {"rejection_reason": "SCALE_ERROR"}, OPERATOR)
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "SCALE_ERROR"

    reread = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert reread["organic_loading_rate"] == 1.640

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["total_manure_received_tonnes"] == 150.000
    assert facility["mass_control_residual_tonnes"] == 0.000


def test_03_the_solids_tonnage_is_rounded_before_the_cake_divide(api):
    """12.00 tonnes of dry solids at thirty percent dry matter make 26.000 t of cake.

    PRD: "The total solids tonnage is the sum, over those deliveries, of each load's `net_tonnes` multiplied by its own `total_solids_pct` divided by 100, with that sum rounded to 2 decimal places."

    Design: Corner/calculations/calc_separation_rounds_total_solids_to_two_places_before_the_cake_divide
    """
    plant = setup_closed_day()

    separated = validate_success(
        api.record_separation(
            plant["ops_day"]["id"],
            {
                "solids_capture_pct": 65.0,
                "bedding_recovery_pct": 70.0,
                "lab_total_nitrogen_mg_per_l": 1150.0,
            },
            OPERATOR,
        )
    )
    assert separated["separation_recorded"] is True
    assert separated["digestate_solids_tonnes"] == 26.000
    assert separated["digestate_liquid_tonnes"] == 124.000
    assert separated["bedding_recovered_tonnes"] == 18.200

    facility = validate_success(api.get_facility(plant["facility"]["id"], OPERATOR))
    assert facility["digestate_solids_on_hand_tonnes"] == 26.000
    assert facility["digestate_liquid_on_hand_tonnes"] == 124.000
    assert facility["unseparated_manure_tonnes"] == 0.000
    assert facility["mass_control_residual_tonnes"] == 0.000


def test_04_a_ratio_landing_on_the_severe_constant_scores_two_points(api):
    """0.400 exactly is severe, and two points alone move the plant to WATCH.

    PRD: "The ratio `vfa_alkalinity_ratio` is `vfa_mg_per_l` divided by `alkalinity_mg_per_l`, rounded to 3 decimal places; it contributes two points when it is greater than or equal to 0.400, one point when it is greater than or equal to 0.300 but below 0.400, and zero points otherwise."

    Design: Corner/calculations/calc_vfa_ratio_exactly_at_the_severe_constant_scores_two_points
    """
    plant = setup_open_day_with_delivery()

    payload = dict(CANONICAL_CLOSE)
    payload["vfa_mg_per_l"] = 3200.0
    closed = validate_success(
        api.close_ops_day(plant["ops_day"]["id"], payload, OPERATOR)
    )
    assert closed["vfa_alkalinity_ratio"] == 0.400
    assert closed["thermal_status"] == "IN_BAND"
    assert closed["organic_loading_rate"] == 1.640
    assert closed["stress_points"] == 2
    assert closed["stability_status"] == "STRESSED"

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["ops_posture"] == "WATCH"


def test_05_the_close_response_itself_carries_every_derived_field(api):
    """No refresh, retry or background job stands between the close and the numbers.

    PRD: "Closing runs the loading-rate calculation first and the stability assessment second, then increments the day's `version` and the facility's `version` by one."

    Design: Corner/consistency_model/cm_close_response_already_carries_every_derived_stability_and_gas_field
    """
    plant = setup_open_day_with_delivery()

    closed = validate_success(
        api.close_ops_day(plant["ops_day"]["id"], dict(CANONICAL_CLOSE), OPERATOR)
    )
    assert closed["status"] == "CLOSED"
    assert closed["gas_state"] == "RAW"
    assert closed["organic_loading_rate"] == 1.640
    assert closed["vfa_alkalinity_ratio"] == 0.300
    assert closed["stress_points"] == 1
    assert closed["stability_status"] == "STABLE"
    assert closed["raw_hhv_btu_per_scf"] == 626.20
    assert closed["raw_gas_mmbtu"] == 122.735

    reread = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert reread["stability_status"] == "STABLE"
    facility = validate_success(api.get_facility(plant["facility"]["id"], OPERATOR))
    assert facility["ops_posture"] == "STABLE"
    assert facility["unseparated_manure_tonnes"] == 150.000
    assert facility["mass_control_residual_tonnes"] == 0.000


def test_06_a_duplicate_day_and_an_out_of_term_load_each_answer_their_own_guard(api):
    """The date pair is unique, and the term window is compared with the day's date.

    PRD: "Operations are organised around the `OperationsDay`. A `ProjectOperator` opens one by naming the `facility_id` and the calendar `ops_date`; the pair is unique, and a second attempt at the same facility and date is rejected with `ERR_OPS_DAY_EXISTS`."

    Design: Corner/validations/validation_duplicate_ops_day_and_out_of_term_delivery_both_violate
    """
    plant = setup_plant(
        agreement_overrides={
            "term_start_date": "2026-09-01",
            "term_end_date": "2027-06-30",
        }
    )
    ops_day = create_ops_day(plant["facility"]["id"], "2026-08-03")

    validate_error(
        api.create_ops_day(
            {"facility_id": plant["facility"]["id"], "ops_date": "2026-08-03"}, OPERATOR
        ),
        "ERR_OPS_DAY_EXISTS",
        409,
    )
    validate_error(
        api.create_delivery(
            {
                "agreement_id": plant["agreement"]["id"],
                "ops_day_id": ops_day["id"],
                "gross_tonnes": 150.000,
                "tare_tonnes": 0.000,
                "total_solids_pct": 8.0,
                "volatile_solids_pct_of_ts": 82.0,
            },
            OPERATOR,
        ),
        "ERR_OUTSIDE_AGREEMENT_TERM",
        422,
    )

    empty = validate_success(api.get_ops_day(ops_day["id"], OPERATOR))
    assert empty["organic_loading_rate"] == 0.000


def test_07_a_load_filling_the_hydraulic_capacity_exactly_is_accepted(api):
    """500.000 t of 500.000 t is inside the ceiling even at an OLR of 5.467.

    PRD: "Booking is gated by five business rules in the order established in §2.9: the supplying agreement must be `ACTIVE`, or the request fails with `ERR_AGREEMENT_NOT_ACTIVE`; the receiving facility's `ops_posture` must not be `UPSET`, or the request fails with `ERR_FACILITY_UPSET`; the day's `ops_date` must fall inside the inclusive term bounded by the agreement's `term_start_date` and `term_end_date`, or the request fails with `ERR_OUTSIDE_AGREEMENT_TERM`; the measured `total_solids_pct` must be greater than or equal to the agreement's `minimum_total_solids_pct`, with exact equality accepted, or the request fails with `ERR_SOLIDS_BELOW_MINIMUM`; and finally the sum of `net_tonnes` across the day's already-`ACCEPTED` deliveries plus the new load's `net_tonnes` must be less than or equal to the facility's `hydraulic_capacity_tonnes_per_day`, with equality accepted, or the request fails with `ERR_HYDRAULIC_CAPACITY_EXCEEDED`."

    Design: Corner/validations/validation_hydraulic_capacity_reached_exactly_still_accepts_the_load
    """
    plant = setup_day_at_hydraulic_headroom(350.000)

    filling_load = validate_success(
        api.create_delivery(
            {
                "agreement_id": plant["agreement"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "gross_tonnes": 150.000,
                "tare_tonnes": 0.000,
                "total_solids_pct": 8.0,
                "volatile_solids_pct_of_ts": 82.0,
            },
            OPERATOR,
        ),
        201,
    )
    assert filling_load["status"] == "ACCEPTED"
    assert filling_load["vs_tonnes"] == 9.840

    ops_day = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert ops_day["organic_loading_rate"] == 5.467

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["total_manure_received_tonnes"] == 500.000
    assert facility["mass_control_residual_tonnes"] == 0.000


def test_08_the_delivery_list_follows_the_ops_day_reference_not_the_facility(api):
    """Two loads on the third of August answer; the fourth-of-August load does not.

    PRD: "Deliveries accept `agreement_id`, `ops_day_id` and `status`."

    Design: Corner/endpoints/endpoint_delivery_list_is_scoped_by_the_ops_day_reference
    """
    plant = setup_open_day_with_delivery()
    second_day = create_ops_day(plant["facility"]["id"], "2026-08-04")
    on_day_one = book_delivery(
        plant["agreement"]["id"], plant["ops_day"]["id"], **SECOND_LOAD
    )
    on_day_two = book_delivery(
        plant["agreement"]["id"],
        second_day["id"],
        gross_tonnes=120.000,
        tare_tonnes=0.000,
        total_solids_pct=7.5,
        volatile_solids_pct_of_ts=81.0,
    )

    rows, meta = validate_paginated(
        api.list_deliveries(VERIFIER, {"ops_day_id": plant["ops_day"]["id"]})
    )
    assert meta["total_count"] == 2
    for row in rows:
        assert row["ops_day_id"] == plant["ops_day"]["id"]
    returned = {row["id"] for row in rows}
    assert returned == {plant["delivery"]["id"], on_day_one["id"]}
    assert on_day_two["id"] not in returned

    day_one = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert day_one["organic_loading_rate"] == 2.600
    day_two = validate_success(api.get_ops_day(second_day["id"], OPERATOR))
    assert day_two["organic_loading_rate"] == 1.215


def test_09_the_day_listing_reports_the_population_not_the_page(api):
    """Three days at the facility, two on the page, and has_more says so.

    PRD: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/endpoint_ops_day_listing_pages_within_the_facility_filter
    """
    facility = create_facility()
    first = create_ops_day(facility["id"], "2026-08-03")
    create_ops_day(facility["id"], "2026-08-04")
    third = create_ops_day(facility["id"], "2026-08-05")

    rows, meta = validate_paginated(
        api.list_ops_days(
            SCHEDULER, {"facility_id": facility["id"], "limit": 2, "offset": 0}
        )
    )
    assert meta["total_count"] == 3
    assert len(rows) == 2
    assert meta["has_more"] is True

    day_one = validate_success(api.get_ops_day(first["id"], SCHEDULER))
    assert day_one["status"] == "OPEN"
    assert day_one["separation_recorded"] is False
    day_three = validate_success(api.get_ops_day(third["id"], SCHEDULER))
    assert day_three["gas_state"] == "NOT_PRODUCED"


def test_10_a_second_close_on_the_same_day_is_an_invalid_transition(api):
    """CLOSED declares no close transition, so the first assessment stands.

    PRD: "**Generic state check** — the target resource is in a from-state that declares the requested transition: `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/sm_closing_an_already_closed_ops_day_returns_invalid_state
    """
    plant = setup_closed_day()
    assert plant["ops_day"]["status"] == "CLOSED"

    validate_error(
        api.close_ops_day(
            plant["ops_day"]["id"],
            {
                "avg_digester_temp_c": 39.0,
                "temp_excursion_minutes": 0,
                "vfa_mg_per_l": 2000.0,
                "alkalinity_mg_per_l": 9000.0,
                "raw_biogas_scf": 210000.000,
                "raw_ch4_pct": 63.0,
                "raw_co2_pct": 36.0,
                "raw_h2s_ppm": 1700.0,
                "raw_moisture_lb_per_mmscf": 110.0,
            },
            OPERATOR,
        ),
        "ERR_INVALID_STATE",
        409,
    )

    unchanged = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert unchanged["status"] == "CLOSED"
    assert unchanged["avg_digester_temp_c"] == 38.4
    assert unchanged["raw_gas_mmbtu"] == 122.735
    assert unchanged["stress_points"] == 1


def test_11_a_second_reopen_of_the_same_day_is_refused(api):
    """The correction loop is bounded at one round trip.

    PRD: "Reopening is permitted only when the day is `CLOSED`, no nomination on that day is `CONFIRMED` or `DELIVERED`, no credit batch of that facility in `CLAIMED`, `VERIFIED` or `ISSUED` status covers the day's `ops_date`, no nutrient application drawing on that day has reached `APPLIED`, and `reopen_count` is still below one — a second reopen attempt is rejected with `ERR_REOPEN_LIMIT_REACHED`."

    Design: Corner/state_machines/sm_second_reopen_of_the_same_ops_day_is_rejected
    """
    plant = setup_closed_day()
    reopened = validate_success(
        api.reopen_ops_day(
            plant["ops_day"]["id"], {"reason": "Scale ticket correction"}, OPERATOR
        )
    )
    assert reopened["status"] == "OPEN"
    assert reopened["reopen_count"] == 1
    close_day(plant["ops_day"]["id"])

    validate_error(
        api.reopen_ops_day(
            plant["ops_day"]["id"], {"reason": "Second correction attempt"}, OPERATOR
        ),
        "ERR_REOPEN_LIMIT_REACHED",
        422,
    )

    frozen = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert frozen["status"] == "CLOSED"
    assert frozen["gas_state"] == "RAW"
    assert frozen["reopen_count"] == 1


def test_12_the_separation_latch_blocks_a_second_run_and_a_reopen_releases_it(api):
    """Recording twice is refused, and once the flag is cleared the plan cannot commit.

    PRD: "Separation may be recorded only once per day: if `separation_recorded` is already true, the request is rejected with `ERR_SEPARATION_ALREADY_RECORDED`, and only a reopen can clear the flag."

    Design: Corner/validations/validation_separation_flag_gates_both_recording_and_applying
    """
    plant = setup_planned_nutrient_application()

    validate_error(
        api.record_separation(
            plant["ops_day"]["id"],
            {
                "solids_capture_pct": 70.0,
                "bedding_recovery_pct": 60.0,
                "lab_total_nitrogen_mg_per_l": 1200.0,
            },
            OPERATOR,
        ),
        "ERR_SEPARATION_ALREADY_RECORDED",
        409,
    )

    reopened = validate_success(
        api.reopen_ops_day(
            plant["ops_day"]["id"], {"reason": "Laboratory result superseded"}, OPERATOR
        )
    )
    assert reopened["status"] == "OPEN"
    assert reopened["separation_recorded"] is False

    validate_error(
        api.apply_nutrient_application(
            plant["application"]["id"],
            {"applicator_name": "Valley Custom Spreading"},
            OPERATOR,
        ),
        "ERR_SEPARATION_NOT_RECORDED",
        409,
    )

    still_planned = validate_success(
        api.get_nutrient_application(plant["application"]["id"], OPERATOR)
    )
    assert still_planned["status"] == "PLANNED"
    dairy = validate_success(api.get_dairy(plant["dairy"]["id"], ADMIN))
    assert dairy["pan_applied_ytd_kg"] == 0.000
