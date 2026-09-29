"""One coverage row, two parents, one denormalised staff id.

The junction row must surface both when the list is filtered by its encounter and
when it is filtered by its roster entry, and the staff id it carries is the roster
entry's, not the caller's.
"""

import pytest

from test_helpers import (
    api_client,
    assert_care_assignment,
    assert_shift_assignment,
    bootstrap_unit,
    create_active_shift,
    create_care_assignment,
    create_encounter,
    get_success_data,
    reload_encounter,
)

CLOCK_START = "2026-08-01T06:00:00Z"
SHIFT_START = "2026-08-01T05:00:00Z"
SHIFT_END = "2026-08-01T15:00:00Z"
CHARGE_CAPACITY = 2.0
RATIO_DEBIT = 0.5

JUNCTION_STAFF = {
    "charge": {
        "full_name": "Dana Okoye RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-06-30T00:00:00Z",
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_junction_row_between_one_shift_and_one_encounter():
    """A charge nurse covering a single antepartum patient in ratio-shared mode."""
    world = bootstrap_unit(
        clock=CLOCK_START,
        ldr_beds=4,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR")],
        staff_specs=JUNCTION_STAFF,
        unit_overrides={"unit_name": "Redbud Perinatal Institute LDR"},
    )
    shift = create_active_shift(world, "charge", "CHARGE", SHIFT_START, SHIFT_END)
    encounter = create_encounter(
        world,
        patient_record_code="PRC-JXN-6006",
        parity=0,
        gestational_age_weeks=39,
    )
    assignment = create_care_assignment(
        world, encounter, shift, coverage_mode="RATIO_SHARED"
    )
    return {
        "world": world,
        "shift": shift,
        "encounter": encounter,
        "assignment": assignment,
    }


def test_the_same_row_surfaces_under_both_of_its_parents(
    one_junction_row_between_one_shift_and_one_encounter,
):
    """"Rows may be listed filtered by `encounter_id`, `shift_assignment_id`,
    `staff_id`, `coverage_mode`, `status` and `superseded_by_assignment_id`,
    ordered by `created_at` ascending", and "The new row opens in `ACTIVE` with `staff_id` denormalised from the roster entry,
    and carries `acuity_units_consumed`, `released_at` and
    `superseded_by_assignment_id` as its remaining state.".

    Design: Corner/entities/care_assignment_junction_row_is_reachable_from_both_the_encounter_and_the_shift
    """
    setup = one_junction_row_between_one_shift_and_one_encounter
    world = setup["world"]
    assignment = setup["assignment"]
    assert_care_assignment(assignment)
    by_encounter = api_client.list_care_assignments(
        world.charge_headers,
        params={"encounter_id": setup["encounter"]["id"], "limit": 10},
    ).json()["data"]
    by_shift = api_client.list_care_assignments(
        world.charge_headers,
        params={"shift_assignment_id": setup["shift"]["id"], "limit": 10},
    ).json()["data"]
    assert len(by_encounter) == 1
    assert len(by_shift) == 1
    assert by_encounter[0]["id"] == assignment["id"]
    assert by_shift[0]["id"] == assignment["id"]
    assert by_encounter[0]["staff_id"] == world.staff_id("charge")
    assert by_shift[0]["coverage_mode"] == "RATIO_SHARED"
    assert assignment["status"] == "ACTIVE"
    assert assignment["superseded_by_assignment_id"] is None
    assert assignment["released_at"] is None
    assert assignment["acuity_units_consumed"] == pytest.approx(RATIO_DEBIT, abs=1e-9)
    encounter = reload_encounter(world, setup["encounter"]["id"])
    assert encounter["assigned_coverage_units"] == pytest.approx(RATIO_DEBIT, abs=1e-9)
    assert encounter["staffing_state"] == "RATIO_COVERED"
    shift = get_success_data(
        api_client.get_shift(setup["shift"]["id"], world.charge_headers)
    )
    assert_shift_assignment(shift)
    assert shift["assigned_acuity_load_units"] == pytest.approx(RATIO_DEBIT, abs=1e-9)
    assert shift["capacity_units_effective"] == pytest.approx(
        CHARGE_CAPACITY, abs=1e-9
    )
    assert world.reload_unit()["coverage_deficit_units"] == pytest.approx(0.0, abs=1e-9)
