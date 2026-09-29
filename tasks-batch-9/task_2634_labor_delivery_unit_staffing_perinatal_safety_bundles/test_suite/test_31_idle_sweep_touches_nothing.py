"""A sweep run over a unit where every candidate set is empty.

Each of the sweep's six steps selects its work by a deadline comparison, and
this unit is populated with rows that superficially look sweepable but are
none of them due: a CATEGORY_I chain that never had a deadline, a pass valid for
another day, a fully covered encounter and two idle beds. The sweep must stamp
its own instant and touch nothing else.
"""

import pytest

from test_helpers import (
    api_client,
    assert_care_assignment,
    assert_bed,
    assert_fetal_assessment,
    assert_instant_equals,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_support_pass,
    bootstrap_unit,
    capacity_sweep,
    create_active_shift,
    create_assessment,
    create_care_assignment,
    create_encounter,
    create_pass,
    get_success_data,
    reload_encounter,
    reload_pass,
    set_clock,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SWEEP_INSTANT = "2026-08-01T06:10:00Z"
PASS_VALID_UNTIL = "2026-08-02T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
CHARGE_CAPACITY = 2.0
RATIO_DEBIT = 0.5

IDLE_STAFF = {
    "charge": {
        "full_name": "Annika Sorrentino RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def a_unit_with_nothing_due_swept_ten_minutes_on():
    """A covered encounter, a quiet CATEGORY_I chain and a day-long pass, swept."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=IDLE_STAFF,
        unit_overrides={"unit_name": "Sablewood Family Birth LDR"},
    )
    shift = create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world, patient_record_code="PRC-IDLE-2828", parity=2, gestational_age_weeks=40
    )
    assignment = create_care_assignment(
        world, encounter, shift, coverage_mode="RATIO_SHARED"
    )
    assessment = create_assessment(
        world,
        encounter,
        interpreted_key="charge",
        acting_key="charge",
        category="CATEGORY_I",
        baseline_rate_bpm=140,
        variability="MODERATE",
        recurrent_decelerations=False,
    )
    support_pass = create_pass(
        world, encounter, person_name="Tobias Renner", credential_type="PARTNER"
    )
    set_clock(SWEEP_INSTANT)
    result = capacity_sweep(world)
    return {
        "world": world,
        "shift": shift,
        "encounter": encounter,
        "assignment": assignment,
        "assessment": assessment,
        "pass": support_pass,
        "result": result,
    }


def test_the_idle_sweep_answers_two_hundred_with_every_counter_at_zero(
    a_unit_with_nothing_due_swept_ten_minutes_on,
):
    """"A sweep with nothing due is not an error: every counter it reports is 0, no
    record is touched, and the response is a normal 200 OK."

    Design: Corner/calculations/an_idle_sweep_stamps_the_sweep_time_and_touches_nothing_that_is_not_yet_due
    """
    result = a_unit_with_nothing_due_swept_ten_minutes_on["result"]
    counters = {
        key: value
        for key, value in result.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    assert counters, "the sweep report must carry at least one counter"
    for key, value in counters.items():
        assert value == 0, f"{key} should be 0 on an idle sweep, got {value}"
    for key, value in result.items():
        if isinstance(value, list):
            assert value == [], f"{key} should be empty on an idle sweep, got {value}"


def test_the_sweep_instant_is_recorded_on_the_unit(
    a_unit_with_nothing_due_swept_ten_minutes_on,
):
    """"The sweep records `last_capacity_sweep_at` on the unit, which is null until
    the first sweep runs."

    Design: Corner/calculations/an_idle_sweep_stamps_the_sweep_time_and_touches_nothing_that_is_not_yet_due
    """
    unit = a_unit_with_nothing_due_swept_ten_minutes_on["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert_instant_equals(
        unit["last_capacity_sweep_at"], SWEEP_INSTANT, "last_capacity_sweep_at"
    )
    assert unit["escalation_breach_count"] == 0
    assert unit["bundle_breach_count"] == 0
    assert unit["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)


def test_the_quiet_chain_and_the_valid_pass_are_left_alone(
    a_unit_with_nothing_due_swept_ten_minutes_on,
):
    """"Alongside the booking waterfall the same sweep settles three other classes
    of overdue obligation: checklist items still `PENDING` past their grace window
    become `MISSED`; fetal escalation chains sitting past a deadline become
    `TIMED_OUT_BREACH`, and chains sitting in `REASSESSMENT_PENDING` past their
    reassessment deadline re-arm to `ESCALATION_DUE`; and support passes in `ISSUED`
    or `CHECKED_OUT` whose validity has elapsed become `EXPIRED`."

    Design: Corner/calculations/an_idle_sweep_stamps_the_sweep_time_and_touches_nothing_that_is_not_yet_due
    """
    setup = a_unit_with_nothing_due_swept_ten_minutes_on
    world = setup["world"]
    chain = get_success_data(
        api_client.get_assessment(setup["assessment"]["id"], world.charge_headers)
    )
    assert_fetal_assessment(chain)
    assert chain["escalation_status"] == "NOT_REQUIRED"
    assert chain["escalation_due_at"] is None
    still_valid = reload_pass(world, setup["pass"]["id"])
    assert_support_pass(still_valid)
    assert still_valid["status"] == "ISSUED"
    assert_instant_equals(still_valid["valid_until"], PASS_VALID_UNTIL, "valid_until")


def test_the_covered_encounter_is_not_pushed_into_a_breach(
    a_unit_with_nothing_due_swept_ten_minutes_on,
):
    """"It reaches `RATIO_COVERED` only once `assigned_coverage_units` is at least
    `required_coverage_units`." The two figures are equal at 0.5, so the coverage
    step of the sweep has nothing to breach.

    Design: Corner/calculations/an_idle_sweep_stamps_the_sweep_time_and_touches_nothing_that_is_not_yet_due
    """
    setup = a_unit_with_nothing_due_swept_ten_minutes_on
    world = setup["world"]
    encounter = reload_encounter(world, setup["encounter"]["id"])
    assert_labor_encounter(encounter)
    assert encounter["staffing_state"] == "RATIO_COVERED"
    assert encounter["required_coverage_units"] == pytest.approx(RATIO_DEBIT, abs=1e-9)
    assert encounter["assigned_coverage_units"] == pytest.approx(RATIO_DEBIT, abs=1e-9)
    row = get_success_data(
        api_client.get_care_assignment(setup["assignment"]["id"], world.charge_headers)
    )
    assert_care_assignment(row)
    assert row["status"] == "ACTIVE"
    assert row["acuity_units_consumed"] == pytest.approx(RATIO_DEBIT, abs=1e-9)
    assert setup["shift"]["capacity_units_effective"] == pytest.approx(
        CHARGE_CAPACITY, abs=1e-9
    )


def test_both_idle_beds_stay_available(a_unit_with_nothing_due_swept_ten_minutes_on):
    """"Second, it clears beds in `TURNOVER` whose `turnover_clear_at` is at or
    before the current instant, returning them to `AVAILABLE`." Neither bed was
    ever in `TURNOVER`, so the step has an empty candidate set.

    Design: Corner/calculations/an_idle_sweep_stamps_the_sweep_time_and_touches_nothing_that_is_not_yet_due
    """
    world = a_unit_with_nothing_due_swept_ten_minutes_on["world"]
    for label in ("LDR-01", "LDR-02"):
        bed = get_success_data(
            api_client.get_bed(world.bed_id(label), world.charge_headers)
        )
        assert_bed(bed)
        assert bed["status"] == "AVAILABLE"
        assert bed["current_encounter_id"] is None
