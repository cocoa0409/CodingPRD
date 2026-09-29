"""Compensating moves that must put a conserved quantity back exactly where it was."""

from test_helpers import (
    ASSIGN_CANCELLED,
    COMPLIANCE_AT_LIMIT,
    COMPLIANCE_COMPLIANT,
    CYCLE_QUEUED,
    CYCLE_VOIDED,
    DIRECTOR_HEADERS,
    ENROLLMENT_ACTIVE,
    ENROLLMENT_VOIDED,
    ORDINANCE_NONE,
    PROGRAM_DAILY,
    PROGRAM_OPT_OUT,
    SERVICE_CHECKOUT,
    SHORTAGE_OK,
    assert_coverage_ratio,
    assert_credits,
    assert_linen_buckets,
    assert_roster_totals,
    build_enrollment,
    build_scenario,
    dispatch_cycle,
    read_cycle,
    read_day,
    read_linen_item,
    read_property,
    read_room,
    read_roster,
    validate_success,
    void_cycle,
)


# --------------------------------------------------------------------------
# The day's conserved credit total
# --------------------------------------------------------------------------


def _day_with_one_allocated_room(api):
    """One departure clean allocated on an otherwise empty published day."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}],
        linen={"total_owned_sets": 20},
    )
    return scenario, scenario.assign("101", SERVICE_CHECKOUT)


def test_cancelling_the_only_assignment_restores_the_days_pre_create_total(api):
    """The day's allocated total rises to 1.00 on the create and returns to 0.00.

    PRD 3.4: "The forecast day's `allocated_credits_total` is recomputed, restoring
    the conserved day quantity exactly to its pre-create value, and both the
    assignment's and the roster's `version` increment, with the new roster version
    reported as `roster_version_after`."

    Design: Difficulty/compensating_invariant/forecast_day_allocated_credits_returns_to_pre_assignment_total_after_cancel
    """
    scenario, assignment = _day_with_one_allocated_room(api)
    assert_credits(
        read_day(api, scenario.day_id)["allocated_credits_total"],
        1.00,
        "allocated_credits_total",
    )

    cancelled = validate_success(
        api.cancel_assignment(assignment["id"], None, DIRECTOR_HEADERS), 200
    )

    assert cancelled["status"] == ASSIGN_CANCELLED
    assert_credits(
        read_day(api, scenario.day_id)["allocated_credits_total"],
        0.00,
        "allocated_credits_total",
    )
    assert cancelled["roster_version_after"] == read_roster(api, scenario.roster_id)[
        "version"
    ], "the cancel must report the roster version it produced"


def _roster_exactly_on_a_one_credit_ceiling(api):
    """A single departure clean sitting exactly on a 1.00-credit ceiling."""
    scenario = build_scenario(
        api,
        property_overrides={
            "ordinance_profile": ORDINANCE_NONE,
            "max_daily_credits": 1.00,
        },
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}],
        linen={"total_owned_sets": 20},
    )
    return scenario, scenario.assign("101", SERVICE_CHECKOUT)


def test_cancelling_releases_both_the_credits_and_the_square_feet(api):
    """Shedding the work drops the roster off its ceiling and back to COMPLIANT.

    PRD 3.4: "The roster's `assigned_credits` and `assigned_square_feet` are
    recomputed and its `compliance_state` re-derived — which is how a roster
    escapes `BREACH_BLOCKED` by shedding work, moving `BREACH_BLOCKED → COMPLIANT`
    or `AT_LIMIT → COMPLIANT` once the totals fall strictly below both ceilings."

    Design: Difficulty/compensating_invariant/forecast_day_allocated_credits_returns_to_pre_assignment_total_after_cancel
    """
    scenario, assignment = _roster_exactly_on_a_one_credit_ceiling(api)
    before = read_roster(api, scenario.roster_id)
    assert_roster_totals(before, 1.00, 420)
    assert before["compliance_state"] == COMPLIANCE_AT_LIMIT

    validate_success(
        api.cancel_assignment(assignment["id"], None, DIRECTOR_HEADERS), 200
    )

    roster = read_roster(api, scenario.roster_id)
    assert_roster_totals(roster, 0.00, 0)
    assert roster["compliance_state"] == COMPLIANCE_COMPLIANT


# --------------------------------------------------------------------------
# The linen ledger identity
# --------------------------------------------------------------------------


def _dispatched_batch_still_at_the_kerb(api):
    """Eight of twenty sets dispatched from a line holding twelve clean."""
    scenario = build_scenario(
        api,
        rooms=["101", "102"],
        linen={"total_owned_sets": 20, "initial_soiled_sets": 8},
        with_day=False,
        with_roster=False,
    )
    before = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(before, 12, 0, 8)
    cycle = dispatch_cycle(
        api,
        scenario.linen_id,
        8,
        "2026-08-03T08:00:00.000Z",
        "2026-08-03T12:00:00.000Z",
        before["version"],
    )
    assert cycle["status"] == CYCLE_QUEUED
    assert_linen_buckets(read_linen_item(api, scenario.linen_id), 12, 8, 0)
    return scenario, before, cycle


def test_voiding_the_dispatch_puts_every_set_back_where_it_began(api):
    """The eight sets return from the laundry bucket to the soiled queue exactly.

    PRD 3.8: "The void advances `QUEUED → VOIDED` and moves `batch_sets` out of
    `in_laundry` and back into `soiled_queue` — the exact compensation of the
    dispatch, leaving the ledger where it began."

    Design: Difficulty/compensating_invariant/linen_ledger_three_bucket_identity_restored_by_laundry_void
    """
    scenario, before, cycle = _dispatched_batch_still_at_the_kerb(api)

    voided = void_cycle(api, cycle["id"])

    assert voided["status"] == CYCLE_VOIDED
    line = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(line, 12, 0, 8)
    assert line["total_owned_sets"] == before["total_owned_sets"], (
        "a void writes nothing off, so the owned count must not move"
    )
    assert read_cycle(api, cycle["id"])["status"] == CYCLE_VOIDED


def test_the_void_re_derives_the_lines_health_and_reports_its_new_version(api):
    """Coverage and the shortage rung come back unchanged, on a freshly bumped version.

    PRD 3.8: "The line's `coverage_ratio` and `shortage_status` are re-derived and
    both versions increment, with the new line version reported as
    `linen_item_version_after`."

    Design: Difficulty/compensating_invariant/linen_ledger_three_bucket_identity_restored_by_laundry_void
    """
    scenario, before, cycle = _dispatched_batch_still_at_the_kerb(api)
    assert_coverage_ratio(before["coverage_ratio"], 3.0000)

    voided = void_cycle(api, cycle["id"])

    line = read_linen_item(api, scenario.linen_id)
    assert_coverage_ratio(line["coverage_ratio"], 3.0000)
    assert line["shortage_status"] == SHORTAGE_OK
    assert voided["linen_item_version_after"] == line["version"], (
        "the void must report the linen version it produced"
    )
    assert line["version"] > before["version"], (
        f"the line version should have moved past {before['version']}, "
        f"got {line['version']}"
    )


# --------------------------------------------------------------------------
# The guest incentive reversal
# --------------------------------------------------------------------------


def _opted_out_stay_with_two_skips_accrued(api):
    """A three-night opt-out enrolment carrying two skips and 1000 points."""
    context = build_enrollment(api, program=PROGRAM_OPT_OUT, nights=3)
    assert context.enrollment["points_per_skip"] == 500
    context.accrue()
    accrued = context.accrue()
    assert accrued["status"] == ENROLLMENT_ACTIVE
    assert accrued["skips_accrued"] == 2
    assert accrued["points_accrued"] == 1000
    return context


def test_voiding_the_enrolment_zeroes_the_points_and_the_property_balance(api):
    """Both the accrued points and the property's outstanding balance go back to zero.

    PRD 3.9: "The void advances `ACTIVE → VOIDED`, zeroes both `skips_accrued` and
    `points_accrued`, restores the room's `service_program` to `DAILY` — the exact
    compensation of the creation side effect, so the room becomes eligible for
    ordinary checkout and stayover work again — and recomputes the property's
    `outstanding_incentive_points` back to its pre-enrolment value."

    Design: Difficulty/compensating_invariant/guest_incentive_points_and_room_program_both_reversed_by_enrollment_void
    """
    context = _opted_out_stay_with_two_skips_accrued(api)
    assert read_property(api, context.prop["id"])["outstanding_incentive_points"] == 1000

    voided = context.void()

    assert voided["status"] == ENROLLMENT_VOIDED
    assert voided["skips_accrued"] == 0
    assert voided["points_accrued"] == 0
    assert read_property(api, context.prop["id"])["outstanding_incentive_points"] == 0, (
        "the property balance must return to its pre-enrolment value"
    )


def test_voiding_the_enrolment_returns_the_room_to_the_daily_programme(api):
    """The room's programme is rewritten back to DAILY and its version moves.

    PRD 3.9: "Both the enrolment's and the room's `version` increment."

    Design: Difficulty/compensating_invariant/guest_incentive_points_and_room_program_both_reversed_by_enrollment_void
    """
    context = _opted_out_stay_with_two_skips_accrued(api)
    before = read_room(api, context.room["id"])
    assert before["service_program"] == PROGRAM_OPT_OUT

    context.void()

    room = read_room(api, context.room["id"])
    assert room["service_program"] == PROGRAM_DAILY, (
        f"the room programme should be restored to DAILY, got {room['service_program']}"
    )
    assert room["version"] > before["version"], (
        f"the room version should have moved past {before['version']}, "
        f"got {room['version']}"
    )
