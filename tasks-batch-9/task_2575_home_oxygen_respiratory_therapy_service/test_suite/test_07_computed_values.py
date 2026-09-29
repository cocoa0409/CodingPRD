"""Computed values: qualifying groups, documentation scores, monthly allowables,
equipment selection, travel supply, route litres, malfunction tiers and risk
scores, recall deadlines and recertification due dates.

Every test in this file drives one arithmetic rule of the PRD end to end through
real HTTP and asserts the exact computed outcome: money as whole integer cents,
scores and factors as exact two-place decimals, dates as YYYY-MM-DD and computed
instants as ISO 8601 UTC with three fractional digits.
"""

from test_helpers import (
    ApiErrorId,
    BILLING_SPECIALIST,
    BRANCH_MANAGER,
    CLOCK_STARTUP_DATE,
    CLOCK_STARTUP_MONTH,
    COMPLIANCE_HOLD_THRESHOLD,
    DOCUMENTATION,
    INTAKE_COORDINATOR,
    LITERS,
    RESPIRATORY_THERAPIST,
    TRAVEL,
    VALIDITY_DAYS,
    advance_clock,
    api_client,
    assign_equipment,
    complete_in_home_setup,
    create_cmn_payload,
    create_equipment_assignment_payload,
    create_qualifying_test_payload,
    create_travel_authorization_payload,
    drive_cmn_to_active,
    file_malfunction,
    make_branch,
    make_delivery_route,
    make_equipment_unit,
    make_qualifying_test,
    make_route_stop,
    placement_for_role,
    placements_for_contract,
    publish_recall,
    read_cmn,
    read_contract,
    read_equipment_unit,
    read_patient,
    read_route,
    release_placement,
    retire_unit,
    setup_admitted_patient,
    setup_branch_with_fleet,
    setup_contract_in_service,
    setup_dispatched_setup_stop,
    setup_liquid_in_service,
    setup_open_contract_with_pool,
    setup_qualifying_study,
    update_branch_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Private composition helpers ──────────────────────


def _record_study(patient_id, **overrides):
    """Record one qualifying study and return the immutable computed row."""
    payload = create_qualifying_test_payload(patient_id, **overrides)
    return validate_success(
        api_client.create_qualifying_test(payload, INTAKE_COORDINATOR), 201
    )


def _draft_certificate(patient_id, qualifying_test_id, **overrides):
    """Draft one certificate, reading the patient's current version first so the
    stale-read token is always the live one."""
    patient = read_patient(patient_id)
    payload = create_cmn_payload(
        patient_id, qualifying_test_id, patient["version"], **overrides
    )
    return validate_success(api_client.create_cmn(payload, INTAKE_COORDINATOR), 201)


def _request_travel(contract_id, **overrides):
    """Request one travel authorisation, re-reading the contract's version so the
    optimistic-concurrency token matches the current row."""
    contract = read_contract(contract_id)
    payload = create_travel_authorization_payload(contract["version"], **overrides)
    return validate_success(
        api_client.create_travel_authorization(contract_id, payload, INTAKE_COORDINATOR),
        201,
    )


# ─── Tests ────────────────────────────────────────────


def test_partial_pressure_bands_split_group_i_group_ii_and_non_qualifying():
    """A study's qualifying group over the PaO2 axis: 55 is Group I, 56 and 59 are borderline and need a secondary finding, 60 qualifies for nothing.

    PRD: "A study is a Group I hit when either the saturation is present and is at most 88 percent, or the partial pressure is present and is at most 55 millimetres of mercury."

    Design: Corner/calculations/qualifying_group_pao2_band_boundaries
    """
    scenario = setup_admitted_patient(
        patient_overrides={
            "mrn": "MRN-0500",
            "full_name": "Zia Marchetti",
            "payer_type": "MEDICARE_NON_BID",
            "mobility_profile": "HOMEBOUND",
        }
    )
    patient_id = scenario["patient"]["id"]

    row_55 = _record_study(patient_id, spo2_percent=None, pao2_mmhg=55)
    row_56_cor = _record_study(
        patient_id, spo2_percent=None, pao2_mmhg=56, cor_pulmonale_or_edema=True
    )
    row_56_plain = _record_study(
        patient_id, spo2_percent=None, pao2_mmhg=56, cor_pulmonale_or_edema=False
    )
    row_59_cor = _record_study(
        patient_id, spo2_percent=None, pao2_mmhg=59, cor_pulmonale_or_edema=True
    )
    row_60_cor = _record_study(
        patient_id, spo2_percent=None, pao2_mmhg=60, cor_pulmonale_or_edema=True
    )
    row_54 = _record_study(patient_id, spo2_percent=None, pao2_mmhg=54)

    # 55 sits inside the inclusive Group I ceiling and needs no secondary finding.
    assert row_55["qualifying_group"] == "GROUP_I"
    assert row_54["qualifying_group"] == "GROUP_I"

    # 56 and 59 are the two ends of the inclusive borderline band.
    assert row_56_cor["qualifying_group"] == "GROUP_II"
    assert row_59_cor["qualifying_group"] == "GROUP_II"

    # The secondary finding is load-bearing only inside the band.
    assert row_56_plain["qualifying_group"] == "NON_QUALIFYING"
    assert row_60_cor["qualifying_group"] == "NON_QUALIFYING"

    # The Group I test rested on the partial-pressure disjunct alone.
    for row in (row_55, row_56_cor, row_56_plain, row_59_cor, row_60_cor, row_54):
        assert row["spo2_percent"] is None
        assert row["validity_days"] == VALIDITY_DAYS["RESTING_ROOM_AIR"]
        assert row["test_validity_expires_at"] == "2026-08-24T14:00:00.000Z"


def test_overnight_oximetry_needs_five_desaturation_minutes_and_a_ninety_day_window():
    """The desaturation-minutes conjunct binds overnight oximetry only, and the sleep family carries the long validity window.

    PRD: "For an overnight oximetry study only, that hit is additionally conditioned on the cumulative desaturation time having reached at least 5 minutes — a single momentary dip does not qualify a patient for nocturnal oxygen."

    Design: Corner/calculations/nocturnal_desat_minimum_and_sleep_validity_window
    """
    scenario = setup_admitted_patient(
        patient_overrides={
            "mrn": "MRN-0510",
            "full_name": "Arno Beck",
            "payer_type": "MEDICARE_NON_BID",
            "mobility_profile": "HOMEBOUND",
        }
    )
    patient_id = scenario["patient"]["id"]

    overnight_4 = _record_study(
        patient_id,
        test_type="NOCTURNAL_OVERNIGHT_OXIMETRY",
        spo2_percent=87,
        desat_minutes=4,
    )
    overnight_5 = _record_study(
        patient_id,
        test_type="NOCTURNAL_OVERNIGHT_OXIMETRY",
        spo2_percent=87,
        desat_minutes=5,
    )
    sleep = _record_study(patient_id, test_type="SLEEP_STUDY", spo2_percent=87)
    exercise = _record_study(patient_id, test_type="EXERCISE", spo2_percent=88)

    # 87 percent clears the saturation ceiling, but four documented minutes do not
    # clear the overnight conjunct; five do, so the boundary is inclusive.
    assert overnight_4["qualifying_group"] == "NON_QUALIFYING"
    assert overnight_5["qualifying_group"] == "GROUP_I"

    # The conjunct does not reach a sleep study, whose desaturation minutes default to 0.
    assert sleep["desat_minutes"] == 0
    assert sleep["qualifying_group"] == "GROUP_I"
    assert exercise["qualifying_group"] == "GROUP_I"

    # Both sleep-family studies get the long window; exercise is in the acute family.
    assert overnight_4["validity_days"] == VALIDITY_DAYS["NOCTURNAL_OVERNIGHT_OXIMETRY"]
    assert overnight_4["test_validity_expires_at"] == "2026-10-23T14:00:00.000Z"
    assert sleep["validity_days"] == VALIDITY_DAYS["SLEEP_STUDY"]
    assert sleep["test_validity_expires_at"] == "2026-10-23T14:00:00.000Z"
    assert exercise["validity_days"] == VALIDITY_DAYS["EXERCISE"]
    assert exercise["test_validity_expires_at"] == "2026-08-24T14:00:00.000Z"

    # The currency window is stamped independently of the group determination.
    assert overnight_5["test_validity_expires_at"] == "2026-10-23T14:00:00.000Z"


def test_documentation_score_rounds_once_on_the_final_sum():
    """The documentation score sums its six components at full precision and rounds half up to two places exactly once.

    PRD: "The six components are added together **at unlimited precision** and the sum is rounded half up to two decimal places exactly once, at the very end."

    Design: Corner/calculations/documentation_score_single_final_rounding
    """
    scenario = setup_qualifying_study(
        patient_overrides={
            "mrn": "MRN-0520",
            "full_name": "Bex Corrigan",
            "payer_type": "MEDICARE_NON_BID",
            "mobility_profile": "HOMEBOUND",
        }
    )
    patient_id = scenario["patient"]["id"]
    study_id = scenario["qualifying_test"]["id"]

    # 30 + 20 + 4.375 + 6.66666... + 10 + 0 = 71.04166...
    cert_a = _draft_certificate(
        patient_id,
        study_id,
        hours_per_day=7,
        length_of_need_months=6,
        narrative_element_count=1,
    )
    # 30 + 20 + 0.625 + 0 + 10 + 0 = exactly 60.625
    cert_b = _draft_certificate(
        patient_id,
        study_id,
        hours_per_day=1,
        length_of_need_months=6,
        narrative_element_count=0,
    )
    # 30 + 20 + 14.375 + 13.33333... + 10 + 5 = 92.70833...
    cert_c = _draft_certificate(
        patient_id,
        study_id,
        hours_per_day=23,
        length_of_need_months=12,
        narrative_element_count=2,
    )
    # Every component at its maximum: the six maxima sum to exactly 100.
    cert_d = _draft_certificate(
        patient_id,
        study_id,
        hours_per_day=24,
        length_of_need_months=12,
        narrative_element_count=3,
    )

    # Rounding the usage component to 4.38 and the narrative component to 6.67
    # before adding would have produced the wrong 71.05.
    assert cert_a["documentation_score"] == 71.04
    # Half up carries the exact half upward; banker's rounding would give 60.62.
    assert cert_b["documentation_score"] == 60.63
    assert cert_c["documentation_score"] == 92.71
    assert cert_d["documentation_score"] == 100.00

    # All four certificates share one study, so only the input-driven components move.
    for cert in (cert_a, cert_b, cert_c, cert_d):
        assert cert["qualifying_test_id"] == study_id
        assert cert["status"] == "DRAFT"


def test_monthly_allowable_counts_only_placed_equipment():
    """The monthly allowable is built from placements whose status is exactly PLACED, so a reserved unit prices at nothing until the setup completes.

    PRD: "It is built from the placements on the contract whose status is exactly `PLACED` — reserved, removed and recalled-out-of-service placements are excluded — each joined to its fleet unit by `equipment_unit_id` regardless of that unit's own current status."

    Design: Corner/calculations/monthly_allowable_counts_only_placed_equipment
    """
    scenario = setup_dispatched_setup_stop(
        roles=["PRIMARY_STATIONARY", "PORTABLE"],
        patient_overrides={
            "mrn": "MRN-0530",
            "full_name": "Cato Insua",
            "mobility_profile": "LIMITED_AMBULATORY",
        },
        cmn_overrides={"portable_prescribed": True},
    )
    contract_id = scenario["contract"]["id"]

    # Both units are already committed to this contract, but both placements are
    # still RESERVED, so nothing prices.
    reserved_contract = read_contract(contract_id)
    assert reserved_contract["monthly_allowable_cents"] == 0
    assert reserved_contract["first_service_month"] is None

    complete_in_home_setup(scenario["stop"]["id"])

    # The stationary line is round_half_up(7752 x 1.00 x 0.7358 x 0.98) == 5590 and
    # the portable line is round_half_up(7340 x 0.25 x 0.7358 x 0.98) == 1323,
    # summed only after each line is rounded to whole cents.
    placed_contract = read_contract(contract_id)
    assert placed_contract["monthly_allowable_cents"] == 5590 + 1323
    assert placed_contract["monthly_allowable_cents"] == 6913
    assert placed_contract["first_service_month"] == CLOCK_STARTUP_MONTH

    rows, meta = validate_paginated(
        api_client.list_placements(
            BILLING_SPECIALIST, params={"contract_id": contract_id, "status": "PLACED"}
        )
    )
    assert meta["total_count"] == 2
    by_role = {row["role"]: row for row in rows}
    assert by_role["PRIMARY_STATIONARY"]["equipment_unit_id"] == scenario["stationary_unit"]["id"]
    assert by_role["PORTABLE"]["equipment_unit_id"] == scenario["portable_unit"]["id"]
    for row in rows:
        assert row["placed_at"] == "2026-08-01T00:00:00.000Z"


def test_cash_basis_allowable_still_takes_the_sequestration_factor():
    """On the CASH basis the adjustment factor is 1.0000, so the class base and the role factor show through unmediated while sequestration still applies.

    PRD: "The product is then multiplied by the statutory sequestration factor of 0.98, which applies to every line without exception."

    Design: Corner/calculations/monthly_allowable_cash_basis_applies_unadjusted_constants
    """
    scenario = setup_dispatched_setup_stop(
        roles=["PRIMARY_STATIONARY", "BACKUP"],
        branch_overrides={"competitive_bid_area": False},
        unit_specs=[
            {
                "serial_number": "SC-1001",
                "model_code": "CONC-5L",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 5.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
            {
                "serial_number": "CY-3001",
                "model_code": "ECYL-M",
                "equipment_class": "COMPRESSED_CYLINDER",
                "max_continuous_lpm": 4.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
        ],
        patient_overrides={
            "mrn": "MRN-0540",
            "full_name": "Dara Nnamdi",
            "payer_type": "COMMERCIAL",
            "mobility_profile": "HOMEBOUND",
        },
        contract_overrides={"pricing_basis": "CASH"},
        stop_overrides={"cylinders_requested": 1},
    )
    contract_id = scenario["contract"]["id"]
    cylinder_unit = scenario["units"][1]

    # The stationary unit is already RESERVED for the primary role, so the BACKUP
    # role takes the compressed cylinder.
    backup = placement_for_role(contract_id, "BACKUP")
    assert backup["equipment_unit_id"] == cylinder_unit["id"]

    complete_in_home_setup(scenario["stop"]["id"])

    # round_half_up(7752 x 1.00 x 1.0000 x 0.98) == 7597 for the stationary line and
    # round_half_up(2520 x 0.10 x 1.0000 x 0.98) == 247 for the backup cylinder line;
    # an unsequestered stationary line would have been 7752.
    contract = read_contract(contract_id)
    assert contract["monthly_allowable_cents"] == 7597 + 247
    assert contract["monthly_allowable_cents"] == 7844
    assert contract["pricing_basis"] == "CASH"
    assert contract["first_service_month"] == CLOCK_STARTUP_MONTH
    assert contract["billing_status"] == "ACCRUING"


def test_equipment_selection_prefers_the_tightest_adequate_unit():
    """Selection ranks candidates by ascending stranded capacity and breaks ties on the later maintenance due date.

    PRD: "The **ranking** is designed to minimise stranded capacity: surviving candidates are ordered by the difference between the unit's rated maximum continuous flow and the prescribed flow, ascending, so the tightest adequate unit is preferred over an oversized one."

    Design: Corner/calculations/equipment_selection_prefers_tightest_adequate_unit
    """
    scenario = setup_open_contract_with_pool(
        unit_specs=[
            {
                "serial_number": "SC-A",
                "model_code": "CONC-4L",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 4.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-01-01",
            },
            {
                "serial_number": "SC-B",
                "model_code": "CONC-4L",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 4.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
            {
                "serial_number": "SC-C",
                "model_code": "CONC-9L",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 9.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2028-01-01",
            },
            {
                "serial_number": "SC-D",
                "model_code": "CONC-3L",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 3.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2026-09-01",
            },
        ],
        prescribed_lpm=3.0,
        patient_overrides={
            "mrn": "MRN-0550",
            "full_name": "Eira Sollis",
            "mobility_profile": "HOMEBOUND",
        },
    )
    contract_id = scenario["contract"]["id"]
    units = scenario["units_by_serial"]

    # SC-D strands 0.0 lpm against the 3.0 prescription, so it outranks every larger
    # unit even though its maintenance is the soonest due.
    first = assign_equipment(contract_id, "PRIMARY_STATIONARY")
    assert first["equipment_unit_id"] == units["SC-D"]["id"]

    released = release_placement(first["id"])
    assert released["status"] == "REMOVED"
    assert released["removal_reason"] == "RELEASED"
    assert read_equipment_unit(units["SC-D"]["id"])["status"] == "IN_STOCK"
    retire_unit(units["SC-D"]["id"])

    # SC-A and SC-B both strand exactly 1.0 lpm; the tie-break takes the later
    # next_pm_due_date, 2027-06-01 over 2027-01-01.
    second = assign_equipment(contract_id, "PRIMARY_STATIONARY")
    assert second["equipment_unit_id"] == units["SC-B"]["id"]

    release_placement(second["id"])
    retire_unit(units["SC-B"]["id"])

    # A's stranded 1.0 beats C's stranded 6.0, so the 9.0 lpm unit is still last.
    third = assign_equipment(contract_id, "PRIMARY_STATIONARY")
    assert third["equipment_unit_id"] == units["SC-A"]["id"]

    # Every placement created here was RESERVED and never PLACED.
    assert third["status"] == "RESERVED"
    assert read_contract(contract_id)["monthly_allowable_cents"] == 0


def test_equipment_selection_rejects_when_every_candidate_is_filtered_out():
    """Under-capacity, overdue maintenance, an open recall, a withdrawn liquid certification and a foreign branch each remove a candidate, emptying the set.

    PRD: "When the eligibility filter yields nothing at all, the request is rejected with `ERR_NO_ELIGIBLE_EQUIPMENT` and no placement row is created."

    Design: Corner/calculations/equipment_selection_excludes_ineligible_units
    """
    scenario = setup_open_contract_with_pool(
        unit_specs=[
            {
                "serial_number": "LOW-1",
                "model_code": "CONC-2L",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 2.5,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
            {
                "serial_number": "STALE-1",
                "model_code": "CONC-5L",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 5.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2026-07-15",
            },
            {
                "serial_number": "RCL-1",
                "model_code": "CONC-RECALLED",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 5.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
            {
                "serial_number": "LIQ-1",
                "model_code": "LIQ-RES",
                "equipment_class": "LIQUID_RESERVOIR",
                "max_continuous_lpm": 6.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
        ],
        prescribed_lpm=3.0,
        branch_overrides={"liquid_oxygen_certified": True},
        patient_overrides={
            "mrn": "MRN-0560",
            "full_name": "Fenn Oduya",
            "mobility_profile": "HOMEBOUND",
        },
    )
    serving_branch_id = scenario["branch"]["id"]
    contract_id = scenario["contract"]["id"]
    units = scenario["units_by_serial"]

    # A second branch holds an otherwise perfect 3.0 lpm unit.
    far_branch = make_branch(name="Sarasota", liquid_oxygen_certified=False)
    far_unit = make_equipment_unit(
        far_branch["id"],
        serial_number="FAR-1",
        model_code="CONC-3L",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=3.0,
        next_pm_due_date="2027-06-01",
    )
    assert far_unit["branch_id"] == far_branch["id"] != serving_branch_id

    # A CLASS_III notice quarantines nothing, so only the recall predicate can
    # remove the recalled unit.
    notice = publish_recall("CONC-RECALLED", "CLASS_III")
    assert notice["auto_quarantined_unit_count"] == 0
    assert notice["status"] == "OPEN"
    assert read_equipment_unit(units["RCL-1"]["id"])["status"] == "IN_STOCK"

    # Withdrawing the liquid certification retires the liquid reservoir from the
    # candidate set even though 6.0 lpm covers the prescription.
    patched = validate_success(
        api_client.update_branch(
            serving_branch_id,
            update_branch_payload(liquid_oxygen_certified=False),
            BRANCH_MANAGER,
        )
    )
    assert patched["liquid_oxygen_certified"] is False

    response = api_client.create_equipment_assignment(
        contract_id,
        create_equipment_assignment_payload("PRIMARY_STATIONARY"),
        RESPIRATORY_THERAPIST,
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_EQUIPMENT.value)
    assert placements_for_contract(contract_id) == []

    # 2.5 lpm is under capacity and 2026-07-15 is already overdue against the
    # clock's 2026-08-01, so neither of those two units survives either.
    assert units["LOW-1"]["max_continuous_lpm"] == 2.5
    assert units["STALE-1"]["next_pm_due_date"] == "2026-07-15"

    # One unit satisfying every predicate turns the same request into a placement.
    ok_unit = make_equipment_unit(
        serving_branch_id,
        serial_number="OK-1",
        model_code="CONC-35",
        equipment_class="STATIONARY_CONCENTRATOR",
        max_continuous_lpm=3.5,
        next_pm_due_date="2027-06-01",
    )
    placement = assign_equipment(contract_id, "PRIMARY_STATIONARY")
    assert placement["equipment_unit_id"] == ok_unit["id"]


def test_travel_altitude_factor_steps_on_the_ceiling_and_clamps_at_the_maximum():
    """The altitude factor steps on the ceiling of the thousand-foot quotient and is capped, driving effective flow and the whole supply waterfall.

    PRD: "Divide the gain by 1000 and take the ceiling to get the number of thousand-foot steps, multiply by 0.03, add 1.00, round half up to two decimal places, and finally cap the result at 1.30."

    Design: Corner/calculations/travel_supply_altitude_factor_step_and_ceiling
    """
    scenario = setup_contract_in_service(
        patient_overrides={
            "mrn": "MRN-0570",
            "full_name": "Gwen Prakash",
            "mobility_profile": "HOMEBOUND",
            "altitude_feet": 500,
        },
        cmn_overrides={"prescribed_lpm": 2.0},
    )
    contract_id = scenario["contract"]["id"]
    assert scenario["patient"]["altitude_feet"] == 500
    assert scenario["cmn"]["hours_per_day"] == 24

    # Gain 4000 ft divides to exactly 4.0 and the ceiling leaves it at four steps.
    trip_a = _request_travel(
        contract_id,
        destination_altitude_feet=4500,
        depart_utc="2026-08-02T00:00:00Z",
        return_utc="2026-08-02T10:00:00Z",
    )
    # One extra foot of gain pushes ceil(4.001) to five steps.
    trip_b = _request_travel(
        contract_id,
        destination_altitude_feet=4501,
        depart_utc="2026-08-04T00:00:00Z",
        return_utc="2026-08-04T10:00:00Z",
    )
    # Gain 11500 would give 1.00 + 0.36 == 1.36, and the cap takes it to 1.30.
    trip_c = _request_travel(
        contract_id,
        destination_altitude_feet=12000,
        depart_utc="2026-08-06T00:00:00Z",
        return_utc="2026-08-06T10:00:00Z",
    )

    assert trip_a["altitude_factor"] == 1.12
    assert trip_a["effective_lpm"] == 2.24
    assert trip_b["altitude_factor"] == 1.15
    assert trip_b["effective_lpm"] == 2.30
    assert trip_c["altitude_factor"] == TRAVEL["ALTITUDE_FACTOR_CAP"]
    assert trip_c["altitude_factor"] == 1.30
    assert trip_c["effective_lpm"] == 2.60

    # A 10-hour trip is at or below 24 hours, so the reserve percentage is 0.20 and
    # floor(1344 x 0.20) == 268 discards the 0.8.
    assert trip_a["base_liters"] == 1344
    assert trip_a["reserve_liters"] == 268
    assert trip_a["required_liters"] == 1612
    assert trip_a["cylinders_raw"] == 3
    assert trip_a["supply_cylinders_authorized"] == 3

    assert trip_b["base_liters"] == 1380
    assert trip_b["reserve_liters"] == 276
    assert trip_b["required_liters"] == 1656
    assert trip_b["cylinders_raw"] == 3

    assert trip_c["base_liters"] == 1560
    assert trip_c["reserve_liters"] == 312
    assert trip_c["required_liters"] == 1872
    assert trip_c["cylinders_raw"] == 3
    assert trip_c["supply_cylinders_authorized"] == 3

    # usable_hours is the trip itself, not the daily allowance: min(10, 24 x ceil(10 / 24)).
    for trip in (trip_a, trip_b, trip_c):
        assert trip["trip_hours"] == 10
        assert trip["handling_surcharge_cylinders"] == 0
        assert trip["status"] == "REQUESTED"


def test_route_litres_committed_per_stop_type_and_route_rollups():
    """Cylinder stops multiply out at 680 litres each, a portable refill commits a flat vessel and a pickup commits nothing, and the route roll-ups aggregate exactly those figures.

    PRD: "A `SETUP_DELIVERY`, `TANK_EXCHANGE` or `MAINTENANCE_SWAP` stop commits 680 litres for each E-cylinder requested — so a tank exchange requesting three cylinders commits 2040 litres, and one requesting none commits nothing."

    Design: Corner/calculations/route_liters_committed_per_stop_type_and_rollups
    """
    scenario = setup_liquid_in_service(
        stop_overrides={"cylinders_requested": 2},
        patient_overrides={"mrn": "MRN-0580", "full_name": "Hale Quintero"},
    )
    branch_id = scenario["branch"]["id"]
    contract_id = scenario["contract"]["id"]

    # A SETUP_DELIVERY takes the same cylinder branch as a TANK_EXCHANGE.
    assert scenario["stop"]["liters_committed"] == 2 * LITERS["PER_E_CYLINDER"]
    assert scenario["stop"]["liters_committed"] == 1360
    first_route = read_route(scenario["route"]["id"])
    assert first_route["total_o2_liters_committed"] == 1360

    second_route = make_delivery_route(
        branch_id,
        service_date="2026-08-02",
        shift_start_utc="2026-08-02T12:00:00Z",
        shift_end_utc="2026-08-02T22:00:00Z",
    )
    tank = make_route_stop(
        second_route["id"],
        contract_id,
        stop_type="TANK_EXCHANGE",
        window_start_utc="2026-08-02T13:00:00Z",
        window_end_utc="2026-08-02T14:00:00Z",
        service_minutes=45,
        cylinders_requested=3,
    )
    refill = make_route_stop(
        second_route["id"],
        contract_id,
        stop_type="PORTABLE_REFILL",
        window_start_utc="2026-08-02T15:00:00Z",
        window_end_utc="2026-08-02T16:00:00Z",
        service_minutes=30,
    )
    pickup = make_route_stop(
        second_route["id"],
        contract_id,
        stop_type="PICKUP",
        window_start_utc="2026-08-02T17:00:00Z",
        window_end_utc="2026-08-02T18:00:00Z",
        service_minutes=30,
    )

    assert tank["liters_committed"] == 3 * LITERS["PER_E_CYLINDER"]
    assert tank["liters_committed"] == 2040
    # The flat vessel figure does not consult cylinders_requested at all.
    assert refill["cylinders_requested"] == 0
    assert refill["liters_committed"] == LITERS["PORTABLE_REFILL_VESSEL"]
    assert refill["liters_committed"] == 1085
    # A pickup moves equipment out, so it commits no oxygen.
    assert pickup["liters_committed"] == LITERS["PICKUP"]
    assert pickup["liters_committed"] == 0

    # Sequence indices follow window_start_utc ascending.
    assert tank["sequence_index"] == 1
    assert refill["sequence_index"] == 2
    assert pickup["sequence_index"] == 3

    persisted = read_route(second_route["id"])
    assert persisted["total_o2_liters_committed"] == 2040 + 1085 + 0
    assert persisted["total_o2_liters_committed"] == 3125
    assert persisted["refill_slots_used"] == 1
    assert persisted["planned_stop_count"] == 3

    # The recomputed manifest agrees with the persisted roll-ups.
    manifest = validate_success(
        api_client.get_route_manifest(second_route["id"], BRANCH_MANAGER)
    )
    assert manifest["total_o2_liters_committed"] == 3125
    assert manifest["refill_slots_used"] == 1
    assert manifest["refill_capacity_per_day"] == 4
    assert manifest["planned_stop_count"] == 3

    # Roll-ups never cross route boundaries.
    assert read_route(scenario["route"]["id"])["total_o2_liters_committed"] == 1360

    # Scheduling the pickup moved the contract's service dimension.
    assert read_contract(contract_id)["service_status"] == "PICKUP_SCHEDULED"


def test_malfunction_tier_gap_boundaries_and_ongoing_risk_escalation():
    """The oxygen-gap boundaries at 15 and 60 minutes decide the severity tier on a benign symptom, and the same reports escalate the ongoing-surveillance risk score.

    PRD: "The tier is `TIER_1` when the symptom is `NO_FLOW` or `LOW_PURITY`, **or** the gap is 60 minutes or more."

    Design: Corner/calculations/malfunction_tier_gap_boundaries_and_ongoing_risk_escalation
    """
    scenario = setup_contract_in_service(
        roles=["PRIMARY_STATIONARY", "PORTABLE"],
        patient_overrides={
            "mrn": "MRN-0590",
            "full_name": "Ines Rovira",
            "mobility_profile": "LIMITED_AMBULATORY",
        },
        cmn_overrides={"portable_prescribed": True},
    )
    patient_id = scenario["patient"]["id"]
    contract_id = scenario["contract"]["id"]
    portable_unit_id = scenario["portable_unit"]["id"]
    portable_placement = placement_for_role(contract_id, "PORTABLE")
    stationary_placement = placement_for_role(contract_id, "PRIMARY_STATIONARY")

    # A perfect in-home assessment leaves factor_flow 20 as the only non-zero factor,
    # so the initial-assessment weighted average is 0.30 x 20 == 6.00.
    assert scenario["stop"]["safety_result"] == "PASS"
    assert scenario["patient"]["oxygen_safety_risk_score"] == 6.00
    assert scenario["patient"]["risk_variant_applied"] == "INITIAL_ASSESSMENT"

    # One minute below the TIER_2 threshold the placement stays in service.
    report_1 = file_malfunction(portable_placement["id"], "LEAK", 14)
    assert report_1["last_severity_tier"] == "TIER_3"
    assert report_1["status"] == "PLACED"
    patient_1 = read_patient(patient_id)
    assert patient_1["oxygen_safety_risk_score"] == 35.00
    assert patient_1["risk_variant_applied"] == "ONGOING_SURVEILLANCE"
    assert patient_1["compliance_hold"] is False

    # Exactly 15 minutes and 59 minutes are both inside the one TIER_2 band.
    report_2 = file_malfunction(portable_placement["id"], "LEAK", 15)
    assert report_2["last_severity_tier"] == "TIER_2"
    assert report_2["status"] == "PLACED"
    patient_2 = read_patient(patient_id)
    assert patient_2["oxygen_safety_risk_score"] == 65.00
    assert patient_2["oxygen_safety_risk_score"] < COMPLIANCE_HOLD_THRESHOLD
    assert patient_2["compliance_hold"] is False

    report_3 = file_malfunction(portable_placement["id"], "LEAK", 59)
    assert report_3["last_severity_tier"] == "TIER_2"
    patient_3 = read_patient(patient_id)
    assert patient_3["oxygen_safety_risk_score"] == 95.00
    assert patient_3["compliance_hold"] is True

    # Exactly 60 minutes forces the top tier and pulls the unit out of the home.
    report_4 = file_malfunction(portable_placement["id"], "LEAK", 60)
    assert report_4["last_severity_tier"] == "TIER_1"
    assert report_4["status"] == "REMOVED"
    assert report_4["removal_reason"] == "MALFUNCTION"
    quarantined = read_equipment_unit(portable_unit_id)
    assert quarantined["status"] == "IN_QUARANTINE"
    assert quarantined["quarantine_reason"] == "MALFUNCTION"

    after_4 = read_contract(contract_id)
    assert after_4["monthly_allowable_cents"] == 5590
    assert after_4["malfunction_count"] == 4
    assert after_4["cumulative_oxygen_gap_minutes"] == 14 + 15 + 59 + 60
    assert after_4["cumulative_oxygen_gap_minutes"] == 148
    assert read_patient(patient_id)["oxygen_safety_risk_score"] == 100.00

    # The NO_FLOW symptom alone forces the top tier on a zero-minute gap.
    report_5 = file_malfunction(stationary_placement["id"], "NO_FLOW", 0)
    assert report_5["last_severity_tier"] == "TIER_1"
    assert report_5["status"] == "REMOVED"

    after_5 = read_contract(contract_id)
    assert after_5["monthly_allowable_cents"] == 0
    assert after_5["malfunction_count"] == 5
    assert after_5["cumulative_oxygen_gap_minutes"] == 148
    assert read_patient(patient_id)["oxygen_safety_risk_score"] == 100.00

    # Both variants are reported over the one factor vector: 0.30 x 20 + 0.10 x 100
    # for the weighted average, and max(100) + 5 for the second non-zero factor,
    # capped, for the surveillance variant.
    risk = validate_success(
        api_client.get_patient_risk_assessment(patient_id, RESPIRATORY_THERAPIST)
    )
    assert risk["factor_incident"] == 100
    assert risk["factor_flow"] == 20
    assert risk["initial_assessment_score"] == 16.00
    assert risk["ongoing_surveillance_score"] == 100.00


def test_recall_remediation_deadline_by_severity_class():
    """Each recall severity offsets the remediation deadline from one issued_at, and only a Class I notice quarantines fleet units.

    PRD: "The notice opens in `OPEN` with `issued_at` stamped from the logical clock, and its `remediation_deadline_utc` is `issued_at` advanced by whole days according to severity: 5 days for `CLASS_I`, 30 days for `CLASS_II` and 90 days for `CLASS_III`."

    Design: Corner/calculations/recall_remediation_deadline_by_severity_class
    """
    scenario = setup_branch_with_fleet(
        unit_specs=[
            {
                "serial_number": "M2-1",
                "model_code": "M2",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 5.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
            {
                "serial_number": "M2-2",
                "model_code": "M2",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 5.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
            {
                "serial_number": "M2-3",
                "model_code": "M2",
                "equipment_class": "STATIONARY_CONCENTRATOR",
                "max_continuous_lpm": 5.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
            {
                "serial_number": "M3-1",
                "model_code": "M3",
                "equipment_class": "PORTABLE_CONCENTRATOR",
                "max_continuous_lpm": 3.0,
                "max_pulse_setting": 5,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
            {
                "serial_number": "M1-1",
                "model_code": "M1",
                "equipment_class": "COMPRESSED_CYLINDER",
                "max_continuous_lpm": 4.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
        ]
    )
    m2_first, m2_second, m2_retired, m3_unit, m1_unit = scenario["units"]

    retired = retire_unit(m2_retired["id"])
    assert retired["status"] == "RETIRED"

    notice_class_ii = publish_recall("M2", "CLASS_II")
    notice_class_iii = publish_recall("M3", "CLASS_III")
    notice_class_i = publish_recall("M1", "CLASS_I")

    # All three are issued at the same logical instant and offset by whole days.
    for notice in (notice_class_ii, notice_class_iii, notice_class_i):
        assert notice["issued_at"] == "2026-08-01T00:00:00.000Z"
    assert notice_class_ii["remediation_deadline_utc"] == "2026-08-31T00:00:00.000Z"
    assert notice_class_iii["remediation_deadline_utc"] == "2026-10-30T00:00:00.000Z"
    assert notice_class_i["remediation_deadline_utc"] == "2026-08-06T00:00:00.000Z"

    # The retired M2 unit is outside the affected-unit status set.
    assert notice_class_ii["affected_unit_count"] == 2
    assert notice_class_iii["affected_unit_count"] == 1
    assert notice_class_i["affected_unit_count"] == 1

    # Only CLASS_I quarantines.
    assert notice_class_ii["auto_quarantined_unit_count"] == 0
    assert notice_class_iii["auto_quarantined_unit_count"] == 0
    assert notice_class_i["auto_quarantined_unit_count"] == 1
    assert read_equipment_unit(m2_first["id"])["status"] == "IN_STOCK"
    assert read_equipment_unit(m2_second["id"])["status"] == "IN_STOCK"
    assert read_equipment_unit(m3_unit["id"])["status"] == "IN_STOCK"
    quarantined = read_equipment_unit(m1_unit["id"])
    assert quarantined["status"] == "IN_QUARANTINE"
    assert quarantined["quarantine_reason"] == "RECALL"

    # Every fresh notice opens with nothing remediated.
    for notice in (notice_class_ii, notice_class_iii, notice_class_i):
        assert notice["status"] == "OPEN"
        assert notice["remediated_unit_count"] == 0


def test_recert_due_date_takes_the_smaller_interval_and_clamps_the_month():
    """The recertification interval is the smaller of the group interval and the declared length of need, and month addition clamps to the last day of a short month.

    PRD: "The interval actually applied is the smaller of that group interval and the declared length of need — a physician who declares a 2-month need does not get a 12-month certificate."

    Design: Corner/calculations/recert_due_date_interval_floor_and_month_clamp
    """
    scenario = setup_admitted_patient(
        patient_overrides={
            "mrn": "MRN-0600",
            "full_name": "Juno Takahashi",
            "payer_type": "MEDICARE_NON_BID",
            "mobility_profile": "HOMEBOUND",
        }
    )
    patient_id = scenario["patient"]["id"]

    # The two studies differ only in saturation and the secondary finding.
    study_group_ii = make_qualifying_test(
        patient_id, spo2_percent=89, cor_pulmonale_or_edema=True
    )
    study_group_i = make_qualifying_test(patient_id, spo2_percent=87)
    assert study_group_ii["qualifying_group"] == "GROUP_II"
    assert study_group_i["qualifying_group"] == "GROUP_I"

    # A borderline study scores 24 group points, and a lifetime need earns the
    # duration points: 24 + 20 + 15 + 20 + 10 + 5 == 94.00.
    cert_group_ii = _draft_certificate(patient_id, study_group_ii["id"])
    assert cert_group_ii["documentation_score"] == 94.00
    active_group_ii = drive_cmn_to_active(cert_group_ii["id"])
    assert active_group_ii["initial_date"] == CLOCK_STARTUP_DATE
    # min(3, 99) == 3 months: a lifetime length of need does not extend the interval.
    assert active_group_ii["recert_due_date"] == "2026-11-01"

    # A Group I study would allow 12 months, but min(12, 6) takes the declared need.
    cert_six_months = _draft_certificate(
        patient_id,
        study_group_i["id"],
        form_type="RECERTIFICATION",
        length_of_need_months=6,
    )
    active_six_months = drive_cmn_to_active(cert_six_months["id"])
    assert active_six_months["initial_date"] == CLOCK_STARTUP_DATE
    assert active_six_months["recert_due_date"] == "2027-02-01"

    # Superseding does not rewrite the earlier certificate's computed due date.
    superseded = read_cmn(cert_group_ii["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["recert_due_date"] == "2026-11-01"

    # The surviving certificate's due date is still in the future, so the sweep
    # expires nothing.
    sweep = advance_clock("2026-08-31T00:00:00Z")
    assert sweep["expired_cmn_count"] == 0

    # At 2026-08-31 the study is past its 2026-08-24T14:00:00.000Z expiry but inside
    # the 15-day grace, so the currency component drops from 20 to 10 and the total
    # lands exactly on the pass threshold: 30 + 10 + 15 + 20 + 10 + 0 == 85.00.
    cert_month_end = _draft_certificate(
        patient_id,
        study_group_i["id"],
        form_type="RECERTIFICATION",
        length_of_need_months=6,
    )
    assert cert_month_end["documentation_score"] == 85.00
    assert cert_month_end["documentation_score"] == DOCUMENTATION["PASS_THRESHOLD"]

    active_month_end = drive_cmn_to_active(cert_month_end["id"])
    assert active_month_end["initial_date"] == "2026-08-31"
    # Adding six months clamps to the last day of February instead of spilling into March.
    assert active_month_end["recert_due_date"] == "2027-02-28"

    # Exactly one certificate is ACTIVE, and the patient mirrors it.
    assert read_cmn(cert_six_months["id"])["status"] == "SUPERSEDED"
    assert active_month_end["status"] == "ACTIVE"
    assert read_patient(patient_id)["current_cmn_status"] == "ACTIVE"
