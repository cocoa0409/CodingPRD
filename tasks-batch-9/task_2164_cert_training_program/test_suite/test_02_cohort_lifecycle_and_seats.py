"""Cohort lifecycle, the seat ledger, the waitlist and enrollment gates."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_trainee,
    advance_cohort,
    assert_cohort,
    create_cohort_payload,
    create_program,
    create_session,
    read_cohort,
    read_program,
    read_trainee,
    schedule_core_sessions,
    set_clock,
    setup_graduated_trainees,
    setup_program_and_curriculum,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_new_cohort_opens_in_recruiting_with_a_zero_seat_ledger(api):
    """PRD §3.2: "A new cohort opens in `RECRUITING`, with `seats_confirmed`,
    `seats_waitlisted`, and `delivered_contact_hours` at 0, `next_waitlist_position` at 1,
    and `graduation_reviewer_user_id` null."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly 1 on each mutation of that row, including mutations caused
    indirectly by a cascade originating on another resource."

    Design: Corner/state_machines/new_cohort_starts_in_recruiting_with_a_zero_seat_ledger
    """
    program = create_program()
    cohort = validate_success(
        api.create_cohort(
            create_cohort_payload(
                program["id"], cohort_code="C-2027A", seat_capacity=12,
                session_window_start="2027-01-01T00:00:00Z",
                session_window_end="2027-06-30T23:00:00Z",
            ),
            COORD,
        ),
        201,
    )
    assert_cohort(cohort)
    assert cohort["status"] == "RECRUITING"
    assert cohort["seats_confirmed"] == 0
    assert cohort["seats_waitlisted"] == 0
    assert cohort["delivered_contact_hours"] == 0
    assert cohort["next_waitlist_position"] == 1
    assert cohort["version"] == 1


def test_cohort_cannot_open_teaching_before_its_window_starts(api):
    """PRD §3.2: "Moving `SCHEDULED → IN_SESSION` requires the logical clock to have
    reached `session_window_start` — that is, the clock must be at or after that instant."
    PRD §3.2: "A request naming a `to_status` that is not reachable from the cohort's
    present state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cohort_advance_to_in_session_before_window_start_is_rejected
    """
    ctx = setup_program_and_curriculum(
        cohort_code="C-2026B",
        window_start="2026-09-01T00:00:00Z",
        window_end="2027-01-31T23:00:00Z",
    )
    cohort_id = ctx["cohort"]["id"]
    facility_id = ctx["facility"]["id"]
    instructor_id = ctx["instructor1"]["id"]
    create_session(cohort_id, ctx["m101"]["id"], facility_id, instructor_id,
                   "2026-09-02T09:00:00Z")
    create_session(cohort_id, ctx["m102"]["id"], facility_id, instructor_id,
                   "2026-09-03T09:00:00Z")
    create_session(cohort_id, ctx["m103"]["id"], facility_id, instructor_id,
                   "2026-09-04T09:00:00Z")
    advance_cohort(ctx, "SCHEDULED")

    validate_error(
        api.advance_cohort(cohort_id, {"to_status": "IN_SESSION"}, COORD),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_cohort(ctx)["status"] == "SCHEDULED"

    set_clock("2026-09-01T00:00:00Z")
    advanced = validate_success(
        api.advance_cohort(cohort_id, {"to_status": "IN_SESSION"}, COORD)
    )
    assert advanced["status"] == "IN_SESSION"


def test_a_closed_cohort_refuses_every_further_advance(api):
    """PRD §3.2: "The cohort lifecycle runs `RECRUITING → SCHEDULED → IN_SESSION →
    GRADUATION_REVIEW → CLOSED`, with `CANCELLED` reachable from either of the first two
    states, and with `CLOSED` and `CANCELLED` as the two terminal states."
    PRD §3.2: "A request naming a `to_status` that is not reachable from the cohort's
    present state is rejected with `ERR_INVALID_STATE`."
    PRD §3.1: "and `pending_graduation_count`, the number of the program's cohorts
    currently sitting in graduation review."

    Design: Corner/state_machines/closed_cohort_rejects_any_further_advance
    """
    ctx = setup_graduated_trainees()
    advance_cohort(ctx, "CLOSED")
    assert read_cohort(ctx)["status"] == "CLOSED"

    validate_error(
        api.advance_cohort(ctx["cohort"]["id"], {"to_status": "CANCELLED"}, COORD),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api.advance_cohort(ctx["cohort"]["id"], {"to_status": "IN_SESSION"}, COORD),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert read_cohort(ctx)["status"] == "CLOSED"
    assert read_program(ctx)["pending_graduation_count"] == 0


def test_cancelling_a_cohort_cancels_its_sessions_and_withdraws_its_people(api):
    """PRD §3.2: "Cancelling a cohort from `RECRUITING` or from `SCHEDULED` transitions
    every one of its class sessions still in `SCHEDULED` to `CANCELLED` and every one of
    its trainees whose enrollment standing is `APPLIED`, `WAITLISTED`, or `ENROLLED` to
    `WITHDRAWN`."

    Design: Corner/state_machines/cancel_cohort_cascades_down_to_sessions_and_trainees
    """
    ctx = setup_program_and_curriculum()
    schedule_core_sessions(ctx)
    add_trainee(ctx, key="tara", full_name="Tara Nolan")
    add_trainee(ctx, key="dev", full_name="Dev Okafor", enroll=False)

    cancelled = validate_success(
        api.advance_cohort(ctx["cohort"]["id"], {"to_status": "CANCELLED"}, COORD)
    )
    assert cancelled["status"] == "CANCELLED"

    for key in ("session_a", "session_b", "session_c"):
        session = validate_success(api.get_class_session(ctx[key]["id"], AUDITOR))
        assert session["status"] == "CANCELLED", f"{key} must be cancelled with the cohort"

    assert read_trainee(ctx, "tara")["enrollment_status"] == "WITHDRAWN"
    assert read_trainee(ctx, "dev")["enrollment_status"] == "WITHDRAWN"

    cohort = read_cohort(ctx)
    assert cohort["seats_confirmed"] == 0
    assert cohort["seats_waitlisted"] == 0
    assert read_program(ctx)["active_member_count"] == 0


def test_releasing_a_confirmed_seat_promotes_the_first_waitlisted_volunteer(api):
    """PRD §3.2: "when `seats_confirmed` has reached or exceeded `seat_capacity` the
    applicant advances `APPLIED → WAITLISTED` instead, their `waitlist_position` is stamped
    from the cohort's `next_waitlist_position`, that counter is then increased by 1, and
    `seats_waitlisted` rises by 1."
    PRD §3.2: "Its candidate set is every trainee of that same cohort whose enrollment
    standing is `WAITLISTED`; they are ranked by `waitlist_position` ascending, ties broken
    by `created_at` ascending."
    PRD §3.2: "Exactly one trainee is promoted per released seat, taking the `WAITLISTED →
    ENROLLED` edge, which lowers `seats_waitlisted` by 1, raises `seats_confirmed` by 1,
    and raises the program's `active_member_count` by 1."
    PRD §3.2: "The waitlist counter is monotone and is never decremented, so positions
    remain unique and comparable for the life of the cohort; a promoted trainee keeps the
    `waitlist_position` they were given, for audit."

    Design: Corner/state_machines/waitlisted_trainee_is_promoted_when_a_seat_is_released
    """
    ctx = setup_program_and_curriculum(seat_capacity=1)
    add_trainee(ctx, key="tara", full_name="Tara Nolan")
    add_trainee(ctx, key="dev", full_name="Dev Okafor")

    dev = read_trainee(ctx, "dev")
    assert dev["enrollment_status"] == "WAITLISTED"
    assert dev["waitlist_position"] == 1
    cohort = read_cohort(ctx)
    assert cohort["seats_confirmed"] == 1
    assert cohort["seats_waitlisted"] == 1

    validate_success(
        api.trainee_enrollment(ctx["trainees"]["tara"]["id"], {"action": "WITHDRAW"}, COORD)
    )

    assert read_trainee(ctx, "tara")["enrollment_status"] == "WITHDRAWN"
    promoted = read_trainee(ctx, "dev")
    assert promoted["enrollment_status"] == "ENROLLED"
    assert promoted["waitlist_position"] == 1, "the audit position survives promotion"

    cohort = read_cohort(ctx)
    assert cohort["seats_confirmed"] == 1
    assert cohort["seats_waitlisted"] == 0
    assert cohort["next_waitlist_position"] == 2, "the monotone counter is never lowered"
    assert read_program(ctx)["active_member_count"] == 1


def test_enrolling_into_a_cohort_under_graduation_review_is_refused(api):
    """PRD §3.2: "Enrolling requires the cohort to be `RECRUITING`, `SCHEDULED`, or
    `IN_SESSION`, and otherwise fails with `ERR_COHORT_NOT_ACCEPTING`."

    Design: Corner/validations/enrolling_into_a_cohort_in_graduation_review_is_refused
    """
    ctx = setup_graduated_trainees(applicants=(("dev", "Dev Okafor"),))
    assert read_cohort(ctx)["status"] == "GRADUATION_REVIEW"

    validate_error(
        api.trainee_enrollment(
            ctx["trainees"]["dev"]["id"], {"action": "ENROLL"}, COORD
        ),
        ApiErrorId.ERR_COHORT_NOT_ACCEPTING.value,
    )

    dev = read_trainee(ctx, "dev")
    assert dev["enrollment_status"] == "APPLIED"
    assert dev["waitlist_position"] is None
    cohort = read_cohort(ctx)
    assert cohort["seats_confirmed"] == 1
    assert cohort["seats_waitlisted"] == 0
    assert read_program(ctx)["active_member_count"] == 1


def test_enrolling_raises_the_seat_ledger_and_the_program_member_count(api):
    """PRD §3.2: "From `APPLIED`, the outcome depends on the seat ledger: when
    `seats_confirmed` is strictly below `seat_capacity` the applicant advances `APPLIED →
    ENROLLED`, `seats_confirmed` rises by 1, and the program's `active_member_count` rises
    by 1; when `seats_confirmed` has reached or exceeded `seat_capacity` the applicant
    advances `APPLIED → WAITLISTED` instead, their `waitlist_position` is stamped from the
    cohort's `next_waitlist_position`, that counter is then increased by 1, and
    `seats_waitlisted` rises by 1."

    Design: Difficulty/compensating_invariant/enroll_then_withdraw_conserves_the_cohort_seat_ledger
    """
    ctx = setup_program_and_curriculum(seat_capacity=2)
    trainee = add_trainee(ctx, key="tara", full_name="Tara Nolan", enroll=False)

    cohort_before = read_cohort(ctx)
    assert cohort_before["seats_confirmed"] == 0
    assert read_program(ctx)["active_member_count"] == 0

    enrolled = validate_success(
        api.trainee_enrollment(trainee["id"], {"action": "ENROLL"}, COORD)
    )
    assert enrolled["enrollment_status"] == "ENROLLED"
    assert read_cohort(ctx)["seats_confirmed"] == 1
    assert read_program(ctx)["active_member_count"] == 1


def test_withdrawing_repays_the_seat_ledger_without_drift(api):
    """PRD §3.2: "A trainee may be withdrawn from `APPLIED` with no ledger effect at all,
    from `WAITLISTED` with `seats_waitlisted` reduced by 1, or from `ENROLLED` or
    `GRADUATED`, in which case `seats_confirmed` falls by 1 and the program's
    `active_member_count` falls by 1."
    PRD §2.9: "Each is defined as an aggregate over primary rows, and every operation that
    changes those rows must leave the counter equal to that aggregate — which is what makes
    an increment on one path and a decrement on the reverse path mandatory rather than
    cosmetic."
    PRD §3.2: "The waitlist counter is monotone and is never decremented, so positions
    remain unique and comparable for the life of the cohort; a promoted trainee keeps the
    `waitlist_position` they were given, for audit."

    Design: Difficulty/compensating_invariant/enroll_then_withdraw_conserves_the_cohort_seat_ledger
    """
    ctx = setup_program_and_curriculum(seat_capacity=2)
    trainee = add_trainee(ctx, key="tara", full_name="Tara Nolan")
    assert read_cohort(ctx)["seats_confirmed"] == 1

    withdrawn = validate_success(
        api.trainee_enrollment(trainee["id"], {"action": "WITHDRAW"}, COORD)
    )
    assert withdrawn["enrollment_status"] == "WITHDRAWN"
    assert withdrawn["waitlist_position"] is None

    cohort = read_cohort(ctx)
    assert cohort["seats_confirmed"] == 0, "the released seat must return to the ledger"
    assert cohort["seats_waitlisted"] == 0
    assert cohort["next_waitlist_position"] == 1, (
        "nobody was ever waitlisted, so the monotone counter never moved"
    )
    assert read_program(ctx)["active_member_count"] == 0
