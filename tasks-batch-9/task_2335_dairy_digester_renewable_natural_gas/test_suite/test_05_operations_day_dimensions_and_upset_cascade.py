"""The independent bookkeeping and gas dimensions of an operations day, the biological
upset cascade, and the mass-control round trip through separation and reopen."""
from test_helpers import (
    ADMIN,
    FINANCE_A,
    OPERATOR,
    assert_mass_control_holds,
    book_delivery,
    close_day,
    condition_gas,
    create_active_agreement,
    create_dairy,
    create_facility,
    create_interconnect,
    create_ops_day,
    record_separation,
    set_clock,
    validate_success,
)

DAIRY_ONE = {
    "name": "Vista Verde Dairy",
    "county": "Tulare",
    "herd_size": 3000,
    "manure_management_baseline": "LAGOON",
    "haul_distance_km": 12.0,
    "annual_nitrogen_budget_kg": 18000.000,
}
DAIRY_TWO = {
    "name": "Kings River Dairy",
    "county": "Kings",
    "herd_size": 2200,
    "manure_management_baseline": "SOLID_STORAGE",
    "haul_distance_km": 30.0,
    "annual_nitrogen_budget_kg": 12000.000,
}
TERMS_ONE = {
    "minimum_total_solids_pct": 8.0,
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
    "revenue_share_pct": 0.2200,
    "revenue_share_basis": "NET",
    "curtailable": True,
}
TERMS_TWO = {
    "committed_tonnes_per_day": 120.000,
    "minimum_total_solids_pct": 6.5,
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
    "revenue_share_pct": 0.1500,
    "revenue_share_basis": "GROSS",
    "curtailable": False,
}


def _single_dairy_closed_day(with_interconnect: bool):
    set_clock("2026-08-01T00:00:00Z")
    dairy = create_dairy(**DAIRY_ONE)
    facility = create_facility()
    agreement = create_active_agreement(
        dairy["id"], facility["id"], committed_tonnes_per_day=180.000, **TERMS_ONE
    )
    if with_interconnect:
        create_interconnect(facility["id"])
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
    return {"dairy": dairy, "facility": facility, "agreement": agreement, "ops_day": ops_day}


def _conditioned_after_one_failure():
    """A day whose gas failed the sulfide screen once and then passed on retry."""
    plant = _single_dairy_closed_day(with_interconnect=True)
    condition_gas(plant["ops_day"]["id"], treated_h2s_ppm=6.0)
    plant["ops_day"] = condition_gas(plant["ops_day"]["id"], treated_h2s_ppm=3.5)
    return plant


def _upset_cascade_plant():
    """Two agreements, two days, three loads, and a close that inhibits the digester."""
    set_clock("2026-08-01T00:00:00Z")
    dairy_one = create_dairy(**DAIRY_ONE)
    dairy_two = create_dairy(**DAIRY_TWO)
    facility = create_facility()
    agreement_one = create_active_agreement(
        dairy_one["id"], facility["id"], committed_tonnes_per_day=400.000, **TERMS_ONE
    )
    agreement_two = create_active_agreement(dairy_two["id"], facility["id"], **TERMS_TWO)
    day_one = create_ops_day(facility["id"], "2026-08-03")
    day_two = create_ops_day(facility["id"], "2026-08-04")
    delivery_one = book_delivery(
        agreement_one["id"],
        day_one["id"],
        gross_tonnes=400.000,
        tare_tonnes=0.000,
        total_solids_pct=8.0,
        volatile_solids_pct_of_ts=82.0,
    )
    delivery_two = book_delivery(
        agreement_one["id"],
        day_two["id"],
        gross_tonnes=100.000,
        tare_tonnes=0.000,
        total_solids_pct=8.0,
        volatile_solids_pct_of_ts=82.0,
    )
    delivery_three = book_delivery(
        agreement_two["id"],
        day_two["id"],
        gross_tonnes=80.000,
        tare_tonnes=0.000,
        total_solids_pct=7.2,
        volatile_solids_pct_of_ts=80.0,
    )
    return {
        "dairy_one": dairy_one,
        "dairy_two": dairy_two,
        "facility": facility,
        "agreement_one": agreement_one,
        "agreement_two": agreement_two,
        "day_one": day_one,
        "day_two": day_two,
        "delivery_one": delivery_one,
        "delivery_two": delivery_two,
        "delivery_three": delivery_three,
    }


def test_01_a_closed_day_can_still_be_carrying_pipeline_quality_gas(api):
    """Bookkeeping sits at CLOSED while the gas dimension has run RAW to PIPELINE_SPEC.

    PRD: "The bookkeeping dimension `status` and the gas dimension `gas_state` then evolve independently of one another on the same row."

    Design: Difficulty/non_linear_state_machine/nlsm_ops_day_status_and_gas_state_dimensions_advance_independently
    """
    plant = _conditioned_after_one_failure()
    ops_day = validate_success(api.get_ops_day(plant["ops_day"]["id"], OPERATOR))
    assert ops_day["status"] == "CLOSED"
    assert ops_day["gas_state"] == "PIPELINE_SPEC"
    assert ops_day["conditioning_attempts"] == 2


def test_02_reopening_rewinds_the_gas_dimension_all_the_way_to_not_produced(api):
    """One reopen resets both dimensions and every reading the gas passes wrote.

    PRD: "The day moves `CLOSED → OPEN` and the gas dimension rewinds all the way to `NOT_PRODUCED`: `treated_ch4_pct`, `treated_co2_pct`, `treated_h2s_ppm`, `treated_moisture_lb_per_mmscf`, `pipeline_hhv_btu_per_scf` and `offspec_reason` are cleared to null, `pipeline_gas_scf` and `pipeline_gas_mmbtu` return to 0.000, and `conditioning_attempts` resets to 0."

    Design: Difficulty/non_linear_state_machine/nlsm_ops_day_status_and_gas_state_dimensions_advance_independently
    """
    plant = _conditioned_after_one_failure()

    ops_day = validate_success(
        api.reopen_ops_day(
            plant["ops_day"]["id"],
            {"reason": "Chromatograph recalibration invalidated the August 3 gas analysis"},
            OPERATOR,
        )
    )
    assert ops_day["status"] == "OPEN"
    assert ops_day["gas_state"] == "NOT_PRODUCED"
    assert ops_day["conditioning_attempts"] == 0
    assert ops_day["reopen_count"] == 1
    assert ops_day["offspec_reason"] is None
    assert ops_day["treated_h2s_ppm"] is None
    assert ops_day["pipeline_gas_scf"] == 0.000
    assert ops_day["pipeline_gas_mmbtu"] == 0.000
    assert ops_day["separation_recorded"] is False

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["unseparated_manure_tonnes"] == 150.000
    assert facility["mass_control_residual_tonnes"] == 0.000


def test_03_an_inhibited_close_drives_the_facility_into_upset(api):
    """Severe acidity on top of a ten-percent overload scores four stress points.

    PRD: "A close producing `INHIBITED` moves the posture to `UPSET` from either `STABLE` or `WATCH`."

    Design: Difficulty/transitive_cascade/tc_inhibited_close_upsets_facility_suspends_curtailable_agreement_cancels_open_delivery_suspends_dairy
    """
    plant = _upset_cascade_plant()

    day_one = validate_success(
        api.close_ops_day(
            plant["day_one"]["id"],
            {
                "avg_digester_temp_c": 38.4,
                "temp_excursion_minutes": 15,
                "vfa_mg_per_l": 3600.0,
                "alkalinity_mg_per_l": 8000.0,
                "raw_biogas_scf": 40000.000,
                "raw_ch4_pct": 62.0,
                "raw_co2_pct": 36.5,
                "raw_h2s_ppm": 1800.0,
                "raw_moisture_lb_per_mmscf": 120.0,
            },
            OPERATOR,
        )
    )
    assert day_one["status"] == "CLOSED"
    assert day_one["organic_loading_rate"] == 4.373
    assert day_one["vfa_alkalinity_ratio"] == 0.450
    assert day_one["stress_points"] == 4
    assert day_one["stability_status"] == "INHIBITED"

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["ops_posture"] == "UPSET"


def test_04_the_upset_cascade_spares_the_non_curtailable_agreement(api):
    """Only the curtailable agreement is swept, and only its open load is cancelled.

    PRD: "Agreements whose `curtailable` flag is false are skipped and remain `ACTIVE` — that is the whole point of the flag."

    Design: Difficulty/transitive_cascade/tc_inhibited_close_upsets_facility_suspends_curtailable_agreement_cancels_open_delivery_suspends_dairy
    """
    plant = _upset_cascade_plant()
    close_day(
        plant["day_one"]["id"],
        vfa_mg_per_l=3600.0,
        alkalinity_mg_per_l=8000.0,
        raw_biogas_scf=40000.000,
    )

    agreement_one = validate_success(
        api.get_agreement(plant["agreement_one"]["id"], OPERATOR)
    )
    assert agreement_one["status"] == "SUSPENDED"
    assert agreement_one["suspension_reason"] == "OPS_UPSET"
    agreement_two = validate_success(
        api.get_agreement(plant["agreement_two"]["id"], OPERATOR)
    )
    assert agreement_two["status"] == "ACTIVE"
    assert agreement_two["suspension_reason"] is None

    on_closed_day = validate_success(
        api.get_delivery(plant["delivery_one"]["id"], OPERATOR)
    )
    assert on_closed_day["status"] == "ACCEPTED"
    swept = validate_success(api.get_delivery(plant["delivery_two"]["id"], OPERATOR))
    assert swept["status"] == "CANCELLED"
    assert swept["rejection_reason"] == "AGREEMENT_SUSPENDED"
    spared = validate_success(api.get_delivery(plant["delivery_three"]["id"], OPERATOR))
    assert spared["status"] == "ACCEPTED"

    day_two = validate_success(api.get_ops_day(plant["day_two"]["id"], OPERATOR))
    assert day_two["status"] == "OPEN"
    assert day_two["organic_loading_rate"] == 0.768

    dairy_one = validate_success(api.get_dairy(plant["dairy_one"]["id"], ADMIN))
    assert dairy_one["active_agreement_count"] == 0
    assert dairy_one["contracted_agreement_count"] == 1
    assert dairy_one["status"] == "SUSPENDED"
    dairy_two = validate_success(api.get_dairy(plant["dairy_two"]["id"], ADMIN))
    assert dairy_two["status"] == "CONTRACTED"

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["total_manure_received_tonnes"] == 480.000
    assert facility["mass_control_residual_tonnes"] == 0.000
    assert_mass_control_holds(facility)


def test_05_recording_separation_moves_tonnage_without_disturbing_the_residual(api):
    """The press splits 150 tonnes into cake and liquid and the balance still closes.

    PRD: "The conserved quantity `mass_control_residual_tonnes` is the total received less the unseparated portion less the solids produced less the liquid produced, rounded to 3 decimal places, and it must always equal exactly 0.000."

    Design: Difficulty/compensating_invariant/comp_mass_control_tonnes_return_to_zero_residual_after_separation_then_reopen
    """
    plant = _single_dairy_closed_day(with_interconnect=False)
    ops_day = record_separation(
        plant["ops_day"]["id"],
        solids_capture_pct=65.0,
        bedding_recovery_pct=70.0,
        lab_total_nitrogen_mg_per_l=1150.0,
    )
    assert ops_day["digestate_solids_tonnes"] == 26.000
    assert ops_day["digestate_liquid_tonnes"] == 124.000
    assert ops_day["bedding_recovered_tonnes"] == 18.200

    summary = validate_success(
        api.get_financial_summary(plant["facility"]["id"], FINANCE_A)
    )
    assert summary["unseparated_manure_tonnes"] == 0.000
    assert summary["mass_control_residual_tonnes"] == 0.000


def test_06_reopening_a_separated_day_returns_the_tonnage_and_the_residual(api):
    """The compensating reopen empties the digestate accounts and leaves nothing behind.

    PRD: "The facility's `unseparated_manure_tonnes`, `digestate_solids_produced_tonnes`, `digestate_liquid_produced_tonnes` and `mass_control_residual_tonnes` are recomputed, and the residual must return to exactly 0.000."

    Design: Difficulty/compensating_invariant/comp_mass_control_tonnes_return_to_zero_residual_after_separation_then_reopen
    """
    plant = _single_dairy_closed_day(with_interconnect=False)
    record_separation(
        plant["ops_day"]["id"],
        solids_capture_pct=65.0,
        bedding_recovery_pct=70.0,
        lab_total_nitrogen_mg_per_l=1150.0,
    )

    ops_day = validate_success(
        api.reopen_ops_day(
            plant["ops_day"]["id"],
            {"reason": "Separation press ticket was mis-keyed and must be re-entered"},
            OPERATOR,
        )
    )
    assert ops_day["separation_recorded"] is False
    assert ops_day["digestate_solids_tonnes"] == 0.000
    assert ops_day["digestate_liquid_tonnes"] == 0.000
    assert ops_day["bedding_recovered_tonnes"] == 0.000

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["total_manure_received_tonnes"] == 150.000
    assert facility["unseparated_manure_tonnes"] == 150.000
    assert facility["digestate_solids_produced_tonnes"] == 0.000
    assert facility["digestate_liquid_produced_tonnes"] == 0.000
    assert facility["mass_control_residual_tonnes"] == 0.000
    assert_mass_control_holds(facility)
