"""The cohort lifecycle: launch branching, suspension, resumption, completion,
cancellation and the cascades they fire."""

import pytest

from test_helpers import (
    IC,
    PD,
    ApiErrorId,
    UNUSED_UUIDS,
    api_client,
    assert_cohort_seat_pool,
    assert_grant_money_pool,
    cohort_version,
    confirm_enrollment,
    create_assessed_participant,
    create_funding_allocation,
    create_grant_award,
    create_meeting_space,
    create_open_cohort,
    enroll,
    log_attendance,
    read_cohort,
    read_enrollment,
    read_funding_allocation,
    read_grant_award,
    read_outreach_plan,
    read_participant,
    setup_cohort_with_confirmed_seat,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_enrollment,
)


def test_launching_a_forming_cohort_is_an_invalid_state():
    """PRD 3.4: "When the `ProgramDirector` launches an `OPEN_ENROLLMENT` cohort
    whose `seats_filled` has reached or exceeded `min_viable_enrollment`, the
    cohort moves `OPEN_ENROLLMENT → RUNNING`: every enrollment in `CONFIRMED`
    advances `CONFIRMED → ATTENDING` — no seat movement occurs here, since a
    confirmed seat and an attending seat both count toward `seats_filled` — and
    every enrollment still in `HELD` is expired, each returning one unit from
    `seats_held` to `seats_open`."

    Design: Corner/state_machines/cohort_launch_from_forming_returns_invalid_state
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    cohort = validate_success(
        api_client.create_cohort(
            {"name": "Still Forming", "loss_type": "SUICIDE",
             "meeting_space_id": space["id"], "seats_total": 4,
             "min_viable_enrollment": 1, "weekday": "TUE", "start_minute_utc": 600,
             "duration_minutes": 90, "series_start_date": "2026-09-08",
             "sessions_total": 8, "direct_cost_cents": 100_000}, PD), 201)
    assert cohort["version"] == 1

    validate_error(api_client.launch_cohort(cohort["id"], PD),
                   ApiErrorId.ERR_INVALID_STATE.value, 409)

    refreshed = read_cohort(cohort["id"])
    assert refreshed["status"] == "FORMING"
    assert refreshed["version"] == 1, "a refused transition must not bump the version"


def test_launching_an_unknown_cohort_is_not_found():
    """PRD 2.5: "Every resource named by a path segment exists, validated from left
    to right, so the leftmost missing segment determines the reported error —
    otherwise the corresponding not-found error (404)."

    Design: Corner/errors/cohort_launch_with_unknown_id_returns_cohort_not_found
    """
    set_clock()
    validate_error(api_client.launch_cohort(UNUSED_UUIDS["cohort"], PD),
                   ApiErrorId.ERR_COHORT_NOT_FOUND.value, 404)


def test_resuming_below_the_viability_floor_is_refused():
    """PRD 3.4: "Withdrawing a `CONFIRMED` or `ATTENDING` seat carries a further
    consequence: if the cohort is `RUNNING` and the resulting `seats_filled` has
    dropped below `min_viable_enrollment`, the cohort itself moves
    `RUNNING → SUSPENDED`, which in turn releases the cohort's committed grant
    money as described in §3.9."
    PRD 3.4: "Resuming takes the cohort `SUSPENDED → RUNNING`, but only if it still
    meets its viability floor: `seats_filled` must have reached or exceeded
    `min_viable_enrollment`, and a resume attempt below that floor is refused with
    `ERR_MIN_VIABLE_NOT_MET`. Resumption increments `version`."

    Design: Corner/state_machines/cohort_resume_below_viability_floor_returns_min_viable_not_met
    """
    set_clock()
    space, cohort = create_open_cohort(name="Viability Group", seats_total=4,
                                       min_viable_enrollment=1)
    participant = create_assessed_participant(loss_type=cohort["loss_type"])
    enrollment = enroll(participant["id"], cohort["id"], cohort["version"])
    confirm_enrollment(enrollment["id"])
    validate_success(api_client.launch_cohort(cohort["id"], PD))
    withdraw_enrollment(enrollment["id"], "NO_SHOW")

    validate_error(api_client.resume_cohort(cohort["id"], PD),
                   ApiErrorId.ERR_MIN_VIABLE_NOT_MET.value, 409)

    refreshed = read_cohort(cohort["id"])
    assert refreshed["status"] == "SUSPENDED"
    assert refreshed["seats_filled"] == 0
    assert refreshed["seats_open"] == 4
    assert_cohort_seat_pool(refreshed)
    withdrawn = read_enrollment(enrollment["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdraw_reason"] == "NO_SHOW"


def test_cancelling_a_cohort_withdraws_live_seats_and_releases_its_money():
    """PRD 3.4: "Cancellation is available from `FORMING`, `OPEN_ENROLLMENT`,
    `UNDERSUBSCRIBED` or `SUSPENDED` — never from `RUNNING`, which must be
    suspended first. It moves the cohort to `CANCELLED`, withdraws every enrollment
    in `HELD`, `CONFIRMED` or `ATTENDING` with `withdraw_reason`
    `PROGRAM_CANCELLED` and returns each of those seats to `seats_open`, releases
    every `COMMITTED` funding allocation on the cohort, and increments `version`."
    PRD 3.9: "Release moves the allocation `COMMITTED → RELEASED`, leaves
    `settled_cents` null, decreases the award's `committed_cents` by the
    `provisional_cents`, recomputes `available_cents`, and increments the award's
    `version`."

    Design: Corner/state_machines/cohort_cancel_withdraws_live_enrollments_and_releases_allocation
    """
    set_clock()
    award = create_grant_award(awarded_cents=5_000_000,
                               allowed_categories=["GROUP_PROGRAM"])
    space, cohort, participant, enrollment = setup_cohort_with_confirmed_seat(
        cohort_overrides={"name": "Cancel Group", "direct_cost_cents": 240_000})
    allocation = create_funding_allocation(
        award["id"], "GROUP_PROGRAM", cohort_id=cohort["id"],
        expected_grant_award_version=award["version"])
    assert allocation["provisional_cents"] == 67_200

    validate_success(api_client.cancel_cohort(cohort["id"], PD))

    refreshed = read_cohort(cohort["id"])
    assert refreshed["status"] == "CANCELLED"
    assert refreshed["seats_open"] == 4
    assert refreshed["seats_filled"] == 0
    assert_cohort_seat_pool(refreshed)

    withdrawn = read_enrollment(enrollment["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdraw_reason"] == "PROGRAM_CANCELLED"

    released = read_funding_allocation(allocation["id"])
    assert released["status"] == "RELEASED"
    refreshed_award = read_grant_award(award["id"])
    assert refreshed_award["committed_cents"] == 0
    assert refreshed_award["available_cents"] == 5_000_000
    assert_grant_money_pool(refreshed_award)


def _setup_dual_variant_cohort():
    """Award + open cohort + one CONFIRMED seat and one HELD seat + a group
    allocation committed while both seats are live, then launch and log six
    sessions against the confirmed seat."""
    set_clock()
    space, cohort = create_open_cohort(
        space_overrides={"name": "Chapel Room", "capacity": 20,
                         "turnover_buffer_minutes": 30},
        name="Tuesday Illness Group", loss_type="ANTICIPATED_ILLNESS",
        seats_total=4, min_viable_enrollment=1, weekday="TUE",
        start_minute_utc=600, duration_minutes=90,
        series_start_date="2026-09-08", sessions_total=8,
        direct_cost_cents=240_000)
    award = create_grant_award(awarded_cents=5_000_000,
                               allowed_categories=["GROUP_PROGRAM"])

    participant_a = create_assessed_participant(loss_type="ANTICIPATED_ILLNESS")
    participant_b = create_assessed_participant(loss_type="ANTICIPATED_ILLNESS")
    enrollment_a = enroll(participant_a["id"], cohort["id"], cohort["version"])
    enrollment_b = enroll(participant_b["id"], cohort["id"])
    confirm_enrollment(enrollment_a["id"])

    allocation = create_funding_allocation(
        award["id"], "GROUP_PROGRAM", cohort_id=cohort["id"],
        expected_grant_award_version=award["version"])

    validate_success(api_client.launch_cohort(cohort["id"], PD))
    log_attendance(enrollment_a["id"], 6)
    return {
        "cohort": cohort, "award": award, "allocation": allocation,
        "participant_a": participant_a, "participant_b": participant_b,
        "enrollment_a": enrollment_a, "enrollment_b": enrollment_b,
    }


def test_group_allocation_commits_on_the_forward_looking_seat_projection():
    """PRD 3.9: "For a `GROUP_PROGRAM` allocation, the programme projects how many
    participants the cohort will actually carry: take the number of that cohort's
    seats currently held or filled, which is `seats_filled` plus `seats_held`, and
    cap it at `seats_total`. Multiply the cohort's `program_cost_total_cents` by
    that projected count, divide by `seats_total`, and round half up to a whole
    cent. The allocation's `basis` is recorded as `PROJECTED_ENROLLMENT`."
    PRD 3.3: "A direct cost of 240,000 cents therefore yields an admin fee of
    28,800 cents and a programme total of 268,800 cents; keying the tier off the
    total instead would drop the total into the second band and produce 26,880 and
    266,880, which is the wrong answer."

    Design: Difficulty/dual_variant_calc/funding_provisional_projected_vs_settled_actual_on_cohort_money
    """
    scenario = _setup_dual_variant_cohort()
    allocation = read_funding_allocation(scenario["allocation"]["id"])

    assert read_cohort(scenario["cohort"]["id"])["program_cost_total_cents"] == 268_800
    assert allocation["provisional_cents"] == 134_400, (
        f"Expected 134400 from a two-seat projection, got "
        f"{allocation['provisional_cents']}")
    assert allocation["basis"] == "PROJECTED_ENROLLMENT"
    assert allocation["settled_cents"] is None
    assert allocation["status"] == "COMMITTED"


def test_completing_the_cohort_settles_the_same_allocation_on_actual_attendance():
    """PRD 3.9: "For a `GROUP_PROGRAM` allocation, sum `sessions_attended` across
    only those of the cohort's enrollments that have reached status `COMPLETED` or
    `WITHDRAWN` — enrollments still in `HELD`, `CONFIRMED` or `ATTENDING`, and
    those that `EXPIRED`, contribute nothing. Multiply the cohort's
    `program_cost_total_cents` by that attended-session total, divide by the
    product of `seats_total` and `sessions_total`, and round half up to a whole
    cent; `basis` becomes `ACTUAL_ATTENDANCE`."
    PRD 3.9: "Settlement moves the allocation `COMMITTED → SETTLED`, writes
    `settled_cents` and stamps `settled_at` from the logical clock, decreases the
    award's `committed_cents` by the allocation's `provisional_cents`, increases
    the award's `spent_cents` by the newly computed `settled_cents`, recomputes
    `available_cents`, and increments the award's `version`."
    PRD 3.4: "A `RUNNING` cohort moves to `COMPLETED`, and in the same write: every
    enrollment in `CONFIRMED` or `ATTENDING` moves to `COMPLETED` with its
    `attendance_ratio` recomputed; each enrollment reaching `COMPLETED` adds its
    `sessions_attended` to that participant's `sessions_attended_total` and moves
    that participant's `service_status` `ACTIVE → MAINTENANCE`; every funding
    allocation on the cohort still in `COMMITTED` is settled on actual attendance
    as described in §3.9; and the cohort's `version` increases by one."

    Design: Difficulty/dual_variant_calc/funding_provisional_projected_vs_settled_actual_on_cohort_money
    """
    scenario = _setup_dual_variant_cohort()
    validate_success(api_client.complete_cohort(scenario["cohort"]["id"], PD))

    allocation = read_funding_allocation(scenario["allocation"]["id"])
    assert allocation["provisional_cents"] == 134_400
    assert allocation["settled_cents"] == 50_400, (
        f"Expected 50400 from six attended sessions, got {allocation['settled_cents']}")
    assert allocation["provisional_cents"] != allocation["settled_cents"]
    assert allocation["status"] == "SETTLED"
    assert allocation["basis"] == "ACTUAL_ATTENDANCE"

    assert read_cohort(scenario["cohort"]["id"])["status"] == "COMPLETED"
    enrollment_a = read_enrollment(scenario["enrollment_a"]["id"])
    assert enrollment_a["status"] == "COMPLETED"
    assert enrollment_a["attendance_ratio"] == pytest.approx(0.75, abs=0.00001)
    enrollment_b = read_enrollment(scenario["enrollment_b"]["id"])
    assert enrollment_b["status"] == "EXPIRED"
    assert enrollment_b["sessions_attended"] == 0

    award = read_grant_award(scenario["award"]["id"])
    assert award["committed_cents"] == 0
    assert award["spent_cents"] == 50_400
    assert award["available_cents"] == 4_949_600
    assert_grant_money_pool(award)

    participant_a = read_participant(scenario["participant_a"]["id"])
    assert participant_a["sessions_attended_total"] == 6
    assert participant_a["service_status"] == "MAINTENANCE"


def _setup_undersubscribed_cycle():
    """Open cohort with a viability floor of two carrying one CONFIRMED seat, plus
    a second assessed participant waiting to take the seat that closes the gap."""
    set_clock()
    space, cohort = create_open_cohort(
        space_overrides={"name": "Chapel Room", "capacity": 20,
                         "turnover_buffer_minutes": 30},
        name="Cycle Group", loss_type="ANTICIPATED_ILLNESS", seats_total=4,
        min_viable_enrollment=2, direct_cost_cents=240_000)
    participant_a = create_assessed_participant(loss_type="ANTICIPATED_ILLNESS")
    participant_b = create_assessed_participant(loss_type="ANTICIPATED_ILLNESS")
    enrollment_a = enroll(participant_a["id"], cohort["id"], cohort["version"])
    confirm_enrollment(enrollment_a["id"])
    return cohort, participant_b, enrollment_a


def test_launching_below_the_viability_floor_undersubscribes_without_touching_seats():
    """PRD 3.4: "When instead `seats_filled` is strictly below
    `min_viable_enrollment`, the cohort moves `OPEN_ENROLLMENT → UNDERSUBSCRIBED`
    and every enrollment is left exactly where it stands, untouched, so that a
    re-opened enrolment period can build on the seats already taken. Both branches
    increase the cohort's `version` by one."

    Design: Difficulty/non_linear_state_machine/cohort_open_enrollment_undersubscribed_reopen_running_cycle
    """
    cohort, participant_b, enrollment_a = _setup_undersubscribed_cycle()

    launched = validate_success(api_client.launch_cohort(cohort["id"], PD))
    assert launched["status"] == "UNDERSUBSCRIBED", (
        f"Expected UNDERSUBSCRIBED with one of two seats filled, got {launched['status']}")

    assert read_enrollment(enrollment_a["id"])["status"] == "CONFIRMED", (
        "the undersubscribed branch leaves every enrollment exactly where it stands")
    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_filled"] == 1
    assert refreshed["seats_held"] == 0
    assert refreshed["seats_open"] == 3
    assert_cohort_seat_pool(refreshed)


def test_reopening_an_undersubscribed_cohort_lets_the_second_launch_run_it():
    """PRD 3.4: "A `ProgramDirector` opens it with a transition into
    `OPEN_ENROLLMENT`, which is permitted from `FORMING` and, for a group that
    failed to fill the first time round, from `UNDERSUBSCRIBED` as well — the
    second path is what makes the cohort lifecycle a cycle rather than a line.
    Either way, the room must be `AVAILABLE`, and the cohort's `version` increases
    by one."
    PRD 3.4: "When the `ProgramDirector` launches an `OPEN_ENROLLMENT` cohort whose
    `seats_filled` has reached or exceeded `min_viable_enrollment`, the cohort
    moves `OPEN_ENROLLMENT → RUNNING`: every enrollment in `CONFIRMED` advances
    `CONFIRMED → ATTENDING` — no seat movement occurs here, since a confirmed seat
    and an attending seat both count toward `seats_filled` — and every enrollment
    still in `HELD` is expired, each returning one unit from `seats_held` to
    `seats_open`."

    Design: Difficulty/non_linear_state_machine/cohort_open_enrollment_undersubscribed_reopen_running_cycle
    """
    cohort, participant_b, enrollment_a = _setup_undersubscribed_cycle()

    first_launch = validate_success(api_client.launch_cohort(cohort["id"], PD))
    assert first_launch["status"] == "UNDERSUBSCRIBED"

    reopened = validate_success(api_client.open_cohort_enrollment(cohort["id"], PD))
    assert reopened["status"] == "OPEN_ENROLLMENT"

    enrollment_b = enroll(participant_b["id"], cohort["id"], reopened["version"])
    confirm_enrollment(enrollment_b["id"])

    second_launch = validate_success(api_client.launch_cohort(cohort["id"], PD))
    assert second_launch["status"] == "RUNNING", (
        f"Expected the second launch to reach RUNNING, got {second_launch['status']}")

    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_filled"] == 2
    assert refreshed["seats_held"] == 0
    assert refreshed["seats_open"] == 2
    assert_cohort_seat_pool(refreshed)
    assert read_enrollment(enrollment_a["id"])["status"] == "ATTENDING"
    assert read_enrollment(enrollment_b["id"])["status"] == "ATTENDING"


def _setup_withdrawal_cascade():
    """Award + running cohort carrying one ATTENDING seat + a committed group
    allocation sized on that single seat."""
    set_clock()
    award = create_grant_award(awarded_cents=5_000_000,
                               allowed_categories=["GROUP_PROGRAM"])
    space, cohort = create_open_cohort(
        space_overrides={"name": "Chapel Room", "capacity": 20,
                         "turnover_buffer_minutes": 30},
        name="Cascade Group", loss_type="ANTICIPATED_ILLNESS", seats_total=4,
        min_viable_enrollment=1, direct_cost_cents=240_000)
    participant = create_assessed_participant(loss_type="ANTICIPATED_ILLNESS")
    enrollment = enroll(participant["id"], cohort["id"], cohort["version"])
    confirm_enrollment(enrollment["id"])
    allocation = create_funding_allocation(
        award["id"], "GROUP_PROGRAM", cohort_id=cohort["id"],
        expected_grant_award_version=award["version"])
    validate_success(api_client.launch_cohort(cohort["id"], PD))
    return award, cohort, participant, enrollment, allocation


def test_participant_withdrawal_unwinds_the_seat_and_suspends_the_running_cohort():
    """PRD 3.8: "The participant's `service_status` becomes `WITHDRAWN` and their
    `outreach_status` becomes `CLOSED`. Every enrollment of theirs in `HELD`,
    `CONFIRMED` or `ATTENDING` moves to `WITHDRAWN` with `withdraw_reason`
    `PARTICIPANT_REQUEST`, returning each seat to its cohort's `seats_open` — and
    where that drops a `RUNNING` cohort below its `min_viable_enrollment`, that
    cohort moves to `SUSPENDED`, whose own `COMMITTED` allocations are then
    `RELEASED` and the award's money figures restored, which is the full four-step
    chain from a single withdrawal to a grant balance."

    Design: Difficulty/transitive_cascade/participant_withdraw_chain_seat_cohort_allocation_grant
    """
    award, cohort, participant, enrollment, allocation = _setup_withdrawal_cascade()
    assert allocation["provisional_cents"] == 67_200

    validate_success(api_client.withdraw_participant(participant["id"], IC))

    refreshed_participant = read_participant(participant["id"])
    assert refreshed_participant["service_status"] == "WITHDRAWN"
    assert refreshed_participant["outreach_status"] == "CLOSED"

    withdrawn = read_enrollment(enrollment["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdraw_reason"] == "PARTICIPANT_REQUEST"

    refreshed_cohort = read_cohort(cohort["id"])
    assert refreshed_cohort["status"] == "SUSPENDED"
    assert refreshed_cohort["seats_filled"] == 0
    assert refreshed_cohort["seats_held"] == 0
    assert refreshed_cohort["seats_open"] == 4
    assert_cohort_seat_pool(refreshed_cohort)


def test_participant_withdrawal_releases_the_money_and_cancels_the_outreach_plan():
    """PRD 3.9: "Release moves the allocation `COMMITTED → RELEASED`, leaves
    `settled_cents` null, decreases the award's `committed_cents` by the
    `provisional_cents`, recomputes `available_cents`, and increments the award's
    `version`."
    PRD 3.8: "And every anniversary touchpoint of theirs in `SCHEDULED`, `DUE` or
    `SENT` moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/participant_withdraw_chain_seat_cohort_allocation_grant
    """
    award, cohort, participant, enrollment, allocation = _setup_withdrawal_cascade()

    validate_success(api_client.withdraw_participant(participant["id"], IC))

    released = read_funding_allocation(allocation["id"])
    assert released["status"] == "RELEASED"
    assert released["settled_cents"] is None

    refreshed_award = read_grant_award(award["id"])
    assert refreshed_award["committed_cents"] == 0
    assert refreshed_award["spent_cents"] == 0
    assert refreshed_award["available_cents"] == 5_000_000
    assert_grant_money_pool(refreshed_award)

    plan = read_outreach_plan(participant["id"])
    assert len(plan) == 4, f"Expected the full four-touchpoint plan, got {len(plan)}"
    for row in plan:
        assert row["status"] == "CANCELLED"
