"""One junction insert, four entities, and a sweep that finds nothing left to do.

Attaching a nurse to a patient touches the junction row, the encounter's coverage
axis, the covering roster entry's load ledger and the unit's posture, deficit and
turnover buffer. Every one of those is read back on the call immediately
following the write — no clock advance, no sweep, no retry — and pinned. The
write's own response has to carry its computed price rather than a null to be
filled in later, and the unit's `version` has to have already advanced by one.
The discriminating half is the sweep run straight afterwards: with no deferred
work in flight it changes nothing at all. The release arm then runs the whole
cascade backwards in a single call, so the immediacy cannot be an artefact of a
create-only fast path.
"""

import pytest

from test_helpers import (
    api_client,
    assert_care_assignment,
    assert_drill,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    bootstrap_unit,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    get_success_data,
    reload_encounter,
    set_clock,
    setup_validated_drill,
)

CLOCK_BOOTSTRAP = "2026-08-01T05:45:00Z"
CLOCK_DRILL_DUE = "2026-08-01T05:50:00Z"
DRILL_SCHEDULED_FOR = "2026-08-01T05:50:00Z"
SIMULATED_DECISION_AT = "2026-08-01T05:52:00Z"
SIMULATED_INCISION_AT = "2026-08-01T05:55:00Z"
CLOCK_WORKING = "2026-08-01T06:00:00Z"
SHIFT_WINDOW = ("2026-08-01T06:00:00Z", "2026-08-01T12:00:00Z")
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
UNIT_NAME = "Verrazano Shoals Womens Pavilion LDR"

BEDSIDE_CAPACITY = 4.0
TIER_I_ANTEPARTUM_UNITS = 0.5
STANDING_DEFICIT = 0.5
COVERED_DEFICIT = 0.0
OPEN_BUFFER_MINUTES = 45
STRAINED_BUFFER_MINUTES = 75
EMPTY_LOAD = 0.0
DRILL_MEASURED_MINUTES = 3

VERRAZANO_STAFF = {
    "charge": {
        "full_name": "Ludovica Petrossian RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "bedside": {
        "full_name": "Marisol Ashgrove RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "anesthesia": {
        "full_name": "Perpetua Vasilakis MD",
        "staff_role": "ANESTHESIOLOGIST",
        "fetal_monitoring_cert_level": "BASIC",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": True,
    },
    "ob": {
        "full_name": "Alaric Bensimon MD",
        "staff_role": "OB_ATTENDING",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
    "officer": {
        "full_name": "Anselm Thorncastle RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_junction_insert_read_back_immediately():
    """One nurse, one patient, one insert, one sweep and one release.

    The drill is validated first so the unit's readiness leaves its `NOT_READY`
    default; without that the freeze branch of the posture derivation would mask
    every posture movement this instance measures. No booking, pass, bundle or
    assessment exists anywhere, so the sweep genuinely has nothing it could do.
    """
    world = bootstrap_unit(
        clock=CLOCK_BOOTSTRAP,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=VERRAZANO_STAFF,
        unit_overrides={"unit_name": UNIT_NAME},
    )
    set_clock(CLOCK_DRILL_DUE)
    drill = setup_validated_drill(
        world,
        DRILL_SCHEDULED_FOR,
        SIMULATED_DECISION_AT,
        SIMULATED_INCISION_AT,
        participant_keys=["ob", "anesthesia"],
        document_clock=CLOCK_WORKING,
    )
    shift = create_active_shift(world, "bedside", "BEDSIDE", *SHIFT_WINDOW)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-VERR-4101",
        parity=1,
        gestational_age_weeks=39,
    )
    report_params = {"limit": 10, "offset": 0}
    unit_before = world.reload_unit()
    report_before = get_success_data(
        api_client.get_coverage_report(
            world.unit_id, world.charge_headers, params=report_params
        )
    )
    encounter_before = reload_encounter(world, encounter["id"])
    assignment = create_care_assignment(world, encounter, shift)
    encounter_after = reload_encounter(world, encounter["id"])
    shift_after = get_success_data(
        api_client.get_shift(shift["id"], world.charge_headers)
    )
    unit_after = world.reload_unit()
    report_after = get_success_data(
        api_client.get_coverage_report(
            world.unit_id, world.charge_headers, params=report_params
        )
    )
    sweep = api_client.capacity_sweep(world.unit_id, world.charge_headers)
    unit_after_the_sweep = world.reload_unit()
    encounter_after_the_sweep = reload_encounter(world, encounter["id"])
    shift_after_the_sweep = get_success_data(
        api_client.get_shift(shift["id"], world.charge_headers)
    )
    assignment_after_the_sweep = get_success_data(
        api_client.get_care_assignment(assignment["id"], world.charge_headers)
    )
    released = get_success_data(
        api_client.release_care_assignment(assignment["id"], world.charge_headers)
    )
    unit_after_the_release = world.reload_unit()
    report_after_the_release = get_success_data(
        api_client.get_coverage_report(
            world.unit_id, world.charge_headers, params=report_params
        )
    )
    shift_after_the_release = get_success_data(
        api_client.get_shift(shift["id"], world.charge_headers)
    )
    encounter_after_the_release = reload_encounter(world, encounter["id"])
    return {
        "world": world,
        "drill": drill,
        "shift": shift,
        "encounter": encounter,
        "unit_before": unit_before,
        "report_before": report_before,
        "encounter_before": encounter_before,
        "assignment": assignment,
        "encounter_after": encounter_after,
        "shift_after": shift_after,
        "unit_after": unit_after,
        "report_after": report_after,
        "sweep": sweep,
        "unit_after_the_sweep": unit_after_the_sweep,
        "encounter_after_the_sweep": encounter_after_the_sweep,
        "shift_after_the_sweep": shift_after_the_sweep,
        "assignment_after_the_sweep": assignment_after_the_sweep,
        "released": released,
        "unit_after_the_release": unit_after_the_release,
        "report_after_the_release": report_after_the_release,
        "shift_after_the_release": shift_after_the_release,
        "encounter_after_the_release": encounter_after_the_release,
    }


def test_the_baseline_unit_stands_strained_on_a_single_uncovered_patient(
    one_junction_insert_read_back_immediately,
):
    """"`RATIO_STRAINED` when the deficit is greater than 0.0, or any encounter is in
    `COVERAGE_BREACH`." Also: "After the posture is settled, and only then,
    `turnover_buffer_minutes` is set to 45 when the posture is `OPEN` and 75 otherwise."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    drill = setup["drill"]
    assert_drill(drill)
    assert drill["measured_d2i_minutes"] == DRILL_MEASURED_MINUTES
    unit = setup["unit_before"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "DEGRADED"
    assert unit["coverage_deficit_units"] == pytest.approx(STANDING_DEFICIT, abs=1e-9)
    assert unit["staffing_posture"] == "RATIO_STRAINED"
    assert unit["turnover_buffer_minutes"] == STRAINED_BUFFER_MINUTES


def test_the_baseline_patient_and_roster_entry_are_priced_but_unjoined(
    one_junction_insert_read_back_immediately,
):
    """"The third step produces `required_coverage_units`: 0.0 when `labor_phase` is
    `DISCHARGED` or `TRANSFERRED_OUT`; otherwise 4.0 when one-to-one coverage is required;
    otherwise the acuity weight multiplied by the phase multiplier from the table above." Also:
    "A single roster entry read exposes `capacity_units_effective`, the snapshot frozen at
    activation, alongside `assigned_acuity_load_units`, the conserved total that section 3.3
    defines."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    patient = setup["encounter_before"]
    assert_labor_encounter(patient)
    assert patient["acuity_tier"] == "TIER_I"
    assert patient["labor_phase"] == "ANTEPARTUM"
    assert patient["staffing_state"] == "UNASSIGNED"
    assert patient["required_coverage_units"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert patient["assigned_coverage_units"] == pytest.approx(EMPTY_LOAD, abs=1e-9)
    entry = setup["shift"]
    assert_shift_assignment(entry)
    assert entry["status"] == "ACTIVE"
    assert entry["capacity_units_effective"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )
    assert entry["assigned_acuity_load_units"] == pytest.approx(EMPTY_LOAD, abs=1e-9)


def test_the_baseline_report_names_the_branch_that_fired(
    one_junction_insert_read_back_immediately,
):
    """"A unit's coverage report exposes this whole derivation: one row per non-terminal
    encounter with its required units, its assigned units and its own contribution to the
    deficit, ordered by `created_at` ascending and paginated by `limit` and `offset`, together
    with the rolled-up `coverage_deficit_units` and the reason code for the branch that fired —
    `DIVERT_DEFICIT`, `NO_AVAILABLE_LDR_BED`, `STAGE_3_BUNDLE`, `FREEZE_DEFICIT`,
    `ESCALATION_BREACH`, `BUNDLE_BREACH`, `READINESS_NOT_READY`, `STAGE_2_WITH_DEFICIT`,
    `DEFICIT_POSITIVE`, `BREACHED_ENCOUNTER` or `NONE`."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    report = setup["report_before"]
    assert report["staffing_posture"] == "RATIO_STRAINED"
    assert report["posture_reason"] == "DEFICIT_POSITIVE"
    assert report["coverage_deficit_units"] == pytest.approx(
        STANDING_DEFICIT, abs=1e-9
    )
    rows = report["encounters"]
    assert len(rows) == 1
    assert rows[0]["encounter_id"] == setup["encounter"]["id"]
    assert rows[0]["required_coverage_units"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert rows[0]["assigned_coverage_units"] == pytest.approx(EMPTY_LOAD, abs=1e-9)
    assert rows[0]["deficit_units"] == pytest.approx(STANDING_DEFICIT, abs=1e-9)


def test_the_writes_own_response_already_carries_its_computed_price(
    one_junction_insert_read_back_immediately,
):
    """"The new row opens in `ACTIVE` with `staff_id` denormalised from the roster entry, and
    carries `acuity_units_consumed`, `released_at` and `superseded_by_assignment_id` as its
    remaining state." Also: "A `RATIO_SHARED` row debits the product of two factors: the acuity
    weight, which is 1.0 for `TIER_I`, 1.5 for `TIER_II`, 2.0 for `TIER_III` and 4.0 for
    `TIER_IV`; and the phase multiplier, which is 0.5 for `ANTEPARTUM`, 1.0 for `LATENT`, 1.5
    for `ACTIVE_FIRST_STAGE`, 2.0 for `SECOND_STAGE`, 1.5 for `THIRD_STAGE_DELIVERED`, 0.5 for
    `POSTPARTUM_RECOVERY`, 0.0 for `DISCHARGED` and 0.0 for `TRANSFERRED_OUT`."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    world = setup["world"]
    written = setup["assignment"]
    assert_care_assignment(written)
    assert written["status"] == "ACTIVE"
    assert written["coverage_mode"] == "RATIO_SHARED"
    assert written["staff_id"] == world.staff_id("bedside")
    assert written["acuity_units_consumed"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert_instant_is_null(written["released_at"], "released_at")
    assert written["superseded_by_assignment_id"] is None


def test_the_encounter_axis_is_final_on_the_very_next_read(
    one_junction_insert_read_back_immediately,
):
    """"It reaches `RATIO_COVERED` only once `assigned_coverage_units` is at least
    `required_coverage_units`." Also: "For every encounter, `assigned_coverage_units` equals the
    sum of `acuity_units_consumed` over its own `ACTIVE` rows."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    patient = setup["encounter_after"]
    assert_labor_encounter(patient)
    assert patient["assigned_coverage_units"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert patient["required_coverage_units"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert (
        patient["assigned_coverage_units"] >= patient["required_coverage_units"]
    )
    assert patient["staffing_state"] == "RATIO_COVERED"


def test_the_shift_ledger_is_final_on_the_very_next_read(
    one_junction_insert_read_back_immediately,
):
    """"For every roster entry in `SCHEDULED` or `ACTIVE`, `assigned_acuity_load_units` equals
    the sum of `acuity_units_consumed` over that entry's `ACTIVE` rows." Also: "From that raw
    figure an administrative offset of 1.0 is subtracted when the slot is `CHARGE`, and a focus
    penalty of 1.0 is subtracted when the member currently holds an `ACTIVE` care assignment on
    this shift covering an encounter whose `acuity_tier` is `TIER_IV`."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    entry = setup["shift_after"]
    assert_shift_assignment(entry)
    assert entry["assigned_acuity_load_units"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert setup["encounter_after"]["acuity_tier"] == "TIER_I"
    assert entry["capacity_units_effective"] == pytest.approx(
        BEDSIDE_CAPACITY, abs=1e-9
    )


def test_the_unit_row_moved_inside_the_same_request(
    one_junction_insert_read_back_immediately,
):
    """"`version` is an integer that starts at 1 when the record is created and increments by 1
    on each mutation of that record; because this system cascades aggressively, a single request
    routinely increments the `version` of a dozen records, and every such increment is called
    out in the workflow descriptions in section 3." Also: "After the posture is settled, and
    only then, `turnover_buffer_minutes` is set to 45 when the posture is `OPEN` and 75
    otherwise."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    before = setup["unit_before"]
    after = setup["unit_after"]
    assert_obstetric_unit(after)
    assert after["coverage_deficit_units"] == pytest.approx(COVERED_DEFICIT, abs=1e-9)
    assert after["staffing_posture"] == "OPEN"
    assert after["turnover_buffer_minutes"] == OPEN_BUFFER_MINUTES
    assert after["version"] == before["version"] + 1


def test_the_computed_report_agrees_with_the_stored_row_in_the_same_instant(
    one_junction_insert_read_back_immediately,
):
    """"`OPEN` otherwise." Also: "A unit's coverage report exposes this whole derivation: one
    row per non-terminal encounter with its required units, its assigned units and its own
    contribution to the deficit, ordered by `created_at` ascending and paginated by `limit` and
    `offset`, together with the rolled-up `coverage_deficit_units` and the reason code for the
    branch that fired — `DIVERT_DEFICIT`, `NO_AVAILABLE_LDR_BED`, `STAGE_3_BUNDLE`,
    `FREEZE_DEFICIT`, `ESCALATION_BREACH`, `BUNDLE_BREACH`, `READINESS_NOT_READY`,
    `STAGE_2_WITH_DEFICIT`, `DEFICIT_POSITIVE`, `BREACHED_ENCOUNTER` or `NONE`."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    report = setup["report_after"]
    assert report["staffing_posture"] == "OPEN"
    assert report["posture_reason"] == "NONE"
    assert report["coverage_deficit_units"] == pytest.approx(COVERED_DEFICIT, abs=1e-9)
    rows = report["encounters"]
    assert len(rows) == 1
    assert rows[0]["staffing_state"] == "RATIO_COVERED"
    assert rows[0]["deficit_units"] == pytest.approx(COVERED_DEFICIT, abs=1e-9)


def test_the_sweep_finds_no_deferred_work_at_all(
    one_junction_insert_read_back_immediately,
):
    """"A sweep with nothing due is not an error: every counter it reports is 0, no record is
    touched, and the response is a normal 200 OK." Also: "The sweep records
    `last_capacity_sweep_at` on the unit, which is null until the first sweep runs."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    assert setup["unit_after"]["last_capacity_sweep_at"] is None
    response = setup["sweep"]
    assert response.status_code == 200
    swept = get_success_data(response)
    assert swept["unit_id"] == setup["world"].unit_id
    assert_instant_equals(swept["swept_at"], CLOCK_WORKING, "swept_at")
    assert swept["beds_cleared_count"] == 0
    assert swept["promoted_count"] == 0
    for field in (
        "holds_expired_booking_ids",
        "bookings_requeued_booking_ids",
        "bookings_expired_booking_ids",
        "promoted_booking_ids",
        "missed_checklist_item_ids",
        "breached_assessment_ids",
        "rearmed_assessment_ids",
        "expired_pass_ids",
        "breached_encounter_ids",
    ):
        assert swept[field] == []
    assert_instant_equals(
        setup["unit_after_the_sweep"]["last_capacity_sweep_at"],
        CLOCK_WORKING,
        "last_capacity_sweep_at",
    )


def test_the_sweep_moved_nothing_it_swept_over(
    one_junction_insert_read_back_immediately,
):
    """"First, it freezes the unit's `staffing_posture` as it stands at the start of the sweep,
    together with the `turnover_buffer_minutes` derived from that posture, and uses those frozen
    values for the whole sweep." Also: "Sixth, and only once, at the very end, it re-derives the
    unit's posture."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    swept = get_success_data(setup["sweep"])
    assert swept["posture_at_sweep"] == "OPEN"
    assert swept["staffing_posture"] == "OPEN"
    assert swept["coverage_deficit_units"] == pytest.approx(COVERED_DEFICIT, abs=1e-9)
    unit = setup["unit_after_the_sweep"]
    assert_obstetric_unit(unit)
    assert unit["staffing_posture"] == "OPEN"
    assert unit["coverage_deficit_units"] == pytest.approx(COVERED_DEFICIT, abs=1e-9)
    assert unit["turnover_buffer_minutes"] == OPEN_BUFFER_MINUTES
    patient = setup["encounter_after_the_sweep"]
    assert patient["staffing_state"] == "RATIO_COVERED"
    assert patient["assigned_coverage_units"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    entry = setup["shift_after_the_sweep"]
    assert entry["assigned_acuity_load_units"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    row = setup["assignment_after_the_sweep"]
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["acuity_units_consumed"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )


def test_the_release_credits_back_exactly_what_it_debited(
    one_junction_insert_read_back_immediately,
):
    """"Releasing a row is a `ChargeNurse` act: `status` becomes `RELEASED`, `released_at`
    becomes the current instant, and the covering entry is credited back exactly
    `acuity_units_consumed`." Also: "Releasing the last `ACTIVE` row drives the encounter to
    `RELEASED` when its `labor_phase` is `POSTPARTUM_RECOVERY`, `DISCHARGED` or
    `TRANSFERRED_OUT`, and to `COVERAGE_BREACH` in any earlier phase — again recorded rather
    than refused."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    released = setup["released"]
    assert_care_assignment(released)
    assert released["status"] == "RELEASED"
    assert released["acuity_units_consumed"] == pytest.approx(
        TIER_I_ANTEPARTUM_UNITS, abs=1e-9
    )
    assert_instant_equals(released["released_at"], CLOCK_WORKING, "released_at")
    entry = setup["shift_after_the_release"]
    assert entry["assigned_acuity_load_units"] == pytest.approx(EMPTY_LOAD, abs=1e-9)
    patient = setup["encounter_after_the_release"]
    assert_labor_encounter(patient)
    assert patient["labor_phase"] == "ANTEPARTUM"
    assert patient["staffing_state"] == "COVERAGE_BREACH"
    assert patient["assigned_coverage_units"] == pytest.approx(EMPTY_LOAD, abs=1e-9)


def test_one_call_reversed_all_four_hops_with_no_sweep_in_between(
    one_junction_insert_read_back_immediately,
):
    """"Creating a row and then releasing it, performing a one-to-one handoff, relieving a shift
    and rescinding a bundle each leave both sums, and the unit's `coverage_deficit_units`,
    identical to their values before the sequence began." Also: "After the posture is settled,
    and only then, `turnover_buffer_minutes` is set to 45 when the posture is `OPEN` and 75
    otherwise."

    Design: Corner/consistency_model/a_four_entity_cascade_is_final_on_the_very_next_read_and_leaves_the_sweep_nothing_to_do
    """
    setup = one_junction_insert_read_back_immediately
    before = setup["unit_before"]
    after = setup["unit_after_the_release"]
    assert_obstetric_unit(after)
    assert after["coverage_deficit_units"] == pytest.approx(
        before["coverage_deficit_units"], abs=1e-9
    )
    assert after["coverage_deficit_units"] == pytest.approx(STANDING_DEFICIT, abs=1e-9)
    assert after["staffing_posture"] == "RATIO_STRAINED"
    assert after["turnover_buffer_minutes"] == STRAINED_BUFFER_MINUTES
    report = setup["report_after_the_release"]
    assert report["posture_reason"] == "DEFICIT_POSITIVE"
    assert report["coverage_deficit_units"] == pytest.approx(
        STANDING_DEFICIT, abs=1e-9
    )
