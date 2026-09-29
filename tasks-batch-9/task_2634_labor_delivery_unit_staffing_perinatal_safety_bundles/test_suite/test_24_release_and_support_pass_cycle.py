"""Walking two rows back out of the state they were carried into.

Releasing the only care assignment on an encounter fires four consequences at
once and answers 200 even though it manufactures a coverage breach. A support
pass, by contrast, refuses to absorb a replayed check-out, and its one cyclic
edge back in is the only entry that counts a re-entry.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_care_assignment,
    assert_instant_equals,
    assert_instant_is_null,
    assert_labor_encounter,
    assert_obstetric_unit,
    assert_shift_assignment,
    assert_support_pass,
    bootstrap_unit,
    check_in_pass,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    create_pass,
    get_success_data,
    reload_encounter,
    reload_pass,
    set_clock,
)

CLOCK_START = "2026-08-01T06:00:00Z"
CLOCK_LATER = "2026-08-01T06:30:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
CHARGE_CAPACITY = 2.0
RATIO_DEBIT = 0.5
PASS_VALID_UNTIL = "2026-08-02T06:00:00Z"

CYCLE_STAFF = {
    "charge": {
        "full_name": "Nadia Vermeer RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


def _unit(unit_name):
    """One unit with a single AVAILABLE LDR bed and one credentialled nurse."""
    return bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=CYCLE_STAFF,
        unit_overrides={"unit_name": unit_name},
    )


@pytest.fixture
def the_only_covering_row_released_half_an_hour_later():
    """One RATIO_SHARED row on an ANTEPARTUM encounter, released at 06:30."""
    world = _unit("Sycamore Bay Perinatal LDR")
    shift = create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-REL-9009",
        parity=0,
        gestational_age_weeks=39,
    )
    assignment = create_care_assignment(
        world, encounter, shift, coverage_mode="RATIO_SHARED"
    )
    covered = reload_encounter(world, encounter["id"])
    set_clock(CLOCK_LATER)
    released = get_success_data(
        api_client.release_care_assignment(assignment["id"], world.charge_headers)
    )
    return {
        "world": world,
        "shift": shift,
        "encounter": encounter,
        "assignment": assignment,
        "covered": covered,
        "released": released,
    }


@pytest.fixture
def a_partner_pass_taken_out_of_the_room():
    """A PARTNER pass checked in and back out at 06:00, with the clock at 06:30."""
    world = _unit("Kestrel Point Birth Center LDR")
    encounter = create_encounter(
        world,
        patient_record_code="PRC-PASS-1010",
        parity=1,
        gestational_age_weeks=40,
    )
    support_pass = create_pass(world, encounter, person_name="Elliot Nash")
    checked_in = check_in_pass(world, support_pass)
    checked_out = get_success_data(
        api_client.check_out_pass(support_pass["id"], world.access_headers)
    )
    set_clock(CLOCK_LATER)
    return {
        "world": world,
        "encounter": encounter,
        "pass": support_pass,
        "checked_in": checked_in,
        "checked_out": checked_out,
    }


def test_the_release_stamps_the_clock_and_credits_the_entry_back(
    the_only_covering_row_released_half_an_hour_later,
):
    """"Releasing a row is a `ChargeNurse` act: `status` becomes `RELEASED`,
    `released_at` becomes the current instant, and the covering entry is credited
    back exactly `acuity_units_consumed`."

    Design: Corner/state_machines/releasing_the_only_assignment_credits_the_shift_back_and_breaches_the_staffing_axis
    """
    setup = the_only_covering_row_released_half_an_hour_later
    row = setup["released"]
    assert_care_assignment(row)
    assert row["status"] == "RELEASED"
    assert_instant_equals(row["released_at"], CLOCK_LATER, "released_at")
    assert row["acuity_units_consumed"] == pytest.approx(RATIO_DEBIT, abs=1e-9)
    assert row["superseded_by_assignment_id"] is None
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], setup["world"].charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["assigned_acuity_load_units"] == pytest.approx(0.0, abs=1e-9)
    assert shift["capacity_units_effective"] == pytest.approx(CHARGE_CAPACITY, abs=1e-9)


def test_the_release_drops_the_encounter_into_a_breach(
    the_only_covering_row_released_half_an_hour_later,
):
    """"Releasing the last `ACTIVE` row drives the encounter to `RELEASED` when
    its `labor_phase` is `POSTPARTUM_RECOVERY`, `DISCHARGED` or
    `TRANSFERRED_OUT`, and to `COVERAGE_BREACH` in any earlier phase — again
    recorded rather than refused."

    Design: Corner/state_machines/releasing_the_only_assignment_credits_the_shift_back_and_breaches_the_staffing_axis
    """
    setup = the_only_covering_row_released_half_an_hour_later
    assert setup["covered"]["staffing_state"] == "RATIO_COVERED"
    encounter = reload_encounter(setup["world"], setup["encounter"]["id"])
    assert_labor_encounter(encounter)
    assert encounter["labor_phase"] == "ANTEPARTUM"
    assert encounter["staffing_state"] == "COVERAGE_BREACH"
    assert encounter["assigned_coverage_units"] == pytest.approx(0.0, abs=1e-9)
    assert encounter["required_coverage_units"] == pytest.approx(RATIO_DEBIT, abs=1e-9)


def test_the_uncovered_encounter_becomes_the_units_whole_deficit(
    the_only_covering_row_released_half_an_hour_later,
):
    """"`coverage_deficit_units` is recomputed as the sum, over every encounter
    in the unit whose `labor_phase` is one of the six non-terminal phases, of the
    larger of 0.0 and `required_coverage_units` less `assigned_coverage_units`,
    rounded to one decimal place with halves away from zero."

    Design: Corner/state_machines/releasing_the_only_assignment_credits_the_shift_back_and_breaches_the_staffing_axis
    """
    unit = the_only_covering_row_released_half_an_hour_later["world"].reload_unit()
    assert_obstetric_unit(unit)
    assert unit["coverage_deficit_units"] == pytest.approx(0.5, abs=1e-9)


def test_a_replayed_check_out_is_refused_rather_than_absorbed(
    a_partner_pass_taken_out_of_the_room,
):
    """"A `PatientAccessCoordinator` checks the person out again with no
    preconditions, moving the pass from `CHECKED_IN` to `CHECKED_OUT`, setting
    `checked_out_at` and freeing an occupancy slot" — the edge starts at
    `CHECKED_IN` only, so a second call from `CHECKED_OUT` is an undeclared
    transition at HTTP 409 rather than a second success.

    Design: Corner/state_machines/a_second_check_out_on_an_already_checked_out_pass_is_rejected_rather_than_absorbed
    """
    setup = a_partner_pass_taken_out_of_the_room
    assert setup["checked_out"]["status"] == "CHECKED_OUT"
    replay = api_client.check_out_pass(
        setup["pass"]["id"], setup["world"].access_headers
    )
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)


def test_the_refused_replay_overwrites_no_instant_and_counts_no_reentry(
    a_partner_pass_taken_out_of_the_room,
):
    """"A re-entry from `CHECKED_OUT` requires `reentry_count` to be less than 3,
    refused otherwise with `ERR_SUPPORT_REENTRY_LIMIT_REACHED`, and increments
    `reentry_count` by 1; a first check-in from `ISSUED` does not touch that
    counter." Only a check-in moves that counter, so the refused check-out leaves
    it at 0 and leaves the 06:00 instants alone.

    Design: Corner/state_machines/a_second_check_out_on_an_already_checked_out_pass_is_rejected_rather_than_absorbed
    """
    setup = a_partner_pass_taken_out_of_the_room
    world = setup["world"]
    api_client.check_out_pass(setup["pass"]["id"], world.access_headers)
    replayed = reload_pass(world, setup["pass"]["id"])
    assert_support_pass(replayed)
    assert replayed["status"] == "CHECKED_OUT"
    assert_instant_equals(replayed["checked_out_at"], CLOCK_START, "checked_out_at")
    assert_instant_equals(replayed["checked_in_at"], CLOCK_START, "checked_in_at")
    assert replayed["reentry_count"] == 0
    assert_instant_equals(replayed["valid_until"], PASS_VALID_UNTIL, "valid_until")
    assert replayed["version"] == setup["checked_out"]["version"]


@pytest.fixture
def a_partner_pass_walked_back_in():
    """The same pass cycle, but with the 06:30 call being a check-in."""
    world = _unit("Peregrine Womens Health LDR")
    encounter = create_encounter(
        world,
        patient_record_code="PRC-PASS-1111",
        parity=1,
        gestational_age_weeks=40,
    )
    support_pass = create_pass(world, encounter, person_name="Rosa Kaminski")
    first_entry = check_in_pass(world, support_pass)
    checked_out = get_success_data(
        api_client.check_out_pass(support_pass["id"], world.access_headers)
    )
    set_clock(CLOCK_LATER)
    reentered = check_in_pass(world, support_pass)
    return {
        "world": world,
        "pass": support_pass,
        "first_entry": first_entry,
        "checked_out": checked_out,
        "reentered": reentered,
    }


def test_the_cyclic_entry_is_the_only_one_that_counts(a_partner_pass_walked_back_in):
    """"A re-entry from `CHECKED_OUT` requires `reentry_count` to be less than 3,
    refused otherwise with `ERR_SUPPORT_REENTRY_LIMIT_REACHED`, and increments
    `reentry_count` by 1; a first check-in from `ISSUED` does not touch that
    counter."

    Design: Corner/state_machines/support_pass_reentry_returns_to_checked_in_and_advances_reentry_count_to_one
    """
    setup = a_partner_pass_walked_back_in
    assert setup["first_entry"]["reentry_count"] == 0
    assert setup["checked_out"]["status"] == "CHECKED_OUT"
    back = setup["reentered"]
    assert_support_pass(back)
    assert back["status"] == "CHECKED_IN"
    assert back["reentry_count"] == 1


def test_the_reentry_restamps_the_clock_without_renewing_the_pass(
    a_partner_pass_walked_back_in,
):
    """"Success sets `checked_in_at` to the current instant and clears
    `checked_out_at` to null." The 24-hour horizon was fixed at issuance, so
    walking back in re-stamps the entry instant and leaves `valid_until` alone.

    Design: Corner/state_machines/support_pass_reentry_returns_to_checked_in_and_advances_reentry_count_to_one
    """
    setup = a_partner_pass_walked_back_in
    back = reload_pass(setup["world"], setup["pass"]["id"])
    assert_support_pass(back)
    assert_instant_equals(back["checked_in_at"], CLOCK_LATER, "checked_in_at")
    assert_instant_is_null(back["checked_out_at"], "checked_out_at")
    assert_instant_equals(back["valid_until"], PASS_VALID_UNTIL, "valid_until")
