"""Four laps around the visitor door, and one pass that expires without a sweep.

The counter is proved to count returns rather than arrivals: the arrival from
`ISSUED` leaves it at zero and only the three returns move it, so the refusal
lands on the fourth return and not the fourth check-in. The second pass is then
offered at the exact instant its window closes with no capacity sweep anywhere in
the chain, which separates the stored status from the guarded action — the row is
still `ISSUED`, because only the sweep may rewrite it, while the door is already
shut, because the guard reads the clock.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_instant_is_null,
    assert_obstetric_unit,
    assert_support_pass,
    assign_bed,
    bootstrap_unit,
    create_encounter,
    get_success_data,
    set_clock,
)

CLOCK_ISSUED = "2026-08-01T06:00:00Z"
VALID_UNTIL = "2026-08-02T06:00:00Z"
REENTRY_LIMIT = 3
LIVE_CREDENTIAL = "2027-06-30T00:00:00Z"
FIRST_VISITOR = "Ellery Vandergraaf"
SECOND_VISITOR = "Marguerite Ashdown"

LARKSPUR_STAFF = {
    "charge": {
        "full_name": "Isadora Fenwicke RN",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": LIVE_CREDENTIAL,
        "or_circulating_qualified": False,
    },
}


@pytest.fixture
def one_pass_walked_around_four_times_and_one_offered_too_late():
    """Two `PARTNER` passes on one bedded antepartum encounter, issued at the same instant.

    The unit is left exactly as bootstrapped, with no validated drill, so its
    readiness sits at `NOT_READY` and its posture at `INDUCTION_FROZEN`; that clamps
    the visitor allowance to one, which is why the two passes are never in the room
    together and why every check-in below is offered with the room empty.
    """
    world = bootstrap_unit(
        clock=CLOCK_ISSUED,
        ldr_beds=3,
        or_rooms=1,
        bed_specs=[("LDR-01", "LDR"), ("LDR-02", "LDR")],
        staff_specs=LARKSPUR_STAFF,
        unit_overrides={"unit_name": "Larkspur Meadows Birth Center LDR"},
    )
    encounter = create_encounter(
        world,
        patient_record_code="PRC-LARK-2201",
        parity=3,
        gestational_age_weeks=40,
    )
    assign_bed(world, encounter, "LDR-01")
    unit_while_frozen = world.reload_unit()
    pass_a = api_client.create_pass(
        {
            "encounter_id": encounter["id"],
            "person_name": FIRST_VISITOR,
            "credential_type": "PARTNER",
        },
        world.access_headers,
    )
    pass_b = api_client.create_pass(
        {
            "encounter_id": encounter["id"],
            "person_name": SECOND_VISITOR,
            "credential_type": "PARTNER",
        },
        world.access_headers,
    )
    pass_a_id = get_success_data(pass_a)["id"]
    pass_b_id = get_success_data(pass_b)["id"]

    def _check_in():
        return api_client.check_in_pass(pass_a_id, world.access_headers)

    def _check_out():
        return api_client.check_out_pass(pass_a_id, world.access_headers)

    arrivals = [_check_in()]
    departures = []
    for _ in range(REENTRY_LIMIT):
        departures.append(_check_out())
        arrivals.append(_check_in())
    departures.append(_check_out())
    fourth_return = _check_in()
    pass_a_at_the_end = get_success_data(
        api_client.get_pass(pass_a_id, world.access_headers)
    )
    set_clock(VALID_UNTIL)
    offered_at_the_closing_instant = api_client.check_in_pass(
        pass_b_id, world.access_headers
    )
    pass_b_at_the_end = get_success_data(
        api_client.get_pass(pass_b_id, world.access_headers)
    )
    return {
        "world": world,
        "encounter": encounter,
        "unit_while_frozen": unit_while_frozen,
        "pass_a": pass_a,
        "pass_b": pass_b,
        "arrivals": arrivals,
        "departures": departures,
        "fourth_return": fourth_return,
        "pass_a_at_the_end": pass_a_at_the_end,
        "offered_at_the_closing_instant": offered_at_the_closing_instant,
        "pass_b_at_the_end": pass_b_at_the_end,
    }


def test_both_passes_open_with_a_twenty_four_hour_window_and_no_occupancy(
    one_pass_walked_around_four_times_and_one_offered_too_late,
):
    """"The pass opens at `ISSUED` with `valid_until` set to the current instant plus 24
    hours, and an issued pass occupies nothing until it is checked in."

    Design: Corner/errors/both_support_pass_ids_from_four_reentry_laps_and_one_pass_that_expires_without_a_sweep
    """
    setup = one_pass_walked_around_four_times_and_one_offered_too_late
    for response, person in (
        (setup["pass_a"], FIRST_VISITOR),
        (setup["pass_b"], SECOND_VISITOR),
    ):
        assert response.status_code == 201
        issued = get_success_data(response)
        assert_support_pass(issued)
        assert issued["status"] == "ISSUED"
        assert issued["person_name"] == person
        assert issued["credential_type"] == "PARTNER"
        assert issued["reentry_count"] == 0
        assert_instant_equals(issued["valid_until"], VALID_UNTIL, "valid_until")
        assert_instant_is_null(issued["checked_in_at"], "checked_in_at")
        assert_instant_is_null(issued["checked_out_at"], "checked_out_at")


def test_the_frozen_posture_is_why_only_one_visitor_is_ever_at_the_door(
    one_pass_walked_around_four_times_and_one_offered_too_late,
):
    """"If the unit's `staffing_posture` is `INDUCTION_FROZEN` or `DIVERT`, the allowance
    is reduced to 1 whenever it was larger than 1."

    Design: Corner/errors/both_support_pass_ids_from_four_reentry_laps_and_one_pass_that_expires_without_a_sweep
    """
    setup = one_pass_walked_around_four_times_and_one_offered_too_late
    unit = setup["unit_while_frozen"]
    assert_obstetric_unit(unit)
    assert unit["cesarean_readiness_state"] == "NOT_READY"
    assert unit["staffing_posture"] == "INDUCTION_FROZEN"
    assert setup["encounter"]["labor_phase"] == "ANTEPARTUM"


def test_the_arrival_from_issued_does_not_touch_the_counter(
    one_pass_walked_around_four_times_and_one_offered_too_late,
):
    """"A `PatientAccessCoordinator` checks the person in, moving the pass from `ISSUED`
    or — as the cycle re-entry — from `CHECKED_OUT` to `CHECKED_IN`."

    Design: Corner/errors/both_support_pass_ids_from_four_reentry_laps_and_one_pass_that_expires_without_a_sweep
    """
    setup = one_pass_walked_around_four_times_and_one_offered_too_late
    first = setup["arrivals"][0]
    assert first.status_code == 200
    arrived = get_success_data(first)
    assert_support_pass(arrived)
    assert arrived["status"] == "CHECKED_IN"
    assert arrived["reentry_count"] == 0
    assert_instant_equals(arrived["checked_in_at"], CLOCK_ISSUED, "checked_in_at")


def test_each_departure_stamps_the_checkout_and_frees_the_room(
    one_pass_walked_around_four_times_and_one_offered_too_late,
):
    """"A `PatientAccessCoordinator` checks the person out again with no preconditions,
    moving the pass from `CHECKED_IN` to `CHECKED_OUT`, setting `checked_out_at` and
    freeing an occupancy slot — the manual counterpart of the automatic checkout inside
    team mobilisation."

    Design: Corner/errors/both_support_pass_ids_from_four_reentry_laps_and_one_pass_that_expires_without_a_sweep
    """
    setup = one_pass_walked_around_four_times_and_one_offered_too_late
    assert len(setup["departures"]) == REENTRY_LIMIT + 1
    for response in setup["departures"]:
        assert response.status_code == 200
        departed = get_success_data(response)
        assert_support_pass(departed)
        assert departed["status"] == "CHECKED_OUT"
        assert_instant_equals(departed["checked_out_at"], CLOCK_ISSUED, "checked_out_at")


def test_the_three_returns_step_the_counter_one_two_three(
    one_pass_walked_around_four_times_and_one_offered_too_late,
):
    """"A re-entry from `CHECKED_OUT` requires `reentry_count` to be less than 3, refused
    otherwise with `ERR_SUPPORT_REENTRY_LIMIT_REACHED`, and increments `reentry_count` by
    1; a first check-in from `ISSUED` does not touch that counter." Also: "Success sets
    `checked_in_at` to the current instant and clears `checked_out_at` to null."

    Design: Corner/errors/both_support_pass_ids_from_four_reentry_laps_and_one_pass_that_expires_without_a_sweep
    """
    setup = one_pass_walked_around_four_times_and_one_offered_too_late
    returns = setup["arrivals"][1:]
    assert len(returns) == REENTRY_LIMIT
    observed = []
    for response in returns:
        assert response.status_code == 200
        returned = get_success_data(response)
        assert_support_pass(returned)
        assert returned["status"] == "CHECKED_IN"
        assert_instant_is_null(returned["checked_out_at"], "checked_out_at")
        observed.append(returned["reentry_count"])
    assert observed == [1, 2, 3]


def test_the_fourth_return_names_the_reentry_limit(
    one_pass_walked_around_four_times_and_one_offered_too_late,
):
    """"**Priority 8** — the declared-transition guard, on every action operation: an
    attempt to move a record from a state for which the requested edge is not declared
    yields `ERR_INVALID_STATE_TRANSITION` at HTTP 409." A return from `CHECKED_OUT` is a
    declared edge, so the transition guard has nothing to say about this call.

    Design: Corner/errors/both_support_pass_ids_from_four_reentry_laps_and_one_pass_that_expires_without_a_sweep
    """
    setup = one_pass_walked_around_four_times_and_one_offered_too_late
    refused = setup["fourth_return"]
    validate_error(refused, ApiErrorId.ERR_SUPPORT_REENTRY_LIMIT_REACHED.value, 409)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    assert reported != ApiErrorId.ERR_SUPPORT_OCCUPANCY_EXCEEDED.value


def test_the_refused_return_leaves_the_pass_outside_with_its_three_laps(
    one_pass_walked_around_four_times_and_one_offered_too_late,
):
    """"**Priority 15** — capacity and quota, checked after everything else and always
    with an inclusive boundary, so that landing exactly on a limit is allowed and only
    exceeding it fails: `ERR_STAFF_ACUITY_CAPACITY_EXCEEDED`,
    `ERR_INDUCTION_CAPACITY_EXCEEDED` and `ERR_SUPPORT_OCCUPANCY_EXCEEDED`, all at HTTP
    409, on care-assignment creation, shift relief, induction capacity holding, induction
    confirmation and support pass check-in." The room was empty, so the quota band was
    never the reason.

    Design: Corner/errors/both_support_pass_ids_from_four_reentry_laps_and_one_pass_that_expires_without_a_sweep
    """
    setup = one_pass_walked_around_four_times_and_one_offered_too_late
    survivor = setup["pass_a_at_the_end"]
    assert_support_pass(survivor)
    assert survivor["status"] == "CHECKED_OUT"
    assert survivor["reentry_count"] == REENTRY_LIMIT
    assert_instant_equals(survivor["checked_out_at"], CLOCK_ISSUED, "checked_out_at")


def test_the_boundary_instant_already_counts_as_expired(
    one_pass_walked_around_four_times_and_one_offered_too_late,
):
    """"The current instant must be strictly before `valid_until`, the boundary instant
    already counting as expired, refused otherwise with `ERR_SUPPORT_PASS_EXPIRED`."

    Design: Corner/errors/both_support_pass_ids_from_four_reentry_laps_and_one_pass_that_expires_without_a_sweep
    """
    setup = one_pass_walked_around_four_times_and_one_offered_too_late
    refused = setup["offered_at_the_closing_instant"]
    validate_error(refused, ApiErrorId.ERR_SUPPORT_PASS_EXPIRED.value, 422)
    reported = refused.json()["data"]["error_id"]
    assert reported != ApiErrorId.ERR_INVALID_STATE_TRANSITION.value
    assert reported != ApiErrorId.ERR_SUPPORT_REENTRY_LIMIT_REACHED.value


def test_only_the_sweep_may_write_the_expired_status(
    one_pass_walked_around_four_times_and_one_offered_too_late,
):
    """"The sweep expires an `ISSUED` or `CHECKED_OUT` pass once `valid_until` has passed."

    Design: Corner/errors/both_support_pass_ids_from_four_reentry_laps_and_one_pass_that_expires_without_a_sweep
    """
    setup = one_pass_walked_around_four_times_and_one_offered_too_late
    unswept = setup["pass_b_at_the_end"]
    assert_support_pass(unswept)
    assert unswept["status"] == "ISSUED"
    assert unswept["reentry_count"] == 0
    assert_instant_is_null(unswept["checked_in_at"], "checked_in_at")
    assert_instant_equals(unswept["valid_until"], VALID_UNTIL, "valid_until")
