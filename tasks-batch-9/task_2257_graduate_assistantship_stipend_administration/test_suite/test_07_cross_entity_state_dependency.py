"""Operations whose legality depends on the state of a row the client never names.

Scheduling payroll reads the governing term's status; verifying funding reads the
status of every source the plan touches.  In both scenarios the addressed
appointment is in a perfectly legal state and the rejection comes from elsewhere.
"""
from test_helpers import (
    ApiErrorId,
    GRANT_ACCOUNTANT,
    GS_ADMIN,
    MONTHLY_PERIODS_AUTUMN_2026,
    api_client,
    assert_funding_conservation,
    build_funded_appointment,
    build_term_frame,
    lock_term_payroll,
    make_appointment,
    make_funding_source,
    make_student,
    read_appointment,
    read_source,
    read_term,
    set_funding_plan,
    submit,
    suspend_source,
    validate_error,
    validate_paginated,
)

# --------------------------------------------------------------------------- #
# Scheduling payroll against a term that has already locked payroll
# --------------------------------------------------------------------------- #


def _build_active_appointment_in_a_payroll_locked_term():
    """An ACTIVE, never-scheduled appointment whose term then locks payroll."""
    world = build_funded_appointment(
        department={"code": "LING", "name": "Linguistics"},
        term={
            "term_code": "XTERM2026", "term_start": "2026-09-01",
            "term_end": "2026-12-31", "tax_calendar_year": 2026,
            "session_type": "IN_SESSION", "proration_method": "CALENDAR_DAY",
            "remission_drop_deadline": "2026-11-15",
        },
        policy={
            "assistantship_type": "RESEARCH", "degree_level": "DOCTORAL",
            "min_fte_monthly_stipend_cents": 400000,
            "per_credit_tuition_cents": 50000,
            "max_remission_cents_per_term": 500000,
            "term_insurance_premium_cents": 0,
        },
        pay_periods=MONTHLY_PERIODS_AUTUMN_2026,
        student={
            "student_number": "GS-XT-001", "full_name": "Xt Student",
            "degree_level": "DOCTORAL", "cumulative_gpa": 3.60,
            "enrolled_credit_hours": 0,
        },
        source={
            "source_code": "NSF-XT-01", "source_type": "GRANT",
            "authorized_amount_cents": 5000000,
        },
        appointment={
            "assistantship_type": "RESEARCH", "effort_pct": 75,
            "start_date": "2026-09-01", "end_date": "2026-12-31",
            "monthly_stipend_cents": 300000,
        },
        advance_to="ACTIVE",
    )
    lock_term_payroll(world["term_id"])
    return world


def test_scheduling_payroll_is_refused_once_the_term_has_locked_payroll():
    """The appointment is in the only state scheduling accepts, and still fails.

    PRD: "A `GradSchoolAdmin` schedules payroll, advancing `NOT_SCHEDULED →
    SCHEDULED`; the appointment's `payroll_status` must be `NOT_SCHEDULED`, its
    `lifecycle_status` must be exactly `ACTIVE` — otherwise
    `ERR_INVALID_APPOINTMENT_STATE` — and the term must be `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/schedule_payroll_blocked_when_term_payroll_locked
    """
    world = _build_active_appointment_in_a_payroll_locked_term()

    response = api_client.schedule_payroll(world["appointment_id"], GS_ADMIN)

    validate_error(response, ApiErrorId.ERR_TERM_NOT_OPEN.value, 409)

    appointment = read_appointment(world["appointment_id"])
    assert appointment["lifecycle_status"] == "ACTIVE", (
        "the appointment itself was never in a wrong state"
    )
    assert appointment["payroll_status"] == "NOT_SCHEDULED"


def test_a_refused_scheduling_call_materialises_no_disbursements():
    """Nothing is created, and the locked term's periods are all locked.

    PRD: "Locking sets `locked_at` to the current logical-clock instant and moves
    every pay period of the term still `OPEN` to `LOCKED`, which is exactly what
    makes disbursement payment possible." PRD: "Scheduling materialises the money.
    One `StipendDisbursement` row is created for each pay period of the term that
    intersects the appointment's window".

    Design: Difficulty/cross_entity_state_dependency/schedule_payroll_blocked_when_term_payroll_locked
    """
    world = _build_active_appointment_in_a_payroll_locked_term()

    api_client.schedule_payroll(world["appointment_id"], GS_ADMIN)

    rows, meta = validate_paginated(api_client.list_stipend_disbursements(
        GS_ADMIN,
        {"appointment_id": world["appointment_id"], "limit": 10, "offset": 0},
    ))
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    term = read_term(world["term_id"])
    assert term["status"] == "PAYROLL_LOCKED"

    periods, period_meta = validate_paginated(api_client.list_term_pay_periods(
        world["term_id"], GS_ADMIN, {"limit": 10, "offset": 0},
    ))
    assert period_meta["total_count"] == 4
    for period in periods:
        assert period["status"] == "LOCKED"


# --------------------------------------------------------------------------- #
# Verifying funding when one of two plan sources has been suspended
# --------------------------------------------------------------------------- #


def _build_submitted_plan_with_one_suspended_source():
    """A 70/30 plan whose 30 percent departmental cost-share line is suspended."""
    frame = build_term_frame(
        department={"code": "ANTH", "name": "Anthropology"},
        term={
            "term_code": "SUSP2026", "term_start": "2026-09-01",
            "term_end": "2026-09-30", "tax_calendar_year": 2026,
            "session_type": "IN_SESSION", "proration_method": "CALENDAR_DAY",
            "remission_drop_deadline": "2026-09-15",
        },
        policy={
            "assistantship_type": "RESEARCH", "degree_level": "DOCTORAL",
            "min_fte_monthly_stipend_cents": 400000,
            "per_credit_tuition_cents": 50000,
            "max_remission_cents_per_term": 500000,
            "term_insurance_premium_cents": 0,
        },
        pay_periods=[(1, "2026-09-01", "2026-10-01", "2026-10-05")],
    )
    student = make_student(
        student_number="GS-SUSP-001", full_name="Susp Student",
        degree_level="DOCTORAL", cumulative_gpa=3.60, enrolled_credit_hours=0,
    )
    healthy = make_funding_source(
        frame["department_id"], source_code="NSF-SUSP-01", source_type="GRANT",
        authorized_amount_cents=5000000,
    )
    cost_share = make_funding_source(
        frame["department_id"], source_code="DEPT-SUSP-01",
        source_type="DEPARTMENTAL_BUDGET", authorized_amount_cents=5000000,
        allows_tuition_remission=True,
    )
    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        assistantship_type="RESEARCH", effort_pct=75,
        start_date="2026-09-01", end_date="2026-09-30",
        monthly_stipend_cents=300000,
    )
    set_funding_plan(appointment["id"], [
        (healthy["id"], 70.00, False),
        (cost_share["id"], 30.00, True),
    ])
    submit(appointment["id"])
    suspend_source(cost_share["id"], "SPONSOR_HOLD")
    return {
        "appointment_id": appointment["id"],
        "healthy_source_id": healthy["id"],
        "cost_share_source_id": cost_share["id"],
    }


def test_verify_funding_is_refused_when_any_plan_source_is_suspended():
    """One suspended line out of two blocks the whole verification.

    PRD: "Every funding source referenced by one of the appointment's allocations
    must have `status` of exactly `ACTIVE`; a suspended or closed source is
    `ERR_FUNDING_SOURCE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/verify_funding_blocked_when_one_cost_share_source_suspended
    """
    world = _build_submitted_plan_with_one_suspended_source()

    response = api_client.verify_funding(
        world["appointment_id"], GRANT_ACCOUNTANT
    )

    validate_error(response, ApiErrorId.ERR_FUNDING_SOURCE_NOT_ACTIVE.value, 409)

    appointment = read_appointment(world["appointment_id"])
    assert appointment["lifecycle_status"] == "SUBMITTED"


def test_a_refused_verification_commits_neither_allocation():
    """Commitment is all-or-nothing: the healthy source is not encumbered either.

    PRD: "On success, every allocation of the appointment in `PROPOSED` moves to
    `COMMITTED`, and each affected source's `committed_amount_cents` and
    `available_amount_cents` are recomputed." PRD: "Suspension moves the source
    `ACTIVE → SUSPENDED` and blocks new commitments; it deliberately leaves
    existing `COMMITTED` allocations untouched, because a sponsor hold is not a
    clawback."

    Design: Difficulty/cross_entity_state_dependency/verify_funding_blocked_when_one_cost_share_source_suspended
    """
    world = _build_submitted_plan_with_one_suspended_source()

    api_client.verify_funding(world["appointment_id"], GRANT_ACCOUNTANT)

    allocations, meta = validate_paginated(api_client.list_funding_allocations(
        GRANT_ACCOUNTANT,
        {"appointment_id": world["appointment_id"], "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 2
    for allocation in allocations:
        assert allocation["status"] == "PROPOSED"

    healthy = read_source(world["healthy_source_id"])
    assert healthy["status"] == "ACTIVE"
    assert healthy["committed_amount_cents"] == 0
    assert healthy["available_amount_cents"] == 5000000
    assert_funding_conservation(healthy)

    suspended = read_source(world["cost_share_source_id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "SPONSOR_HOLD"
    assert suspended["committed_amount_cents"] == 0
    assert_funding_conservation(suspended)
