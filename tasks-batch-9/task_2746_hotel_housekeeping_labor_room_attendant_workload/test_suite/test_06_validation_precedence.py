"""Which error the caller sees when a request breaks two rules at once."""

from test_helpers import (
    COMPLIANCE_BREACH_BLOCKED,
    DIRECTOR_HEADERS,
    ORDINANCE_NONE,
    ROSTER_CLOSED,
    SERVICE_CHECKOUT,
    SERVICE_DEEP_CLEAN,
    ApiErrorId,
    assert_cents,
    assert_credits,
    assert_roster_totals,
    assert_whole_minutes,
    assignment_payload,
    build_scenario,
    build_second_property,
    patch_attendant,
    read_roster,
    roster_close_payload,
    validate_error,
    validate_paginated,
)


# --------------------------------------------------------------------------
# A closed roster outranks the workload breach
# --------------------------------------------------------------------------


def _closed_roster_still_over_its_reduced_cap(api):
    """A settled roster whose 4.00 credits sit above a cap cut to 3.00."""
    scenario = build_scenario(
        api,
        property_overrides={
            "ordinance_profile": ORDINANCE_NONE,
            "max_daily_credits": 4.00,
        },
        rooms=["103", "104", "105"],
        linen={"total_owned_sets": 20},
    )
    first = scenario.clean(
        "103",
        SERVICE_DEEP_CLEAN,
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T10:30:00.000Z",
    )
    scenario.clean(
        "104",
        SERVICE_DEEP_CLEAN,
        "2026-08-03T10:50:00.000Z",
        "2026-08-03T11:20:00.000Z",
    )
    scenario.inspect(first["id"])
    patch_attendant(api, scenario.worker_id, restricted_duty=True)
    scenario.close_roster(300, 30)
    return scenario


def test_closed_roster_state_outranks_the_workload_breach_on_assignment_create(api):
    """The settled roster answers with its own state, not with the ordinance breach.

    PRD 2.10: "A roster must be `CLOCKED_IN` before a room on it may be started
    or completed and before an inspection may be recorded against it, or
    `ERR_ROSTER_NOT_CLOCKED_IN`; any mutation targeting a roster already in
    `CLOSED` yields `ERR_ROSTER_ALREADY_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_roster_state_outranks_workload_breach_on_assignment_create
    """
    scenario = _closed_roster_still_over_its_reduced_cap(api)
    settled = read_roster(api, scenario.roster_id)
    assert settled["status"] == ROSTER_CLOSED
    assert settled["compliance_state"] == COMPLIANCE_BREACH_BLOCKED
    scenario.refresh_roster_version()

    response = scenario.assign_raw(
        "105", SERVICE_DEEP_CLEAN, headers=scenario.supervisor_headers()
    )

    error = validate_error(response, ApiErrorId.ROSTER_ALREADY_CLOSED)
    assert error["error_id"] != ApiErrorId.ROSTER_WORKLOAD_BREACH.value, (
        "the target-state precondition sits above the ordinance freeze"
    )


def test_refused_create_on_a_closed_roster_writes_nothing(api):
    """No assignment row appears for the third room and the credit total is unmoved.

    PRD 2.9: "`ShiftRoster.assigned_credits` and `assigned_square_feet` are
    recomputed from the roster's counted set, and `compliance_state` is
    recomputed immediately afterwards, on every event that changes any
    assignment's `status` or `credits`, on any change to the rostered attendant's
    `restricted_duty` flag, and on any waiver decision."

    Design: Difficulty/priority_pair_validation_conflict/closed_roster_state_outranks_workload_breach_on_assignment_create
    """
    scenario = _closed_roster_still_over_its_reduced_cap(api)
    scenario.refresh_roster_version()

    scenario.assign_raw(
        "105", SERVICE_DEEP_CLEAN, headers=scenario.supervisor_headers()
    )

    rows, meta = validate_paginated(
        api.list_room_assignments(
            {"room_id": scenario.room_id("105")}, DIRECTOR_HEADERS
        )
    )
    assert meta["total_count"] == 0, (
        f"no assignment should exist for room 105, found {meta['total_count']}"
    )
    assert rows == []
    assert_credits(
        read_roster(api, scenario.roster_id)["assigned_credits"],
        4.00,
        "assigned_credits",
    )


# --------------------------------------------------------------------------
# Property scope coherence outranks occupancy coherence
# --------------------------------------------------------------------------


def _two_properties(api):
    """A rostered property, plus a second property holding one vacant room."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}],
        linen={"total_owned_sets": 20},
    )
    other = build_second_property(api)
    return scenario, other


def test_property_scope_mismatch_outranks_the_occupancy_mismatch(api):
    """A foreign vacant room is refused as a scope mismatch, not an occupancy mismatch.

    PRD 2.10: "Because scope coherence sits above every state and capacity rule,
    a cross-property request is rejected as a scope mismatch even when it would
    also have breached a credit ceiling."

    Design: Difficulty/priority_pair_validation_conflict/property_scope_mismatch_outranks_occupancy_mismatch
    """
    scenario, other = _two_properties(api)

    response = api.create_room_assignment(
        assignment_payload(
            scenario.roster_id,
            other.room_id("901"),
            scenario.roster_version,
            SERVICE_CHECKOUT,
        ),
        scenario.supervisor_headers(),
    )

    error = validate_error(response, ApiErrorId.PROPERTY_SCOPE_MISMATCH, 409)
    assert error["error_id"] != ApiErrorId.OCCUPANCY_MISMATCH.value, (
        "a CHECKOUT against a VACANT room in another property is a scope failure first"
    )


def test_scope_mismatch_leaves_the_roster_totals_and_version_untouched(api):
    """The refused cross-property create moves neither total nor the roster version.

    PRD 2.5: "All entities named by a single request must belong to the same
    `Property`."

    Design: Difficulty/priority_pair_validation_conflict/property_scope_mismatch_outranks_occupancy_mismatch
    """
    scenario, other = _two_properties(api)
    version_before = scenario.roster_version

    api.create_room_assignment(
        assignment_payload(
            scenario.roster_id,
            other.room_id("901"),
            version_before,
            SERVICE_CHECKOUT,
        ),
        scenario.supervisor_headers(),
    )

    roster = read_roster(api, scenario.roster_id)
    assert_roster_totals(roster, 0.00, 0)
    assert roster["version"] == version_before, (
        f"roster version should still be {version_before}, got {roster['version']}"
    )


# --------------------------------------------------------------------------
# A closed roster outranks the implausible worked minutes
# --------------------------------------------------------------------------


def _settled_roster(api):
    """One departure clean, one passing inspection, and a 300-minute settlement."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}],
        linen={"total_owned_sets": 20},
    )
    first = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T10:30:00.000Z",
    )
    scenario.inspect(first["id"])
    scenario.close_roster(300, 30)
    return scenario


def test_closed_roster_state_outranks_implausible_worked_minutes(api):
    """A 900-minute second close is refused for the roster's state, not its arithmetic.

    PRD 3.7: "The roster must be `CLOCKED_IN`; a close aimed at a roster already
    `CLOSED` is `ERR_ROSTER_ALREADY_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_roster_state_outranks_worked_minutes_implausible
    """
    scenario = _settled_roster(api)

    response = api.close_roster(
        scenario.roster_id, roster_close_payload(900, 10), DIRECTOR_HEADERS
    )

    error = validate_error(response, ApiErrorId.ROSTER_ALREADY_CLOSED)
    assert error["error_id"] != ApiErrorId.WORKED_MINUTES_IMPLAUSIBLE.value, (
        "the state precondition is checked before the plausibility ceiling"
    )


def test_refused_second_close_preserves_the_first_settlement(api):
    """The settlement written by the accepted close survives the refused replay.

    PRD 3.7: "`base_wage_cents` is `paid_minutes` multiplied by the attendant's
    `hourly_rate_cents` and divided by 60, rounded half up to a whole cent."

    Design: Difficulty/priority_pair_validation_conflict/closed_roster_state_outranks_worked_minutes_implausible
    """
    scenario = _settled_roster(api)

    api.close_roster(
        scenario.roster_id, roster_close_payload(900, 10), DIRECTOR_HEADERS
    )

    roster = read_roster(api, scenario.roster_id)
    assert_whole_minutes(roster["worked_minutes"], 300, "worked_minutes")
    assert_whole_minutes(roster["paid_minutes"], 300, "paid_minutes")
    assert_cents(roster["base_wage_cents"], 15000, "base_wage_cents")
    assert_cents(roster["total_labor_cost_cents"], 15000, "total_labor_cost_cents")
