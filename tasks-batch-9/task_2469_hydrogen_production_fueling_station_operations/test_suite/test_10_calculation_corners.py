"""Calculation corners: threshold edges, band edges, precision and the two-pass waterfall."""

import pytest
from test_helpers import (
    ANALYST,
    COMPLIANCE,
    HALF_LIMIT_PURITY,
    PURITY_LIMITS_PPM,
    api_client,
    certify_lot_ci,
    complete_session,
    create_power_supply_contract,
    create_production_asset,
    create_production_lot,
    create_session,
    fuel_session,
    purity_test_payload,
    read_lot,
    read_station,
    read_station_version,
    read_vessel,
    record_purity_test,
    set_clock,
    setup_operational_station,
    validate_error,
    validate_success,
)

GRID_CONTRACT = {
    "grid_ci_gco2e_per_mwh": 385000.00,
    "annual_renewable_pct": 50.000,
    "hourly_matched_renewable_pct": 50.000,
    "hourly_matching_enabled": False,
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2027-01-01T00:00:00Z",
}
QA_LOT = {
    "mass_kg": 300.000,
    "energy_consumed_kwh": 15600.0,
    "feedstock_consumed_mmbtu": 0.000,
    "carryover_kg": 0.000,
    "production_start_at": "2026-07-20T00:00:00Z",
    "production_end_at": "2026-07-21T00:00:00Z",
}
SAMPLED_AT = "2026-07-21T06:00:00Z"
AT_EVERY_LIMIT = {"sampled_at": SAMPLED_AT, **PURITY_LIMITS_PPM}
ONE_MILLI_PPM_OVER = {**HALF_LIMIT_PURITY, "carbon_monoxide_ppm": 0.201}

# One HIGH and one LOW vessel: 45.600 + 120.000 kg on site, 36.000 kg of
# high-bank deliverable mass, so the posture is OPEN.
TWO_TIER_BANK = (
    {
        "bank_tier": "HIGH",
        "water_volume_l": 600.0,
        "mawp_bar": 1000.00,
        "min_residual_bar": 200.00,
        "initial_pressure_bar": 950.00,
    },
    {
        "bank_tier": "LOW",
        "water_volume_l": 5000.0,
        "mawp_bar": 1000.00,
        "min_residual_bar": 100.00,
        "initial_pressure_bar": 300.00,
    },
)
HIGH_ONLY_BANK = (TWO_TIER_BANK[0],)

H35_BUS = {
    "vehicle_class": "TRANSIT_BUS",
    "target_pressure_class": "H35",
    "fill_protocol": "SAE_J2601_TABLE",
    "planned_kg": 24.000,
}


# ─── Recipe builders ──────────────────────────────────────────────────────


def _electrolysis_asset(asset_code, contract_code):
    """One PEM asset covered by a 50 % renewable grid contract."""
    set_clock("2026-08-01T00:00:00Z")
    asset = create_production_asset(
        asset_code=asset_code,
        pathway="PEM_ELECTROLYSIS",
        nameplate_kg_per_day=1200.000,
        ccs_capture_rate=0.0000,
        operator_org="Harbor H2 Production",
    )
    create_power_supply_contract(asset["id"], contract_code=contract_code, **GRID_CONTRACT)
    return asset


def _produced_lot(asset_id, lot_code):
    return create_production_lot(asset_id, lot_code=lot_code, **QA_LOT)


def _dispensing_station(code, name, bank=TWO_TIER_BANK, nozzle_count=2, pressure_class="H35"):
    """A dispensing-ready station whose bank is exactly the listed vessels."""
    return setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        agreement_overrides={
            "agreement_code": f"FA-{code}",
            "min_uptime_pct": 99.000,
            "penalty_per_point_cents": 250000,
            "initial_holdback_cents": 500000,
            "uptime_method": "NOZZLE_WEIGHTED",
        },
        station_overrides={
            "code": code,
            "name": name,
            "nozzle_count": nozzle_count,
            "offload_bay_count": 2,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 20.000,
            "max_pressure_class": pressure_class,
            "setback_compliant": True,
        },
        bank=bank,
        responders=2,
        vessel_due_date="2027-06-30",
    )


def _fill(station_id, ambient_temp_c, metered_kg=24.000, precool_temp_achieved_c=-20.0):
    """One complete H35 bus fill at the reference dispensing pressure."""
    session = create_session(station_id, ambient_temp_c=ambient_temp_c, **H35_BUS)
    fuel_session(session["id"], station_id, precool_temp_achieved_c)
    return complete_session(session["id"], station_id, metered_kg, 700.00, 438.00)


# ─── The fuel-cell-grade threshold ────────────────────────────────────────


def test_a_sample_at_every_limit_passes_and_a_thousandth_over_rejects_the_lot():
    """Inclusive limits: exactly at the limit passes, 0.201 ppm of carbon monoxide fails.

    "An analyte fails only when its measured value is **strictly greater** than
    its limit; a value exactly equal to the limit passes."  "Alongside the verdict,
    `purity_margin_pct` reports the tightest remaining headroom: for each measured
    analyte, subtract the measured value from its limit, divide by that limit,
    multiply by one hundred, and round half-up to three decimal places; the reported
    margin is the smallest of those per-analyte figures."  And "A `FAIL` sets
    `qa_status` to `FAILED` and takes the lot `PRODUCED → REJECTED`, a terminal state
    from which no release, certification or delivery is possible."  A second sample is
    then refused: "That check runs after the state-machine check that the lot's `status`
    is still `PRODUCED` — a lot already rejected or already released cannot accept a new
    test, and the attempt surfaces as `ERR_INVALID_STATE_TRANSITION` rather than as a
    timing complaint."

    Design: Corner/calculations/purity_verdict_at_and_just_above_the_carbon_monoxide_limit
    """
    asset = _electrolysis_asset("PA-C1-1", "PSC-C1-1")
    lot_at = _produced_lot(asset["id"], "LOT-C1-AT")
    lot_over = _produced_lot(asset["id"], "LOT-C1-OVER")

    at_limit = record_purity_test(lot_at["id"], **AT_EVERY_LIMIT)
    over_limit = record_purity_test(lot_over["id"], **ONE_MILLI_PPM_OVER)

    assert at_limit["verdict"] == "PASS"
    assert at_limit["purity_margin_pct"] == pytest.approx(0.000, abs=0.0005), (
        "every analyte sitting on its limit leaves no headroom yet breaches nothing"
    )
    assert at_limit["failing_analytes"] == []
    assert read_lot(lot_at["id"])["qa_status"] == "PASSED"
    assert read_lot(lot_at["id"])["status"] == "PRODUCED"

    assert over_limit["verdict"] == "FAIL"
    assert over_limit["failing_analytes"] == ["carbon_monoxide_ppm"], (
        "only the breaching analyte is listed"
    )
    assert over_limit["purity_margin_pct"] == pytest.approx(-0.500, abs=0.0005), (
        "(0.200 - 0.201) / 0.200 * 100 is negative, not clamped to zero"
    )
    rejected = read_lot(lot_over["id"])
    assert rejected["qa_status"] == "FAILED"
    assert rejected["status"] == "REJECTED"

    retry = api_client.create_purity_test(
        lot_over["id"], purity_test_payload(lot_over["id"], **AT_EVERY_LIMIT), ANALYST
    )

    validate_error(retry, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    assert read_lot(lot_over["id"])["status"] == "REJECTED", "the terminal state holds"


# ─── An omitted optional analyte ──────────────────────────────────────────


def test_omitting_helium_leaves_the_margin_alone_and_the_verdict_indeterminate():
    """The unmeasured analyte contributes nothing at all, neither zero nor its limit.

    "Only analytes whose value was supplied participate; an omitted optional analyte
    is excluded both from failure detection and from the margin computation."
    "Otherwise, if either `ammonia_ppm` or `helium_ppm` was omitted, the `verdict` is
    `INDETERMINATE` — nothing exceeded a limit, but the specification cannot be
    certified complete."  The lot is then neither releasable nor rejected: "Then both
    branches must be complete — `qa_status` must be `PASSED` and `ci_status` must be
    `CERTIFIED` — and a lot missing either is refused with `ERR_QA_NOT_PASSED` (HTTP
    422); the single code covers both an untested-or-indeterminate quality branch and an
    uncertified carbon branch."

    Design: Corner/calculations/purity_verdict_indeterminate_when_optional_helium_is_omitted
    """
    asset = _electrolysis_asset("PA-C2-1", "PSC-C2-1")
    lot = _produced_lot(asset["id"], "LOT-C2-1")
    request = purity_test_payload(lot["id"], **HALF_LIMIT_PURITY)
    request.pop("helium_ppm")

    test_row = validate_success(
        api_client.create_purity_test(lot["id"], request, ANALYST), expected_status=201
    )

    assert test_row["verdict"] == "INDETERMINATE"
    assert test_row["failing_analytes"] == []
    assert test_row["purity_margin_pct"] == pytest.approx(50.000, abs=0.0005), (
        "every measured analyte sits at half its limit and helium is excluded"
    )
    assert test_row["helium_ppm"] is None
    quarantined = read_lot(lot["id"])
    assert quarantined["qa_status"] == "PENDING"
    assert quarantined["status"] == "PRODUCED"

    certified = certify_lot_ci(lot["id"])
    assert certified["ci_status"] == "CERTIFIED", "the carbon branch is complete"
    refusal = api_client.release_production_lot(lot["id"], COMPLIANCE)

    validate_error(refusal, "ERR_QA_NOT_PASSED", expected_status=422)
    still_produced = read_lot(lot["id"])
    assert still_produced["status"] == "PRODUCED"
    assert still_produced["qa_status"] == "PENDING"
    assert still_produced["released_by_user_id"] is None


# ─── The precool band edge ────────────────────────────────────────────────


def test_the_precool_band_edge_and_the_protocol_relief_are_independent():
    """Ambient 30.0 is still mild, 30.1 is hot, and MC_FORMULA adds 5.0 to whichever.

    "Ambient temperature selects one of three bands, and the bands are half-open at
    the top: an `ambient_temp_c` strictly greater than 30.0 degrees Celsius is the hot
    band; otherwise, an `ambient_temp_c` strictly greater than 10.0 degrees is the mild
    band; otherwise it is the cold band."  "For an `H70` fill the table value is −40.0
    degrees in the hot band, −33.0 in the mild band and −26.0 in the cold band."
    "Under the `MC_FORMULA` protocol the requirement is relaxed by 5.0 degrees — the
    relief is added to the table value, so a warmer dispenser satisfies it."

    Design: Corner/calculations/required_precool_band_boundary_and_mc_formula_relief
    """
    scenario = _dispensing_station(
        "STN-C3", "Precool Station", bank=HIGH_ONLY_BANK, nozzle_count=4, pressure_class="H70"
    )
    station_id = scenario["station"]["id"]
    assert scenario["station"]["safety_posture"] == "OPEN"
    version_before = read_station_version(station_id)

    h70_light_duty = {
        "vehicle_class": "LIGHT_DUTY",
        "target_pressure_class": "H70",
        "planned_kg": 5.000,
    }
    mild = create_session(
        station_id, fill_protocol="SAE_J2601_TABLE", ambient_temp_c=30.0, **h70_light_duty
    )
    hot = create_session(
        station_id, fill_protocol="SAE_J2601_TABLE", ambient_temp_c=30.1, **h70_light_duty
    )
    version_after_two = read_station_version(station_id)
    relieved = create_session(
        station_id, fill_protocol="MC_FORMULA", ambient_temp_c=30.0, **h70_light_duty
    )

    assert mild["required_precool_c"] == pytest.approx(-33.0, abs=0.05), (
        "30.0 is not strictly greater than 30.0, so the band is mild"
    )
    assert hot["required_precool_c"] == pytest.approx(-40.0, abs=0.05), (
        "a tenth of a degree more crosses into the hot band"
    )
    assert relieved["required_precool_c"] == pytest.approx(-28.0, abs=0.05), (
        "the mild table value of -33.0 relaxed by 5.0"
    )
    assert [row["fill_status"] for row in (mild, hot, relieved)] == [
        "PRECOOLING",
        "PRECOOLING",
        "PRECOOLING",
    ]
    assert [row["billing_status"] for row in (mild, hot, relieved)] == [
        "PENDING",
        "PENDING",
        "PENDING",
    ]
    assert version_after_two == version_before + 2, "each reservation bumps the station"
    station = read_station(station_id)
    assert station["reserved_kg"] == pytest.approx(15.000, abs=0.001)
    assert station["available_kg"] == pytest.approx(30.600, abs=0.001)


# ─── The meter tolerance edge ─────────────────────────────────────────────


def test_a_tenth_of_a_degree_moves_the_metering_error_across_the_tolerance():
    """The unrounded correction factor decides a 1.498 versus 1.502 percent error.

    "The temperature term is the amount by which the reference temperature of 20.0
    degrees Celsius exceeds `ambient_temp_c`, multiplied by a coefficient of 0.00040
    per degree."  "That factor is used exactly as computed, with no intermediate
    rounding."  "`metering_error_pct` is `metered_kg` minus `corrected_kg`, divided by
    `corrected_kg`, multiplied by one hundred, and rounded half-up to three decimal
    places."  "`metering_within_tolerance` is true when the absolute value of
    `metering_error_pct` is no greater than the meter tolerance of 1.500 percent; a
    session sitting exactly on the tolerance is within it."

    Design: Corner/calculations/metering_error_at_the_meter_tolerance_boundary_flips_the_flag
    """
    scenario = _dispensing_station("STN-C4", "Meter Boundary Station")
    station_id = scenario["station"]["id"]

    within = _fill(station_id, -18.0)
    outside = _fill(station_id, -18.1)

    assert within["density_correction_factor"] == pytest.approx(1.0152, abs=0.0000001), (
        "1 + 38.0 * 0.00040 with a zero pressure term"
    )
    assert within["corrected_kg"] == pytest.approx(24.365, abs=0.0005), (
        "24.3648 rounded half-up to three places"
    )
    assert within["metering_error_pct"] == pytest.approx(-1.498, abs=0.0005)
    assert within["metering_within_tolerance"] is True

    assert outside["density_correction_factor"] == pytest.approx(1.01524, abs=0.0000001), (
        "the fifth decimal place survives because the factor is never rounded"
    )
    assert outside["corrected_kg"] == pytest.approx(24.366, abs=0.0005), (
        "24.36576 rounded half-up to three places"
    )
    assert outside["metering_error_pct"] == pytest.approx(-1.502, abs=0.0005)
    assert outside["metering_within_tolerance"] is False

    assert within["metered_kg"] == outside["metered_kg"], (
        "the two fills differ only in ambient temperature"
    )
    assert within["avg_dispense_pressure_bar"] == outside["avg_dispense_pressure_bar"]
    station = read_station(station_id)
    assert station["onsite_inventory_kg"] == pytest.approx(117.600, abs=0.001), (
        "165.600 less two draws of 24.000"
    )


# ─── The reforming pathway ────────────────────────────────────────────────


def test_the_reforming_feedstock_term_survives_a_ninety_percent_capture_rate():
    """Natural gas at ninety percent capture still dominates power and compression.

    "The **feedstock term** is the `feedstock_consumed_mmbtu` multiplied by 61,260
    grams of CO2e per MMBtu of natural gas, and that product multiplied by one minus
    the asset's `ccs_capture_rate`."  "Finally, the carbon intensity is the sum of the
    lot's own emissions and the carryover emissions term, divided by the lot's
    `mass_kg` multiplied by 120 megajoules per kilogram, rounded half-up to two decimal
    places."  "`ANNUAL_AVERAGE` applies when the selected contract's
    `hourly_matching_enabled` is false, and always when the provisional figure is being
    stamped; it uses `annual_renewable_pct`, crediting the annual-average renewable
    contract volume against every production hour."

    Design: Corner/calculations/carbon_intensity_smr_ccs_applies_capture_rate_and_feedstock_constant
    """
    set_clock("2026-08-01T00:00:00Z")
    asset = create_production_asset(
        asset_code="PA-C5-SMR",
        pathway="SMR_CCS",
        nameplate_kg_per_day=5000.000,
        ccs_capture_rate=0.9000,
        operator_org="Harbor H2 Reforming",
    )
    contract = create_power_supply_contract(
        asset["id"],
        contract_code="PSC-C5-1",
        **{**GRID_CONTRACT, "annual_renewable_pct": 0.000, "hourly_matched_renewable_pct": 90.000},
    )

    lot = create_production_lot(
        asset["id"],
        lot_code="LOT-C5-1",
        mass_kg=1000.000,
        energy_consumed_kwh=2000.0,
        feedstock_consumed_mmbtu=160.000,
        carryover_kg=0.000,
        production_start_at="2026-07-20T00:00:00Z",
        production_end_at="2026-07-21T00:00:00Z",
    )

    assert lot["ci_provisional_gco2e_per_mj"] == pytest.approx(17.08, abs=0.005), (
        "770000 g of power plus 980160 g of feedstock plus 300000 g of compression "
        "over 120000 MJ"
    )
    assert lot["selected_power_contract_id"] == contract["id"]

    certified = certify_lot_ci(lot["id"])

    assert certified["ci_certified_gco2e_per_mj"] == pytest.approx(17.08, abs=0.005)
    assert certified["ci_variant_applied"] == "ANNUAL_AVERAGE", (
        "the 90.000 percent hourly share is deliberately unused"
    )
    assert certified["ci_status"] == "CERTIFIED"
    assert certified["status"] == "PRODUCED"


# ─── The two-pass cascade waterfall ───────────────────────────────────────


def test_the_second_fill_splits_between_the_high_bank_and_the_reverse_order_makeup():
    """Pass one stops at the H35 terminal pressure and pass two turns the bank order round.

    "For each vessel, its floor pressure is the greater of its own `min_residual_bar`
    and the fill's terminal pressure; its usable pressure is the greater of zero and
    the amount by which its `current_pressure_bar` exceeds that floor; and its usable
    mass is that usable pressure multiplied by its `water_volume_l` and by 0.00008
    kilograms per litre per bar."  "Otherwise candidates are visited `LOW` bank first,
    then `MEDIUM`, then `HIGH`, again in `created_at` ascending order within a tier, and
    the arithmetic is identical to the first pass with one change: the floor is each
    vessel's own `min_residual_bar` rather than the fill's terminal pressure, so the
    compressor can draw a vessel down below the pressure a gravity cascade could use."

    Design: Corner/calculations/cascade_waterfall_fills_high_bank_first_then_makes_up_in_reverse_order
    """
    scenario = _dispensing_station("STN-C6", "Cascade Station")
    station_id = scenario["station"]["id"]
    high = scenario["vessels"]["HIGH"]
    low = scenario["vessels"]["LOW"]

    first = _fill(station_id, 20.0, precool_temp_achieved_c=-30.0)

    assert first["direct_cascade_kg"] == pytest.approx(24.000, abs=0.001)
    assert first["compressor_makeup_kg"] == pytest.approx(0.000, abs=0.001)
    assert len(first["cascade_plan"]) == 1
    assert first["cascade_plan"][0]["bank_tier"] == "HIGH"
    assert first["cascade_plan"][0]["vessel_id"] == high["id"]
    assert first["cascade_plan"][0]["kg"] == pytest.approx(24.000, abs=0.001)
    assert first["cascade_plan"][0]["pressure_after_bar"] == pytest.approx(450.00, abs=0.005)
    assert read_vessel(low["id"])["current_pressure_bar"] == pytest.approx(300.00, abs=0.005), (
        "the gravity pass never reached the low bank"
    )

    second = _fill(station_id, 20.0, precool_temp_achieved_c=-30.0)

    assert second["direct_cascade_kg"] == pytest.approx(0.576, abs=0.001), (
        "only the 12.00 bar between 450.00 and the 438.00 terminal remained"
    )
    assert second["compressor_makeup_kg"] == pytest.approx(23.424, abs=0.001)
    assert [row["bank_tier"] for row in second["cascade_plan"]] == ["HIGH", "LOW"], (
        "pass two visits the low bank, so the low row is appended last"
    )
    assert second["cascade_plan"][0]["kg"] == pytest.approx(0.576, abs=0.001)
    assert second["cascade_plan"][0]["pressure_after_bar"] == pytest.approx(438.00, abs=0.005)
    assert second["cascade_plan"][1]["vessel_id"] == low["id"]
    assert second["cascade_plan"][1]["kg"] == pytest.approx(23.424, abs=0.001)
    assert second["cascade_plan"][1]["pressure_after_bar"] == pytest.approx(241.44, abs=0.005), (
        "the compressor draws the low bank toward its own 100.00 bar residual"
    )

    station = read_station(station_id)
    assert station["high_bank_deliverable_kg"] == pytest.approx(11.424, abs=0.001)
    assert station["safety_posture"] == "OPEN", "11.424 kg is still above the 10.000 kg minimum"
    assert station["onsite_inventory_kg"] == pytest.approx(117.600, abs=0.001)
    assert station["total_deliverable_kg"] == pytest.approx(68.000, abs=0.001)
    assert first["billing_status"] == "PENDING"
    assert second["billing_status"] == "PENDING"
    assert station["corrected_kg_mtd"] == pytest.approx(0.000, abs=0.001), (
        "an unsettled fill is outside the month-to-date rollup"
    )
