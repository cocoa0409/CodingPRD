"""Three guards that only exist because the specific answer outranks the generic one.

Each of these refusals sits on a status that is not a declared source state for
the edge being attempted, so an implementation that consults only the transition
table answers all three with the same generic identifier and three catalogue
entries become unreachable. The shift endpoint is probed as a contrast pair to
fix the boundary exactly: the identical cancel on the identical `ACTIVE` entry
names the coverage guard while a row still references it and falls back to the
generic guard the moment that row is released.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_shift,
    assert_bed,
    assert_care_assignment,
    assert_induction_booking,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    bootstrap_unit,
    create_care_assignment,
    create_encounter,
    create_shift,
    get_success_data,
    reload_encounter,
    set_clock,
    setup_validated_drill,
)

CLOCK_START = "2026-08-01T05:45:00Z"
CLOCK_AFTER_THE_DRILL = "2026-08-01T06:00:00Z"
SIMULATED_DECISION_AT = "2026-08-01T05:50:00Z"
SIMULATED_INCISION_AT = "2026-08-01T06:00:00Z"
DAY_SHIFT = ("2026-08-01T05:00:00Z", "2026-08-01T15:00:00Z")
EVENING_SHIFT = ("2026-08-01T15:00:00Z", "2026-08-01T20:00:00Z")
REQUESTED_START = "2026-08-01T08:00:00Z"
HOLD_EXPIRES_AT = "2026-08-01T08:00:00Z"
THIRTY_MINUTE_GRACE_INSTANT = "2026-08-01T07:30:00Z"
BOOKING_DAY = "2026-08-01"
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
EXPECTED_LABOR_MINUTES = 60
OPEN_BUFFER = 45
STRAINED_BUFFER = 75
PROJECTED_OCCUPANCY = EXPECTED_LABOR_MINUTES + OPEN_BUFFER
TIER_ONE_ANTEPARTUM_UNITS = 0.5

WINDMERE_STAFF = {
    "charge": {
        "full_name": "Wilhelmina Ashcroft RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "ob": {
        "full_name": "Rosalind Achebe MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Emeric Szabo MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "bedside": {
        "full_name": "Ottoline Marchetti RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "spare": {
        "full_name": "Grigor Yefimov RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Leocadia Brightwater RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def three_structural_guards_probed_on_one_booking_and_one_shift():
    """One booking walked from held through confirmed to admitted, probed at each stop.

    The drill is validated first so the unit clears `NOT_READY`, which the
    confirmation step insists on; no `OR_STANDBY` entry is ever opened, so the unit
    sits at `DEGRADED`, which confirmation also accepts. The retirement probe is
    fired twice against the same bed, once under a hold and once under a
    commitment, because the guard is worded to cover both.
    """
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR"), ("LDR-03", "LDR")],
        staff_specs=WINDMERE_STAFF,
        unit_overrides={"unit_name": "Windmere Ridge Womens Pavilion LDR"},
    )
    setup_validated_drill(
        world,
        scheduled_for_utc=CLOCK_START,
        decision_at=SIMULATED_DECISION_AT,
        incision_at=SIMULATED_INCISION_AT,
        documented_key="ob",
        validator_key="officer",
        participant_keys=["ob", "anesthesia"],
        document_clock=CLOCK_AFTER_THE_DRILL,
    )
    bedside_shift = activate_shift(
        world, create_shift(world, "bedside", "BEDSIDE", *DAY_SHIFT)
    )
    spare_shift = create_shift(world, "spare", "BEDSIDE", *EVENING_SHIFT)
    unit_before_the_hold = world.reload_unit()
    booking = get_success_data(
        api_client.create_booking(
            {
                "unit_id": world.unit_id,
                "patient_record_code": "PRC-WIND-4401",
                "gestational_age_weeks": 38,
                "indication_code": "PREECLAMPSIA",
                "requested_start_utc": REQUESTED_START,
                "expected_labor_minutes": EXPECTED_LABOR_MINUTES,
            },
            world.access_headers,
        )
    )
    held = get_success_data(
        api_client.hold_capacity(
            booking["id"],
            {
                "bed_id": world.bed_id("LDR-01"),
                "expected_unit_version": unit_before_the_hold["version"],
            },
            world.access_headers,
        )
    )
    unit_while_held = world.reload_unit()
    retire_a_held_bed = api_client.delete_bed(
        world.bed_id("LDR-01"), world.officer_headers
    )
    bed_after_the_first_retirement = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    confirmed = api_client.confirm_booking(booking["id"], world.ob_headers)
    unit_while_confirmed = world.reload_unit()
    bed_while_confirmed = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    retire_a_committed_bed = api_client.delete_bed(
        world.bed_id("LDR-01"), world.officer_headers
    )
    set_clock(THIRTY_MINUTE_GRACE_INSTANT)
    admitted = api_client.admit_booking(booking["id"], world.charge_headers)
    unit_after_the_admission = world.reload_unit()
    bed_after_the_admission = get_success_data(
        api_client.get_bed(world.bed_id("LDR-01"), world.charge_headers)
    )
    cancel_an_admitted_booking = api_client.cancel_booking(
        booking["id"], world.access_headers
    )
    booking_at_the_end = get_success_data(
        api_client.get_booking(booking["id"], world.access_headers)
    )
    return {
        "world": world,
        "bedside_shift": bedside_shift,
        "spare_shift": spare_shift,
        "unit_before_the_hold": unit_before_the_hold,
        "booking": booking,
        "held": held,
        "unit_while_held": unit_while_held,
        "retire_a_held_bed": retire_a_held_bed,
        "bed_after_the_first_retirement": bed_after_the_first_retirement,
        "confirmed": confirmed,
        "unit_while_confirmed": unit_while_confirmed,
        "bed_while_confirmed": bed_while_confirmed,
        "retire_a_committed_bed": retire_a_committed_bed,
        "admitted": admitted,
        "unit_after_the_admission": unit_after_the_admission,
        "bed_after_the_admission": bed_after_the_admission,
        "cancel_an_admitted_booking": cancel_an_admitted_booking,
        "booking_at_the_end": booking_at_the_end,
    }


@pytest.fixture
def one_covered_bedside_shift_emptied_beside_an_untouched_sibling():
    """The contrast pair: the same cancellation call refused twice for different reasons.

    The drill is validated here too, purely so the closing posture read is decided
    by the deficit clause rather than by the readiness clause that outranks it.
    """
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=WINDMERE_STAFF,
        unit_overrides={"unit_name": "Windmere Ridge Annex Birthing Suite LDR"},
    )
    setup_validated_drill(
        world,
        scheduled_for_utc=CLOCK_START,
        decision_at=SIMULATED_DECISION_AT,
        incision_at=SIMULATED_INCISION_AT,
        documented_key="ob",
        validator_key="officer",
        participant_keys=["ob", "anesthesia"],
        document_clock=CLOCK_AFTER_THE_DRILL,
    )
    bedside_shift = activate_shift(
        world, create_shift(world, "bedside", "BEDSIDE", *DAY_SHIFT)
    )
    spare_shift = create_shift(world, "spare", "BEDSIDE", *EVENING_SHIFT)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-WIND-4402",
        parity=1,
        gestational_age_weeks=39,
    )
    row = create_care_assignment(world, encounter, bedside_shift, "RATIO_SHARED")
    covered_encounter = reload_encounter(world, encounter["id"])
    cancel_with_live_coverage = api_client.cancel_shift(
        bedside_shift["id"], world.charge_headers
    )
    shift_after_the_first_refusal = get_success_data(
        api_client.get_shift(bedside_shift["id"], world.charge_headers)
    )
    released = api_client.release_care_assignment(row["id"], world.charge_headers)
    cancel_with_no_coverage_left = api_client.cancel_shift(
        bedside_shift["id"], world.charge_headers
    )
    shift_after_the_second_refusal = get_success_data(
        api_client.get_shift(bedside_shift["id"], world.charge_headers)
    )
    cancel_the_scheduled_sibling = api_client.cancel_shift(
        spare_shift["id"], world.charge_headers
    )
    encounter_at_the_end = reload_encounter(world, encounter["id"])
    unit_at_the_end = world.reload_unit()
    return {
        "world": world,
        "bedside_shift": bedside_shift,
        "spare_shift": spare_shift,
        "encounter": encounter,
        "row": row,
        "covered_encounter": covered_encounter,
        "cancel_with_live_coverage": cancel_with_live_coverage,
        "shift_after_the_first_refusal": shift_after_the_first_refusal,
        "released": released,
        "cancel_with_no_coverage_left": cancel_with_no_coverage_left,
        "shift_after_the_second_refusal": shift_after_the_second_refusal,
        "cancel_the_scheduled_sibling": cancel_the_scheduled_sibling,
        "encounter_at_the_end": encounter_at_the_end,
        "unit_at_the_end": unit_at_the_end,
    }


def test_the_hold_freezes_its_quantum_against_an_open_posture(
    three_structural_guards_probed_on_one_booking_and_one_shift,
):
    """"This is also the moment `projected_occupancy_minutes` is frozen, as
    `expected_labor_minutes` plus the unit's current `turnover_buffer_minutes`, and that
    frozen integer is the exact quantum every later credit and debit moves." Also: "It is
    `MEDICALLY_INDICATED` when `indication_code` is `PREECLAMPSIA`, `POST_DATES_41W`,
    `FGR` or `PROM`."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = three_structural_guards_probed_on_one_booking_and_one_shift
    before = setup["unit_before_the_hold"]
    assert_obstetric_unit(before)
    assert before["staffing_posture"] == "OPEN"
    assert before["turnover_buffer_minutes"] == OPEN_BUFFER
    assert before["cesarean_readiness_state"] == "DEGRADED"
    held = setup["held"]
    assert_induction_booking(held)
    assert held["status"] == "CAPACITY_HELD"
    assert held["priority_class"] == "MEDICALLY_INDICATED"
    assert held["expected_labor_minutes"] == EXPECTED_LABOR_MINUTES
    assert held["projected_occupancy_minutes"] == PROJECTED_OCCUPANCY
    assert held["bed_id"] == setup["world"].bed_id("LDR-01")
    assert_instant_equals(held["hold_expires_at"], HOLD_EXPIRES_AT, "hold_expires_at")
    assert (
        setup["unit_while_held"]["held_bed_minutes_by_day"][BOOKING_DAY]
        == PROJECTED_OCCUPANCY
    )


def test_retiring_a_bed_under_a_live_hold_names_the_future_holds_guard(
    three_structural_guards_probed_on_one_booking_and_one_shift,
):
    """"Retirement is a `PerinatalSafetyOfficer` act and moves a bed from `AVAILABLE` or
    `BLOCKED` to `CLOSED`; it is refused with `ERR_BED_HAS_FUTURE_HOLDS` while any booking
    in `CAPACITY_HELD` or `CONFIRMED` still points at the bed."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = three_structural_guards_probed_on_one_booking_and_one_shift
    refused = setup["retire_a_held_bed"]
    validate_error(refused, ApiErrorId.ERR_BED_HAS_FUTURE_HOLDS.value, 409)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    assert reported != ApiErrorId.ERR_BED_NOT_RELEASABLE.value
    survivor = setup["bed_after_the_first_retirement"]
    assert_bed(survivor)
    assert survivor["status"] == "HELD"
    assert survivor["held_booking_id"] == setup["booking"]["id"]


def test_confirmation_moves_the_quantum_across_the_two_ledgers(
    three_structural_guards_probed_on_one_booking_and_one_shift,
):
    """"The frozen projection moves from `held_bed_minutes_by_day` to
    `committed_bed_minutes_by_day` for the same date, a net-zero movement,
    `hold_expires_at` is cleared, and the bed stays `HELD`."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = three_structural_guards_probed_on_one_booking_and_one_shift
    assert setup["confirmed"].status_code == 200
    confirmed = get_success_data(setup["confirmed"])
    assert_induction_booking(confirmed)
    assert confirmed["status"] == "CONFIRMED"
    assert_instant_is_null(confirmed["hold_expires_at"], "hold_expires_at")
    assert confirmed["projected_occupancy_minutes"] == PROJECTED_OCCUPANCY
    unit = setup["unit_while_confirmed"]
    assert unit["held_bed_minutes_by_day"].get(BOOKING_DAY, 0) == 0
    assert unit["committed_bed_minutes_by_day"][BOOKING_DAY] == PROJECTED_OCCUPANCY
    assert setup["bed_while_confirmed"]["status"] == "HELD"


def test_the_same_guard_answers_again_once_the_booking_is_confirmed(
    three_structural_guards_probed_on_one_booking_and_one_shift,
):
    """"**8.07** bed lifecycle guards, yielding `ERR_OR_BED_UNAVAILABLE`,
    `ERR_BED_HOLD_MISMATCH`, `ERR_BED_NOT_RELEASABLE`, `ERR_BED_HAS_FUTURE_HOLDS` or
    `ERR_ENCOUNTER_ALREADY_IN_BED`, on induction capacity holding, induction admission,
    encounter bed attachment, cesarean team mobilisation, bed status change and bed
    retirement."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = three_structural_guards_probed_on_one_booking_and_one_shift
    refused = setup["retire_a_committed_bed"]
    validate_error(refused, ApiErrorId.ERR_BED_HAS_FUTURE_HOLDS.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    )


def test_admission_at_the_boundary_instant_mints_the_encounter_and_takes_the_bed(
    three_structural_guards_probed_on_one_booking_and_one_shift,
):
    """"Admission is a `ChargeNurse` act moving `CONFIRMED` to `ADMITTED`, permitted from
    30 minutes before `requested_start_utc` onwards, with that boundary instant itself
    allowed and anything earlier refused as `ERR_INDUCTION_ADMIT_TOO_EARLY`."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = three_structural_guards_probed_on_one_booking_and_one_shift
    world = setup["world"]
    assert setup["admitted"].status_code == 200
    admitted = get_success_data(setup["admitted"])
    assert_induction_booking(admitted)
    assert admitted["status"] == "ADMITTED"
    assert admitted["encounter_id"] is not None
    minted = reload_encounter(world, admitted["encounter_id"])
    assert_labor_encounter(minted)
    assert minted["labor_phase"] == "ANTEPARTUM"
    assert minted["staffing_state"] == "UNASSIGNED"
    assert minted["source_booking_id"] == setup["booking"]["id"]
    assert minted["patient_record_code"] == "PRC-WIND-4401"
    assert minted["gestational_age_weeks"] == 38
    assert_instant_equals(
        minted["admitted_at"], THIRTY_MINUTE_GRACE_INSTANT, "admitted_at"
    )
    occupied = setup["bed_after_the_admission"]
    assert_bed(occupied)
    assert occupied["status"] == "OCCUPIED"
    assert occupied["held_booking_id"] is None
    assert occupied["current_encounter_id"] == admitted["encounter_id"]


def test_the_committed_minutes_do_not_move_when_the_patient_walks_in(
    three_structural_guards_probed_on_one_booking_and_one_shift,
):
    """"The committed minutes stay committed, since `CONFIRMED` and `ADMITTED` both count
    against the day."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = three_structural_guards_probed_on_one_booking_and_one_shift
    unit = setup["unit_after_the_admission"]
    assert_obstetric_unit(unit)
    assert unit["committed_bed_minutes_by_day"][BOOKING_DAY] == PROJECTED_OCCUPANCY
    assert unit["held_bed_minutes_by_day"].get(BOOKING_DAY, 0) == 0


def test_an_admitted_booking_names_its_own_refusal_rather_than_the_generic_one(
    three_structural_guards_probed_on_one_booking_and_one_shift,
):
    """"A cancellation, also a `PatientAccessCoordinator` act, is available from
    `REQUESTED`, `CAPACITY_HELD` or `CONFIRMED`, releases any held bed and credits back
    exactly `projected_occupancy_minutes`; an `ADMITTED` booking can never be cancelled,
    and the attempt is refused with `ERR_INDUCTION_ALREADY_ADMITTED`."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = three_structural_guards_probed_on_one_booking_and_one_shift
    refused = setup["cancel_an_admitted_booking"]
    validate_error(refused, ApiErrorId.ERR_INDUCTION_ALREADY_ADMITTED.value, 409)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    assert reported != ApiErrorId.ERR_BED_HOLD_MISMATCH.value
    survivor = setup["booking_at_the_end"]
    assert_induction_booking(survivor)
    assert survivor["status"] == "ADMITTED"
    assert survivor["bed_id"] == setup["world"].bed_id("LDR-01")
    assert survivor["projected_occupancy_minutes"] == PROJECTED_OCCUPANCY


def test_a_live_care_assignment_blocks_the_cancellation_by_name(
    one_covered_bedside_shift_emptied_beside_an_untouched_sibling,
):
    """"**8.08** shift and coverage guards, yielding `ERR_SHIFT_NOT_ACTIVE`,
    `ERR_SHIFT_HAS_ACTIVE_COVERAGE`, `ERR_RELIEVING_SHIFT_INELIGIBLE` or
    `ERR_SHIFT_WINDOW_NOT_CURRENT`, on care-assignment creation, shift activation, shift
    relief and shift cancellation."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = one_covered_bedside_shift_emptied_beside_an_untouched_sibling
    row = setup["row"]
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["coverage_mode"] == "RATIO_SHARED"
    assert setup["covered_encounter"]["staffing_state"] == "RATIO_COVERED"
    refused = setup["cancel_with_live_coverage"]
    validate_error(refused, ApiErrorId.ERR_SHIFT_HAS_ACTIVE_COVERAGE.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    )
    unchanged = setup["shift_after_the_first_refusal"]
    assert_shift_assignment(unchanged)
    assert unchanged["status"] == "ACTIVE"


def test_the_identical_call_falls_back_to_the_generic_guard_once_the_row_is_released(
    one_covered_bedside_shift_emptied_beside_an_untouched_sibling,
):
    """"**Priority 8** — the declared-transition guard, on every action operation: an
    attempt to move a record from a state for which the requested edge is not declared
    yields `ERR_INVALID_STATE_TRANSITION` at HTTP 409."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = one_covered_bedside_shift_emptied_beside_an_untouched_sibling
    assert setup["released"].status_code == 200
    released = get_success_data(setup["released"])
    assert_care_assignment(released)
    assert released["status"] == "RELEASED"
    refused = setup["cancel_with_no_coverage_left"]
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    assert (
        refused.json()["data"]["error_id"]
        != ApiErrorId.ERR_SHIFT_HAS_ACTIVE_COVERAGE.value
    )
    still_active = setup["shift_after_the_second_refusal"]
    assert_shift_assignment(still_active)
    assert still_active["status"] == "ACTIVE"


def test_the_scheduled_sibling_cancels_without_argument(
    one_covered_bedside_shift_emptied_beside_an_untouched_sibling,
):
    """"Cancellation is available only from `SCHEDULED`, again to a `ChargeNurse`, and is
    refused with `ERR_SHIFT_HAS_ACTIVE_COVERAGE` while any care assignment referencing the
    entry is still `ACTIVE`."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = one_covered_bedside_shift_emptied_beside_an_untouched_sibling
    assert setup["spare_shift"]["status"] == "SCHEDULED"
    assert setup["cancel_the_scheduled_sibling"].status_code == 200
    cancelled = get_success_data(setup["cancel_the_scheduled_sibling"])
    assert_shift_assignment(cancelled)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["id"] == setup["spare_shift"]["id"]


def test_the_emptied_encounter_falls_to_coverage_breach(
    one_covered_bedside_shift_emptied_beside_an_untouched_sibling,
):
    """"From `RATIO_COVERED` or `ONE_TO_ONE_COVERED` an encounter falls to
    `COVERAGE_BREACH`, and this edge is driven by the system rather than requested, may
    fire any number of times, and never produces an error."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = one_covered_bedside_shift_emptied_beside_an_untouched_sibling
    breached = setup["encounter_at_the_end"]
    assert_labor_encounter(breached)
    assert breached["staffing_state"] == "COVERAGE_BREACH"
    assert breached["acuity_tier"] == "TIER_I"
    assert breached["required_coverage_units"] == pytest.approx(
        TIER_ONE_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert breached["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)


def test_the_half_unit_deficit_strains_the_unit_and_widens_the_buffer(
    one_covered_bedside_shift_emptied_beside_an_untouched_sibling,
):
    """"`RATIO_STRAINED` when the deficit is greater than 0.0, or any encounter is in
    `COVERAGE_BREACH`." Also: "After the posture is settled, and only then,
    `turnover_buffer_minutes` is set to 45 when the posture is `OPEN` and 75 otherwise."

    Design: Corner/errors/three_structural_guard_ids_that_only_exist_because_the_specific_over_generic_carve_out_holds
    """
    setup = one_covered_bedside_shift_emptied_beside_an_untouched_sibling
    unit = setup["unit_at_the_end"]
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(
        TIER_ONE_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert unit["cesarean_readiness_state"] == "DEGRADED"
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER
