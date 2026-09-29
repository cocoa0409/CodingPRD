"""Declared transitions, refused transitions and the downward term cascade.

Each case exercises one edge of a declared state machine: the happy walk, an
action fired from a state outside its from-set, a terminal state that refuses
every further move, and the precondition gates that guard the three term acts.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEPT_ADMIN,
    GRANT_ACCOUNTANT,
    GS_ADMIN,
    SINGLE_PERIOD_AUTUMN_2026,
    allocations_of,
    api_client,
    assert_funding_conservation,
    build_assessment,
    build_funded_appointment,
    build_renewal_review,
    build_term_frame,
    close_term,
    disbursements_of,
    drive_appointment,
    fund_wholly_from,
    lock_term_payroll,
    make_appointment,
    make_funding_source,
    make_pay_periods,
    make_policy,
    make_student,
    make_term,
    open_term,
    pay,
    read_appointment,
    read_assessment,
    read_source,
    read_student,
    read_term,
    set_clock,
    suspend_source,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_term_walks_planning_open_payroll_locked_closed_in_order():
    """The three term acts advance the term and drag the pay period with them.

    PRD: "A term begins in `PLANNING`, becomes `OPEN` for appointment activity,
    then `PAYROLL_LOCKED` when the payroll calendar is frozen, and finally
    `CLOSED`, which is terminal." PRD: "Locking sets `locked_at` to the current
    logical-clock instant and moves every pay period of the term still `OPEN` to
    `LOCKED`, which is exactly what makes disbursement payment possible." PRD: "On
    success `closed_at` is stamped, every pay period of the term still `LOCKED`
    moves to `CLOSED`".

    Design: Corner/state_machines/term_advances_planning_open_payroll_locked_closed_in_order
    """
    frame = build_term_frame(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026, open_the_term=False
    )
    period_id = frame["pay_periods"][0]["id"]
    assert frame["term"]["status"] == "PLANNING"

    opened = open_term(frame["term_id"])
    assert opened["status"] == "OPEN"
    assert opened["pay_period_count"] == 1

    locked = lock_term_payroll(frame["term_id"])
    assert locked["status"] == "PAYROLL_LOCKED"
    assert locked["locked_at"] is not None

    locked_periods, locked_meta = validate_paginated(
        api_client.list_term_pay_periods(
            frame["term_id"], GS_ADMIN,
            {"status": "LOCKED", "limit": 10, "offset": 0},
        )
    )
    assert locked_meta["total_count"] == 1
    assert locked_periods[0]["id"] == period_id
    assert locked_periods[0]["status"] == "LOCKED"

    closed = close_term(frame["term_id"])
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None

    closed_periods, closed_meta = validate_paginated(
        api_client.list_term_pay_periods(
            frame["term_id"], GS_ADMIN,
            {"status": "CLOSED", "limit": 10, "offset": 0},
        )
    )
    assert closed_meta["total_count"] == 1
    assert closed_periods[0]["id"] == period_id


def test_a_new_appointment_sits_on_both_axes_initial_states_at_once():
    """DRAFT and NOT_SCHEDULED are the two independent starting positions.

    PRD: "A newly drafted appointment sits at `lifecycle_status` of `DRAFT` and
    `payroll_status` of `NOT_SCHEDULED`, has `renewal_eligible` true, has
    `submitted_by_user_id`, `approved_by_user_id`, `return_reason`,
    `pay_suspension_reason`, `termination_reason` and `termination_date` all
    null". PRD: "The **counted lifecycle states** are `SUBMITTED`,
    `FUNDING_VERIFIED`, `APPROVED`, `ACTIVE` and `NON_RENEWAL_PENDING`;
    appointments in `DRAFT`, `RETURNED`, `COMPLETED`, `TERMINATED` and
    `CANCELLED` are excluded from every effort figure."

    Design: Corner/state_machines/appointment_initial_states_are_draft_and_not_scheduled
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    student = make_student(student_number="GS-1006")

    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"]
    )

    assert appointment["lifecycle_status"] == "DRAFT"
    assert appointment["payroll_status"] == "NOT_SCHEDULED"
    assert appointment["submitted_by_user_id"] is None
    assert appointment["approved_by_user_id"] is None
    assert appointment["return_reason"] is None
    assert appointment["pay_suspension_reason"] is None
    assert appointment["termination_reason"] is None
    assert appointment["termination_date"] is None
    assert appointment["renewal_eligible"] is True

    assert read_student(student["id"])["total_effort_pct"] == 0, (
        "a DRAFT appointment is not a counted appointment"
    )


def test_opening_a_term_a_second_time_is_refused():
    """Opening is a transition out of PLANNING, not an idempotent assertion.

    PRD: "Opening a term is the act of declaring the frame complete, and it moves
    the term `PLANNING → OPEN`. It requires the term to be in `PLANNING`". PRD:
    "Where an operation needs the term to be in a state other than `OPEN` —
    terminating an appointment, for example, which is permitted while the term is
    either `OPEN` or `PAYROLL_LOCKED` — a state mismatch surfaces as
    `ERR_INVALID_TERM_STATE` (HTTP 409)."

    Design: Corner/state_machines/opening_an_already_open_term_rejected
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    assert frame["term"]["status"] == "OPEN"

    response = api_client.open_academic_term(frame["term_id"], GS_ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_TERM_STATE.value, 409)

    term = read_term(frame["term_id"])
    assert term["status"] == "OPEN"
    assert term["pay_period_count"] == 1


def test_activating_a_draft_appointment_is_refused():
    """Activation is declared only out of APPROVED, so DRAFT cannot jump to ACTIVE.

    PRD: "Activation, also a `GradSchoolAdmin` act, then advances `APPROVED →
    ACTIVE` against an `OPEN` term and changes nothing else." PRD:
    "**Addressed-resource state** — the addressed row is in a state that permits
    the requested transition, else the state error for that collection:
    `ERR_INVALID_TERM_STATE`, `ERR_INVALID_APPOINTMENT_STATE`,
    `ERR_INVALID_ALLOCATION_STATE`, `ERR_INVALID_DISBURSEMENT_STATE`,
    `ERR_INVALID_RENEWAL_STATE`, or `ERR_INVALID_ASSESSMENT_STATE`, each HTTP
    409."

    Design: Corner/state_machines/activating_a_draft_appointment_rejected
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    student = make_student(student_number="GS-1007")
    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"]
    )

    response = api_client.activate_appointment(appointment["id"], GS_ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409)

    stored = read_appointment(appointment["id"])
    assert stored["lifecycle_status"] == "DRAFT"
    assert stored["payroll_status"] == "NOT_SCHEDULED"


def test_a_terminated_appointment_refuses_both_activation_and_resumed_pay():
    """The two terminal states are locked down independently of each other.

    PRD: "The first step sets `lifecycle_status` to the terminal `TERMINATED`,
    stores `termination_reason`, sets `termination_date` to the current
    logical-clock date, and sets `payroll_status` to the terminal `PAY_VOIDED`".
    PRD: "**Addressed-resource state** — the addressed row is in a state that
    permits the requested transition, else the state error for that collection:
    `ERR_INVALID_TERM_STATE`, `ERR_INVALID_APPOINTMENT_STATE`,
    `ERR_INVALID_ALLOCATION_STATE`, `ERR_INVALID_DISBURSEMENT_STATE`,
    `ERR_INVALID_RENEWAL_STATE`, or `ERR_INVALID_ASSESSMENT_STATE`, each HTTP
    409."

    Design: Corner/state_machines/terminated_appointment_cannot_be_reactivated_or_resumed
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1008"},
        advance_to="ACTIVE",
    )
    validate_success(api_client.terminate_appointment(
        world["appointment_id"], {"termination_reason": "STUDENT_WITHDRAWAL"},
        GS_ADMIN,
    ))

    validate_error(
        api_client.activate_appointment(world["appointment_id"], GS_ADMIN),
        ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409,
    )
    validate_error(
        api_client.resume_pay(world["appointment_id"], GS_ADMIN),
        ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409,
    )

    stored = read_appointment(world["appointment_id"])
    assert stored["lifecycle_status"] == "TERMINATED"
    assert stored["payroll_status"] == "PAY_VOIDED"
    assert stored["termination_reason"] == "STUDENT_WITHDRAWAL"


def test_a_term_with_no_stipend_policy_cannot_be_opened_until_one_exists():
    """The calendar alone is not the frame; the policy table must be non-empty too.

    PRD: "It requires the term to be in `PLANNING`, and it requires the calendar
    and the policy table each to be non-empty: at least one pay period and at
    least one stipend policy must reference the term, or the request is rejected
    with `ERR_TERM_CALENDAR_INCOMPLETE`." PRD: "declaring a stipend policy is
    accepted while the term is either `PLANNING` or `OPEN`".

    Design: Corner/state_machines/opening_a_term_without_a_stipend_policy_rejected
    """
    term = make_term()
    make_pay_periods(term["id"], SINGLE_PERIOD_AUTUMN_2026)

    validate_error(
        api_client.open_academic_term(term["id"], GS_ADMIN),
        ApiErrorId.ERR_TERM_CALENDAR_INCOMPLETE.value, 422,
    )
    assert read_term(term["id"])["status"] == "PLANNING"

    make_policy(term["id"])

    opened = open_term(term["id"])
    assert opened["status"] == "OPEN"
    assert opened["pay_period_count"] == 1


def test_payroll_cannot_lock_while_an_appointment_is_still_funding_verified():
    """An unresolved verification blocks the lock and leaves the calendar open.

    PRD: "Locking payroll advances the term `OPEN → PAYROLL_LOCKED`; it requires
    the term to be `OPEN` and requires that no appointment of the term is still in
    `FUNDING_VERIFIED`, else `ERR_UNRESOLVED_APPOINTMENTS`."

    Design: Corner/state_machines/locking_payroll_with_a_funding_verified_appointment_rejected
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1009"},
        advance_to="FUNDING_VERIFIED",
    )

    response = api_client.lock_payroll(world["term_id"], GS_ADMIN)

    validate_error(response, ApiErrorId.ERR_UNRESOLVED_APPOINTMENTS.value, 409)

    term = read_term(world["term_id"])
    assert term["status"] == "OPEN"
    assert term["locked_at"] is None

    periods, _ = validate_paginated(api_client.list_term_pay_periods(
        world["term_id"], GS_ADMIN, {"limit": 10, "offset": 0}
    ))
    assert periods[0]["status"] == "OPEN"
    assert read_appointment(world["appointment_id"])["lifecycle_status"] == (
        "FUNDING_VERIFIED"
    )


def test_a_scheduled_disbursement_blocks_the_close_until_it_is_paid():
    """Close demands every disbursement be settled, and paying settles it.

    PRD: "It requires the term to be `PAYROLL_LOCKED`, requires every
    disbursement belonging to one of the term's pay periods to be in `PAID`,
    `VOIDED` or `REVERSED`, and requires every tax assessment of the term to be in
    `FINAL` or `SUPERSEDED`; a still-`SCHEDULED` disbursement or a non-final
    assessment is `ERR_UNSETTLED_DISBURSEMENTS`." PRD: "`payroll_status` becomes
    `PARTIALLY_DISBURSED` when at least one sibling disbursement of the same
    appointment remains `SCHEDULED` after this payment, and `FULLY_DISBURSED` when
    none does."

    Design: Corner/state_machines/closing_a_term_with_a_scheduled_disbursement_rejected
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1010"},
        advance_to="PAYROLL_SCHEDULED",
        lock_payroll_after=True,
    )
    scheduled = disbursements_of(world["appointment_id"], status="SCHEDULED")
    assert len(scheduled) == 1
    assert scheduled[0]["gross_amount_cents"] == 300000

    validate_error(
        api_client.close_academic_term(world["term_id"], GS_ADMIN),
        ApiErrorId.ERR_UNSETTLED_DISBURSEMENTS.value, 409,
    )
    assert read_term(world["term_id"])["status"] == "PAYROLL_LOCKED"

    paid = pay(scheduled[0]["id"])
    assert paid["status"] == "PAID"
    assert read_appointment(world["appointment_id"])["payroll_status"] == (
        "FULLY_DISBURSED"
    )

    closed = close_term(world["term_id"])
    assert closed["status"] == "CLOSED"


def test_closing_the_term_completes_the_appointment_and_expends_its_allocation():
    """The close cascade reaches three collections without being asked to.

    PRD: "every appointment of the term whose `lifecycle_status` is `ACTIVE` or
    `NON_RENEWAL_PENDING` and whose `end_date` falls on or before the term's
    `term_end` moves to the terminal `COMPLETED`". PRD: "Caused by each
    appointment entering `COMPLETED`, its allocations in `COMMITTED` move to the
    terminal `EXPENDED` and each such allocation's `disbursed_amount_cents` is
    raised to its `allocated_stipend_cents` plus its `allocated_remission_cents`."
    PRD: "the committed total falling and the expended total rising by the same
    amount, with available untouched, as §2.7 requires of this branch."

    Design: Corner/state_machines/term_close_completes_appointment_and_expends_its_commitment
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1011"},
        advance_to="ACTIVE",
        lock_payroll_after=True,
    )
    before = read_source(world["source_id"])
    assert before["committed_amount_cents"] == 300000
    assert before["available_amount_cents"] == 4700000

    closed = close_term(world["term_id"])
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None

    periods, _ = validate_paginated(api_client.list_term_pay_periods(
        world["term_id"], GS_ADMIN, {"limit": 10, "offset": 0}
    ))
    assert periods[0]["status"] == "CLOSED"

    appointment = read_appointment(world["appointment_id"])
    assert appointment["lifecycle_status"] == "COMPLETED"
    assert appointment["payroll_status"] == "NOT_SCHEDULED", (
        "the payroll axis is untouched by the close cascade"
    )

    allocations = allocations_of(world["appointment_id"])
    assert len(allocations) == 1
    assert allocations[0]["status"] == "EXPENDED"
    assert allocations[0]["allocated_stipend_cents"] == 300000
    assert allocations[0]["disbursed_amount_cents"] == 300000

    after = read_source(world["source_id"])
    assert after["committed_amount_cents"] == 0
    assert after["expended_amount_cents"] == 300000
    assert after["available_amount_cents"] == 4700000
    assert_funding_conservation(after)


def test_returning_then_resubmitting_walks_the_review_loop_back_to_submitted():
    """The effort aggregate drops while RETURNED and comes back on resubmission.

    PRD: "The payload carries `return_reason`, which is stored." PRD: "The
    student's `total_effort_pct` is recomputed and the student's `version`
    incremented, since a `RETURNED` appointment is no longer a counted
    appointment. A returned appointment re-enters `SUBMITTED` through the same
    submission path, so the review loop can run any number of times."

    Design: Corner/state_machines/return_then_resubmit_cycle_restores_submitted
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1012"},
        advance_to="SUBMITTED",
    )

    returned = validate_success(api_client.return_appointment(
        world["appointment_id"],
        {"return_reason": "SUPERVISOR_SIGNATURE_MISSING"},
        GS_ADMIN,
    ))
    assert returned["lifecycle_status"] == "RETURNED"
    assert returned["return_reason"] == "SUPERVISOR_SIGNATURE_MISSING"

    while_returned = read_student(world["student_id"])
    assert while_returned["total_effort_pct"] == 0
    assert float(while_returned["assigned_hours_per_week"]) == 0.0

    resubmitted = validate_success(
        api_client.submit_appointment(world["appointment_id"], DEPT_ADMIN)
    )
    assert resubmitted["lifecycle_status"] == "SUBMITTED"
    assert resubmitted["return_reason"] is None
    assert resubmitted["total_stipend_cents"] == 300000
    assert resubmitted["projected_pay_period_count"] == 1

    after = read_student(world["student_id"])
    assert after["total_effort_pct"] == 75
    assert float(after["assigned_hours_per_week"]) == pytest.approx(30.0, abs=0.01)


def test_reinstating_a_sponsor_hold_returns_the_source_to_active():
    """A sponsor hold needs the explicit call, and the balances never move.

    PRD: "Suspension moves the source `ACTIVE → SUSPENDED` and blocks new
    commitments; it deliberately leaves existing `COMMITTED` allocations
    untouched, because a sponsor hold is not a clawback. Reinstatement moves a
    `SUSPENDED` source back to `ACTIVE` and clears `suspension_reason` to null."

    Design: Corner/state_machines/manual_reinstate_clears_sponsor_hold_suspension
    """
    frame = build_term_frame(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026, open_the_term=False
    )
    source = make_funding_source(frame["department_id"])
    assert source["status"] == "ACTIVE"

    suspended = suspend_source(source["id"], "SPONSOR_HOLD")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "SPONSOR_HOLD"
    assert suspended["available_amount_cents"] == 5000000
    assert suspended["committed_amount_cents"] == 0
    assert suspended["expended_amount_cents"] == 0

    reinstated = validate_success(
        api_client.reinstate_funding_source(source["id"], GRANT_ACCOUNTANT)
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None
    assert reinstated["available_amount_cents"] == 5000000
    assert reinstated["committed_amount_cents"] == 0
    assert reinstated["expended_amount_cents"] == 0
    assert_funding_conservation(reinstated)


def test_a_second_provisional_assessment_supersedes_the_first_one():
    """The earlier provisional row is driven to a terminal state by the new one.

    PRD: "The assessment copies the term's `tax_calendar_year` at creation, is
    born `PROVISIONAL` with `variant_applied` of `TERM_PROVISIONAL` and
    `amendment_reason` null, and increments the student's `version` by one. Any
    earlier assessment for the same pair that is still `PROVISIONAL` moves to the
    terminal `SUPERSEDED`." PRD: "Under **`TERM_PROVISIONAL`**, the cap is applied
    to the term in isolation: `exempt_cents` is the smaller of `benefit_cents` and
    the cap, and `taxable_cents` is `benefit_cents` minus `exempt_cents`."

    Design: Corner/state_machines/second_provisional_assessment_supersedes_the_first
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1013", "enrolled_credit_hours": 9},
        advance_to="ACTIVE",
    )
    first = build_assessment(world["student_id"], world["term_id"])
    assert first["status"] == "PROVISIONAL"

    second = build_assessment(world["student_id"], world["term_id"])

    assert read_assessment(first["id"])["status"] == "SUPERSEDED"
    assert second["status"] == "PROVISIONAL"
    assert second["variant_applied"] == "TERM_PROVISIONAL"
    assert second["tax_calendar_year"] == 2026
    assert second["benefit_cents"] == 450000, (
        "9 remitted credits at 50000 cents each, at the 100 percent band"
    )
    assert second["exempt_cents"] == 450000
    assert second["taxable_cents"] == 0
    assert second["imputed_withholding_cents"] == 0


def test_releasing_the_only_allocation_reverts_a_verified_appointment():
    """A direct release drags the appointment back to RETURNED and frees the budget.

    PRD: "One further cascade fires: if the funded appointment's
    `lifecycle_status` was `FUNDING_VERIFIED`, it reverts to `RETURNED` with
    `return_reason` set to `FUNDING_RELEASED`, because an appointment cannot
    remain funding-verified once its funding has gone." PRD: "On success both
    allocated amounts are zeroed, the source's `committed_amount_cents` and
    `available_amount_cents` are recomputed".

    Design: Corner/state_machines/allocation_release_reverts_funding_verified_appointment_to_returned
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1014"},
        advance_to="FUNDING_VERIFIED",
    )
    committed = allocations_of(world["appointment_id"], status="COMMITTED")
    assert len(committed) == 1

    released = validate_success(api_client.release_funding_allocation(
        committed[0]["id"], {"release_reason": "SPONSOR_REBUDGET"},
        GRANT_ACCOUNTANT,
    ))

    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "SPONSOR_REBUDGET"
    assert released["allocated_stipend_cents"] == 0
    assert released["allocated_remission_cents"] == 0

    appointment = read_appointment(world["appointment_id"])
    assert appointment["lifecycle_status"] == "RETURNED"
    assert appointment["return_reason"] == "FUNDING_RELEASED"

    source = read_source(world["source_id"])
    assert source["committed_amount_cents"] == 0
    assert source["available_amount_cents"] == 5000000
    assert_funding_conservation(source)


def test_four_actions_fired_from_the_wrong_state_each_report_their_own_error():
    """Allocation, disbursement, review and assessment all guard their own from-set.

    PRD: "Release requires the allocation to be in `COMMITTED` — otherwise
    `ERR_INVALID_ALLOCATION_STATE`". PRD: "The disbursement must be `SCHEDULED`
    (`ERR_INVALID_DISBURSEMENT_STATE`)". PRD: "Reversal requires the disbursement
    to be `PAID` and requires the term not to be `CLOSED`, else
    `ERR_INVALID_TERM_STATE`." PRD: "The review must be in `SAP_CERTIFIED`". PRD:
    "It requires the assessment to be `FINAL`, and it requires the recomputation
    under `CALENDAR_YEAR_FINAL` to yield a `benefit_cents` different from the
    stored value".

    Design: Corner/state_machines/invalid_from_state_actions_across_four_entities_rejected
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    set_clock("2026-09-05T00:00:00Z")
    source = make_funding_source(frame["department_id"])
    benefiting_student = make_student(
        student_number="GS-1015", enrolled_credit_hours=9
    )
    other_student = make_student(
        student_number="GS-1016", full_name="Ben Ortiz", cumulative_gpa=3.50
    )

    drafted = make_appointment(
        other_student["id"], frame["department_id"], frame["term_id"]
    )
    fund_wholly_from(drafted["id"], source["id"])
    drive_appointment(drafted["id"], "SUBMITTED")
    proposed = allocations_of(drafted["id"], status="PROPOSED")
    assert len(proposed) == 1

    running = make_appointment(
        benefiting_student["id"], frame["department_id"], frame["term_id"]
    )
    fund_wholly_from(running["id"], source["id"])
    drive_appointment(running["id"], "PAYROLL_SCHEDULED")
    scheduled = disbursements_of(running["id"], status="SCHEDULED")
    assert len(scheduled) == 1

    review = build_renewal_review(running["id"])
    assert review["status"] == "DRAFT"
    assessment = build_assessment(benefiting_student["id"], frame["term_id"])
    assert assessment["status"] == "PROVISIONAL"

    validate_error(
        api_client.release_funding_allocation(
            proposed[0]["id"], {"release_reason": "SPONSOR_REBUDGET"},
            GRANT_ACCOUNTANT,
        ),
        ApiErrorId.ERR_INVALID_ALLOCATION_STATE.value, 409,
    )
    validate_error(
        api_client.reverse_stipend_disbursement(
            scheduled[0]["id"], {"reversal_reason": "BANK_RETURN"}, GS_ADMIN
        ),
        ApiErrorId.ERR_INVALID_DISBURSEMENT_STATE.value, 409,
    )
    validate_error(
        api_client.issue_notice(review["id"], {"decision": "RENEW"}, DEPT_ADMIN),
        ApiErrorId.ERR_INVALID_RENEWAL_STATE.value, 409,
    )
    validate_error(
        api_client.amend_tax_assessment(
            assessment["id"], {"amendment_reason": "REMISSION_CORRECTION"},
            GS_ADMIN,
        ),
        ApiErrorId.ERR_INVALID_ASSESSMENT_STATE.value, 409,
    )

    assert allocations_of(drafted["id"])[0]["status"] == "PROPOSED"
    assert disbursements_of(running["id"])[0]["status"] == "SCHEDULED"
    assert validate_success(
        api_client.get_renewal_decision(review["id"], DEPT_ADMIN)
    )["status"] == "DRAFT"
    assert read_assessment(assessment["id"])["status"] == "PROVISIONAL"
