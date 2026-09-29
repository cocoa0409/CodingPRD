"""Digestate separation output, the two plant-available-nitrogen bases, the annual
nitrogen budget ceiling and the asymmetric land-unit setback."""
from test_helpers import (
    ADMIN,
    OPERATOR,
    apply_nutrient_application,
    book_delivery,
    close_day,
    create_active_agreement,
    create_dairy,
    create_facility,
    create_ops_day,
    plan_nutrient_application,
    record_separation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"

SEPARATION_RUN = {
    "solids_capture_pct": 65.0,
    "bedding_recovery_pct": 70.0,
    "lab_total_nitrogen_mg_per_l": 1150.0,
}


def _separated_day(annual_nitrogen_budget_kg: float = 18000.000):
    """One dairy, one 150-tonne load, closed day, screw-press run recorded."""
    set_clock(CLOCK_START)
    dairy = create_dairy(
        name="Vista Verde Dairy",
        county="Tulare",
        herd_size=3000,
        manure_management_baseline="LAGOON",
        haul_distance_km=12.0,
        annual_nitrogen_budget_kg=annual_nitrogen_budget_kg,
    )
    facility = create_facility()
    agreement = create_active_agreement(
        dairy["id"],
        facility["id"],
        committed_tonnes_per_day=180.000,
        minimum_total_solids_pct=8.0,
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        revenue_share_pct=0.2200,
        revenue_share_basis="NET",
        curtailable=True,
    )
    ops_day = create_ops_day(facility["id"], "2026-08-03")
    book_delivery(
        agreement["id"],
        ops_day["id"],
        gross_tonnes=150.000,
        tare_tonnes=0.000,
        total_solids_pct=8.0,
        volatile_solids_pct_of_ts=82.0,
    )
    ops_day = close_day(ops_day["id"])
    ops_day = record_separation(ops_day["id"], **SEPARATION_RUN)
    return {
        "dairy": dairy,
        "facility": facility,
        "agreement": agreement,
        "ops_day": ops_day,
    }


def test_01_lab_and_agronomic_bases_split_on_identical_digestate(api):
    """The same cake and liquid charge different nitrogen under the two bases.

    PRD: "The agronomic basis therefore charges more nitrogen against the dairy's budget than the laboratory basis does for identical digestate."

    Design: Difficulty/dual_variant_calc/dv_plant_available_nitrogen_lab_vs_agronomic_on_identical_digestate
    """
    plant = _separated_day()
    common = {
        "application_start_date": "2026-08-10",
        "application_end_date": "2026-08-11",
        "solids_tonnes_applied": 20.000,
        "liquid_tonnes_applied": 100.000,
    }

    lab = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-101",
        pan_basis="LAB",
        **common,
    )
    agronomic = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-102",
        pan_basis="AGRONOMIC",
        **common,
    )

    assert lab["plant_available_nitrogen_kg"] == 99.650
    assert agronomic["plant_available_nitrogen_kg"] == 105.170
    assert round(
        agronomic["plant_available_nitrogen_kg"] - lab["plant_available_nitrogen_kg"], 3
    ) == 5.520


def test_02_both_bases_share_the_same_liquid_and_cake_nitrogen_totals(api):
    """Only the availability factor differs; the raw nitrogen pools are identical.

    PRD: "The nitrogen in the cake fraction, `solids_total_nitrogen_kg`, is `solids_tonnes_applied` multiplied by the standard cake nitrogen content of 5.20 kilograms per tonne, rounded to 3 decimal places."

    Design: Difficulty/dual_variant_calc/dv_plant_available_nitrogen_lab_vs_agronomic_on_identical_digestate
    """
    plant = _separated_day()
    assert plant["ops_day"]["digestate_solids_tonnes"] == 26.000
    assert plant["ops_day"]["digestate_liquid_tonnes"] == 124.000

    common = {
        "application_start_date": "2026-08-10",
        "application_end_date": "2026-08-11",
        "solids_tonnes_applied": 20.000,
        "liquid_tonnes_applied": 100.000,
    }
    lab = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-101",
        pan_basis="LAB",
        **common,
    )
    agronomic = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-102",
        pan_basis="AGRONOMIC",
        **common,
    )
    for application in (lab, agronomic):
        assert application["liquid_total_nitrogen_kg"] == 115.000
        assert application["solids_total_nitrogen_kg"] == 104.000

    dairy = validate_success(api.get_dairy(plant["dairy"]["id"], ADMIN))
    assert dairy["pan_applied_ytd_kg"] == 0.000


def test_03_an_application_landing_exactly_on_the_nitrogen_budget_is_committed(api):
    """Consuming the whole annual budget to the last gram is accepted.

    PRD: "And the dairy's `pan_applied_ytd_kg` plus this application's `plant_available_nitrogen_kg` must be less than or equal to the dairy's `annual_nitrogen_budget_kg`, with exact equality accepted; exceeding it is rejected with `ERR_NITROGEN_BUDGET_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bpc_nitrogen_budget_exact_equality_accepted_then_any_excess_rejected
    """
    plant = _separated_day(annual_nitrogen_budget_kg=99.650)
    set_clock("2026-08-06T08:00:00Z")
    first = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-101",
        application_start_date="2026-08-05",
        application_end_date="2026-08-06",
        solids_tonnes_applied=20.000,
        liquid_tonnes_applied=100.000,
        pan_basis="LAB",
    )
    assert first["plant_available_nitrogen_kg"] == 99.650

    committed = validate_success(
        api.apply_nutrient_application(
            first["id"], {"applicator_name": "Central Valley Custom Application"}, OPERATOR
        )
    )
    assert committed["status"] == "APPLIED"

    dairy = validate_success(api.get_dairy(plant["dairy"]["id"], ADMIN))
    assert dairy["pan_applied_ytd_kg"] == 99.650
    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["digestate_solids_on_hand_tonnes"] == 6.000
    assert facility["digestate_liquid_on_hand_tonnes"] == 24.000


def test_04_the_next_gram_of_nitrogen_over_the_budget_is_refused(api):
    """A second, tiny application on a spent budget is rejected and stays planned.

    PRD: "The year-to-date figure is itself the sum of `plant_available_nitrogen_kg` over that dairy's `APPLIED` applications whose `application_start_date` falls in the same calendar year as the logical clock."

    Design: Difficulty/boundary_precision_check/bpc_nitrogen_budget_exact_equality_accepted_then_any_excess_rejected
    """
    plant = _separated_day(annual_nitrogen_budget_kg=99.650)
    set_clock("2026-08-06T08:00:00Z")
    first = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-101",
        application_start_date="2026-08-05",
        application_end_date="2026-08-06",
        solids_tonnes_applied=20.000,
        liquid_tonnes_applied=100.000,
        pan_basis="LAB",
    )
    second = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-102",
        application_start_date="2026-08-07",
        application_end_date="2026-08-08",
        solids_tonnes_applied=2.000,
        liquid_tonnes_applied=2.000,
        pan_basis="LAB",
    )
    assert second["plant_available_nitrogen_kg"] == 4.905
    apply_nutrient_application(first["id"], "Central Valley Custom Application")

    validate_error(
        api.apply_nutrient_application(
            second["id"], {"applicator_name": "Central Valley Custom Application"}, OPERATOR
        ),
        "ERR_NITROGEN_BUDGET_EXCEEDED",
        422,
    )

    blocked = validate_success(api.get_nutrient_application(second["id"], OPERATOR))
    assert blocked["status"] == "PLANNED"
    dairy = validate_success(api.get_dairy(plant["dairy"]["id"], ADMIN))
    assert dairy["pan_applied_ytd_kg"] == 99.650


def test_05_the_setback_blocks_a_following_window_but_never_a_preceding_one(api):
    """Twenty-one days of soil rest guard only the trailing edge of a plan.

    PRD: "Note that the setback has no mirror image: an application placed entirely *before* an existing one is never blocked by the setback, only by the closed-interval overlap test."

    Design: Difficulty/resource_temporal_overlap/rto_land_unit_setback_is_leading_edge_only_and_keyed_on_dairy_land_unit_pair
    """
    plant = _separated_day()
    set_clock("2026-08-10T08:00:00Z")
    incumbent = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-101",
        application_start_date="2026-08-20",
        application_end_date="2026-08-21",
        solids_tonnes_applied=2.000,
        liquid_tonnes_applied=2.000,
        pan_basis="LAB",
    )
    assert incumbent["plant_available_nitrogen_kg"] == 4.905

    def plan(land_unit_code, start, end):
        return api.create_nutrient_application(
            {
                "dairy_id": plant["dairy"]["id"],
                "facility_id": plant["facility"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "land_unit_code": land_unit_code,
                "application_start_date": start,
                "application_end_date": end,
                "solids_tonnes_applied": 2.000,
                "liquid_tonnes_applied": 2.000,
                "pan_basis": "LAB",
            },
            OPERATOR,
        )

    validate_error(
        plan("LU-101", "2026-09-05", "2026-09-06"),
        "ERR_LAND_UNIT_SETBACK_CONFLICT",
        409,
    )
    earlier = validate_success(plan("LU-101", "2026-08-08", "2026-08-09"), 201)
    assert earlier["status"] == "PLANNED"
    later = validate_success(plan("LU-101", "2026-09-12", "2026-09-13"), 201)
    assert later["application_start_date"] == "2026-09-12"


def test_06_the_setback_is_keyed_on_the_dairy_and_land_unit_pair(api):
    """A neighbouring field is untouched by another field's soil-rest window.

    PRD: "Every existing application on the same combination of `dairy_id` and `land_unit_code` whose status is `PLANNED` or `APPLIED` is examined; `VOIDED` applications release their window and are excluded."

    Design: Difficulty/resource_temporal_overlap/rto_land_unit_setback_is_leading_edge_only_and_keyed_on_dairy_land_unit_pair
    """
    plant = _separated_day()
    set_clock("2026-08-10T08:00:00Z")
    plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-101",
        application_start_date="2026-08-20",
        application_end_date="2026-08-21",
        solids_tonnes_applied=2.000,
        liquid_tonnes_applied=2.000,
        pan_basis="LAB",
    )

    neighbour = validate_success(
        api.create_nutrient_application(
            {
                "dairy_id": plant["dairy"]["id"],
                "facility_id": plant["facility"]["id"],
                "ops_day_id": plant["ops_day"]["id"],
                "land_unit_code": "LU-102",
                "application_start_date": "2026-09-05",
                "application_end_date": "2026-09-06",
                "solids_tonnes_applied": 2.000,
                "liquid_tonnes_applied": 2.000,
                "pan_basis": "LAB",
            },
            OPERATOR,
        ),
        201,
    )
    assert neighbour["land_unit_code"] == "LU-102"

    rows, _meta = validate_paginated(
        api.list_nutrient_applications(
            OPERATOR, {"dairy_id": plant["dairy"]["id"], "land_unit_code": "LU-101"}
        )
    )
    assert len(rows) == 1
    dairy = validate_success(api.get_dairy(plant["dairy"]["id"], ADMIN))
    assert dairy["pan_applied_ytd_kg"] == 0.000


def test_07_committing_a_lab_basis_plan_charges_the_dairys_annual_budget(api):
    """Only the commit moves nitrogen onto the dairy and cake off the facility.

    PRD: "A successful commit increases the facility's `digestate_solids_applied_tonnes` and `digestate_liquid_applied_tonnes` by the applied amounts, decreases `digestate_solids_on_hand_tonnes` and `digestate_liquid_on_hand_tonnes` by the same amounts, and increases the dairy's `pan_applied_ytd_kg` by `plant_available_nitrogen_kg`."

    Design: Corner/calculations/calc_lab_basis_plant_available_nitrogen_charges_the_dairy_budget
    """
    plant = _separated_day()
    planned = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-07",
        application_start_date="2026-08-10",
        application_end_date="2026-08-12",
        solids_tonnes_applied=2.000,
        liquid_tonnes_applied=2.000,
        pan_basis="LAB",
    )

    committed = validate_success(
        api.apply_nutrient_application(
            planned["id"], {"applicator_name": "Valley Custom Spreading"}, OPERATOR
        )
    )
    assert committed["status"] == "APPLIED"
    assert committed["liquid_total_nitrogen_kg"] == 2.300
    assert committed["solids_total_nitrogen_kg"] == 10.400
    assert committed["plant_available_nitrogen_kg"] == 4.905

    dairy = validate_success(api.get_dairy(plant["dairy"]["id"], OPERATOR))
    assert dairy["pan_applied_ytd_kg"] == 4.905
    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["digestate_solids_on_hand_tonnes"] == 24.000
    assert facility["digestate_liquid_on_hand_tonnes"] == 122.000


def test_08_a_plan_that_outruns_the_cake_on_hand_cannot_be_committed(api):
    """Planning 40.000 tonnes is legal; spreading it against 26.000 on hand is not.

    PRD: "`solids_tonnes_applied` must be less than or equal to the facility's `digestate_solids_on_hand_tonnes` and `liquid_tonnes_applied` less than or equal to `digestate_liquid_on_hand_tonnes`, or the request is rejected with `ERR_DIGESTATE_INVENTORY_INSUFFICIENT`."

    Design: Corner/validations/validation_application_above_the_digestate_inventory_is_rejected
    """
    plant = _separated_day()
    planned = plan_nutrient_application(
        plant["dairy"]["id"],
        plant["facility"]["id"],
        plant["ops_day"]["id"],
        land_unit_code="LU-07",
        application_start_date="2026-08-10",
        application_end_date="2026-08-12",
        solids_tonnes_applied=40.000,
        liquid_tonnes_applied=2.000,
        pan_basis="LAB",
    )
    assert planned["plant_available_nitrogen_kg"] == 74.065

    validate_error(
        api.apply_nutrient_application(
            planned["id"], {"applicator_name": "Valley Custom Spreading"}, OPERATOR
        ),
        "ERR_DIGESTATE_INVENTORY_INSUFFICIENT",
        422,
    )

    blocked = validate_success(api.get_nutrient_application(planned["id"], OPERATOR))
    assert blocked["status"] == "PLANNED"
    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["digestate_solids_on_hand_tonnes"] == 26.000
    assert facility["digestate_liquid_on_hand_tonnes"] == 124.000
    dairy = validate_success(api.get_dairy(plant["dairy"]["id"], ADMIN))
    assert dairy["pan_applied_ytd_kg"] == 0.000
