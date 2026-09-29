"""Cascades whose later levels are caused by earlier levels, not by the request.

Termination and a non-renewal notice each move rows the client never named, and
the last level of each chain is a funding-source balance recomputation that can
flip the source's own status.
"""
from test_helpers import (
    CLOCK_STARTUP_DATE,
    DEPARTMENT_ADMIN_USER_ID,
    DEPT_ADMIN,
    FACULTY,
    GS_ADMIN,
    GRANT_ACCOUNTANT,
    MONTHLY_PERIODS_AUTUMN_2026,
    allocations_of,
    api_client,
    assert_funding_conservation,
    build_funded_appointment,
    build_renewal_review,
    drive_appointment,
    fund_wholly_from,
    make_appointment,
    make_pay_periods,
    make_policy,
    make_term,
    open_term,
    read_appointment,
    read_source,
    read_student,
    set_clock,
    suspend_source,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Termination: six levels ending in an automatic reinstatement
# --------------------------------------------------------------------------- #


def _build_terminable_appointment_on_a_suspended_source():
    """Payroll scheduled against a grant that is then suspended for overcommitment.

    The grant's auto-reinstate threshold is set to its full authorization, so the
    suspension can only clear once every last cent has been released.
    """
    world = build_funded_appointment(
        department={"code": "CHEM", "name": "Chemistry"},
        term={
            "term_code": "CASC2026", "term_start": "2026-09-01",
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
            "student_number": "GS-CASC-001", "full_name": "Casc Student",
            "degree_level": "DOCTORAL", "cumulative_gpa": 3.60,
            "enrolled_credit_hours": 8,
        },
        source={
            "source_code": "NSF-CASC-01", "source_type": "GRANT",
            "authorized_amount_cents": 5000000,
            "auto_reinstate_threshold_cents": 5000000,
        },
        appointment={
            "assistantship_type": "RESEARCH", "effort_pct": 75,
            "start_date": "2026-09-01", "end_date": "2026-12-31",
            "monthly_stipend_cents": 300000,
        },
        advance_to="PAYROLL_SCHEDULED",
    )
    suspend_source(world["source_id"], "OVERCOMMITMENT")
    return world


def _terminate(appointment_id):
    return validate_success(api_client.terminate_appointment(
        appointment_id,
        {"termination_reason": "STUDENT_WITHDREW_FROM_PROGRAM"},
        GS_ADMIN,
    ))


def test_termination_voids_scheduled_disbursements_and_retains_their_gross():
    """Both axes go terminal and the voided rows keep their amounts for audit.

    PRD: "The first step sets `lifecycle_status` to the terminal `TERMINATED`,
    stores `termination_reason`, sets `termination_date` to the current
    logical-clock date, and sets `payroll_status` to the terminal `PAY_VOIDED`".
    PRD: "every disbursement of the appointment still in `SCHEDULED` moves to
    the terminal `VOIDED` with `voided_at` stamped at the current logical-clock
    instant; the row's `gross_amount_cents` is deliberately retained for audit
    rather than zeroed."

    Design: Difficulty/transitive_cascade/terminate_cascade_six_levels_auto_reinstates_overcommitted_source
    """
    world = _build_terminable_appointment_on_a_suspended_source()

    terminated = _terminate(world["appointment_id"])

    assert terminated["lifecycle_status"] == "TERMINATED"
    assert terminated["payroll_status"] == "PAY_VOIDED"
    assert terminated["termination_reason"] == "STUDENT_WITHDREW_FROM_PROGRAM"
    assert terminated["termination_date"] == CLOCK_STARTUP_DATE, (
        "the termination date is the logical-clock date, which starts at "
        "2026-08-01"
    )

    rows, meta = validate_paginated(api_client.list_stipend_disbursements(
        GS_ADMIN,
        {"appointment_id": world["appointment_id"], "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 4
    for row in rows:
        assert row["status"] == "VOIDED"
        assert row["voided_at"] is not None
        assert row["gross_amount_cents"] == 300000


def test_termination_before_the_drop_deadline_zeroes_the_remission_and_releases():
    """The deadline test drops the benefit, which empties and releases the plan.

    PRD: "when `termination_date` falls before the term's
    `remission_drop_deadline`, `tuition_remission_cents` is set to 0, and when it
    falls on or after that deadline the entitlement is left unchanged". PRD:
    "every allocation still in `COMMITTED` whose `allocated_stipend_cents` plus
    `allocated_remission_cents` has fallen to 0 moves to `RELEASED` with
    `release_reason` set to `APPOINTMENT_TERMINATED`."

    Design: Difficulty/transitive_cascade/terminate_cascade_six_levels_auto_reinstates_overcommitted_source
    """
    world = _build_terminable_appointment_on_a_suspended_source()

    terminated = _terminate(world["appointment_id"])

    assert terminated["tuition_remission_cents"] == 0, (
        "2026-08-01 falls before the 2026-11-15 remission drop deadline"
    )

    allocations = allocations_of(world["appointment_id"])
    assert len(allocations) == 1
    allocation = allocations[0]
    assert allocation["status"] == "RELEASED"
    assert allocation["release_reason"] == "APPOINTMENT_TERMINATED"
    assert allocation["allocated_stipend_cents"] == 0, (
        "no disbursement was ever paid, so the recomputed stipend is 0"
    )
    assert allocation["allocated_remission_cents"] == 0


def test_termination_auto_reinstates_a_source_suspended_for_overcommitment():
    """The last cascade level flips the source's own status back to ACTIVE.

    PRD: "every source that is `SUSPENDED` with `suspension_reason` of
    `OVERCOMMITMENT` and whose `available_amount_cents` has reached or passed its
    `auto_reinstate_threshold_cents` returns to `ACTIVE` with
    `suspension_reason` cleared."

    Design: Difficulty/transitive_cascade/terminate_cascade_six_levels_auto_reinstates_overcommitted_source
    """
    world = _build_terminable_appointment_on_a_suspended_source()
    before = read_source(world["source_id"])
    assert before["status"] == "SUSPENDED"
    assert before["suspension_reason"] == "OVERCOMMITMENT"

    _terminate(world["appointment_id"])

    after = read_source(world["source_id"])
    assert after["committed_amount_cents"] == 0
    assert after["expended_amount_cents"] == 0
    assert after["available_amount_cents"] == 5000000, (
        "the whole authorization is free again once the plan is released"
    )
    assert after["status"] == "ACTIVE"
    assert after["suspension_reason"] is None
    assert_funding_conservation(after)


def test_termination_recomputes_the_students_effort_aggregates_to_zero():
    """Leaving a counted state empties the student's effort figures.

    PRD: "Finally, caused by the first step, the student's `total_effort_pct` and
    `assigned_hours_per_week` are recomputed and the student's `version`
    incremented". PRD: "when the student holds no counted appointment at all,
    the persisted aggregate is 0."

    Design: Difficulty/transitive_cascade/terminate_cascade_six_levels_auto_reinstates_overcommitted_source
    """
    world = _build_terminable_appointment_on_a_suspended_source()

    _terminate(world["appointment_id"])

    student = read_student(world["student_id"])
    assert student["total_effort_pct"] == 0
    assert float(student["assigned_hours_per_week"]) == 0.0


# --------------------------------------------------------------------------- #
# Non-renewal: a notice on one appointment collapses its successor
# --------------------------------------------------------------------------- #

_RENEWAL_POLICY = {
    "assistantship_type": "RESEARCH", "degree_level": "DOCTORAL",
    "min_fte_monthly_stipend_cents": 400000,
    "per_credit_tuition_cents": 50000,
    "max_remission_cents_per_term": 500000,
    "term_insurance_premium_cents": 0,
}


def _build_renewal_chain():
    """An ACTIVE autumn appointment plus a funding-verified spring successor.

    The successor names the autumn appointment through
    `renewed_from_appointment_id`, which is the edge the cancellation cascade
    walks.
    """
    set_clock("2026-10-01T00:00:00Z")
    world = build_funded_appointment(
        department={"code": "CHEM", "name": "Chemistry",
                    "non_renewal_notice_days": 60},
        term={
            "term_code": "FALLA2026", "term_start": "2026-09-01",
            "term_end": "2026-12-15", "tax_calendar_year": 2026,
            "session_type": "IN_SESSION", "proration_method": "CALENDAR_DAY",
            "remission_drop_deadline": "2026-11-15",
        },
        policy=_RENEWAL_POLICY,
        pay_periods=[(1, "2026-09-01", "2026-12-16", "2026-12-20")],
        student={
            "student_number": "GS-NRN-001", "full_name": "Nrn Student",
            "degree_level": "DOCTORAL", "cumulative_gpa": 3.60,
            "enrolled_credit_hours": 0,
        },
        source={
            "source_code": "NSF-A-01", "source_type": "GRANT",
            "authorized_amount_cents": 3000000,
        },
        appointment={
            "assistantship_type": "RESEARCH", "effort_pct": 75,
            "start_date": "2026-09-01", "end_date": "2026-12-15",
            "monthly_stipend_cents": 300000,
        },
        advance_to="ACTIVE",
    )

    spring = make_term(
        term_code="SPRB2027", term_start="2027-01-05", term_end="2027-05-15",
        tax_calendar_year=2027, session_type="IN_SESSION",
        proration_method="CALENDAR_DAY", remission_drop_deadline="2027-03-15",
    )
    make_policy(spring["id"], **_RENEWAL_POLICY)
    make_pay_periods(spring["id"], [(1, "2027-01-05", "2027-05-16", "2027-05-20")])
    open_term(spring["id"])

    successor_source = validate_success(api_client.create_funding_source({
        "department_id": world["department_id"],
        "source_code": "NIH-B-01",
        "source_type": "GRANT",
        "authorized_amount_cents": 2000000,
        "budget_period_start": "2026-07-01",
        "budget_period_end": "2027-06-30",
        "allows_tuition_remission": True,
    }, GRANT_ACCOUNTANT), expected_status=201)

    successor = make_appointment(
        world["student_id"], world["department_id"], spring["id"],
        assistantship_type="RESEARCH", effort_pct=75,
        start_date="2027-01-05", end_date="2027-05-15",
        monthly_stipend_cents=300000,
        renewed_from_appointment_id=world["appointment_id"],
    )
    fund_wholly_from(successor["id"], successor_source["id"])
    drive_appointment(successor["id"], "FUNDING_VERIFIED")

    world["successor_id"] = successor["id"]
    world["successor_source_id"] = successor_source["id"]
    world["decision"] = build_renewal_review(
        world["appointment_id"], certify=True, creator=DEPT_ADMIN,
        certifier=FACULTY,
    )
    return world


def _issue_non_renewal(decision_id):
    return validate_success(api_client.issue_notice(
        decision_id, {"decision": "NON_RENEW"}, DEPT_ADMIN
    ))


def test_non_renew_notice_moves_the_predecessor_to_non_renewal_pending():
    """The notice records who issued it and pushes the appointment off renewal.

    PRD: "On success the review's `decision` is recorded, `issued_by_user_id`
    records the acting user, and `notice_sent_date` is set to the current
    logical-clock date." PRD: "When the `decision` is `NON_RENEW`, the
    appointment advances `ACTIVE → NON_RENEWAL_PENDING` and its
    `renewal_eligible` becomes false".

    Design: Difficulty/transitive_cascade/non_renewal_notice_cascade_cancels_successor_and_releases_commitments
    """
    world = _build_renewal_chain()

    issued = _issue_non_renewal(world["decision"]["id"])

    assert issued["status"] == "NOTICE_ISSUED"
    assert issued["decision"] == "NON_RENEW"
    assert issued["issued_by_user_id"] == DEPARTMENT_ADMIN_USER_ID
    assert issued["notice_sent_date"] == "2026-10-01"

    predecessor = read_appointment(world["appointment_id"])
    assert predecessor["lifecycle_status"] == "NON_RENEWAL_PENDING"
    assert predecessor["renewal_eligible"] is False


def test_non_renew_notice_cancels_the_funding_verified_successor():
    """The cascade walks the renewal self-reference and cancels the successor.

    PRD: "caused by that, every appointment whose `renewed_from_appointment_id`
    names this appointment and whose `lifecycle_status` is `DRAFT`, `SUBMITTED`,
    `RETURNED` or `FUNDING_VERIFIED` moves to the terminal `CANCELLED`".

    Design: Difficulty/transitive_cascade/non_renewal_notice_cascade_cancels_successor_and_releases_commitments
    """
    world = _build_renewal_chain()

    _issue_non_renewal(world["decision"]["id"])

    successor = read_appointment(world["successor_id"])
    assert successor["lifecycle_status"] == "CANCELLED"
    assert successor["renewed_from_appointment_id"] == world["appointment_id"]


def test_cancelled_successor_returns_its_encumbrance_to_its_own_source():
    """Only the successor's source is credited; the predecessor's stays encumbered.

    PRD: "caused by each successor entering `CANCELLED`, that successor's
    allocations in `PROPOSED` or `COMMITTED` move to `RELEASED` with
    `release_reason` set to `PREDECESSOR_NON_RENEWED` and both
    `allocated_stipend_cents` and `allocated_remission_cents` zeroed; caused by
    each such release, the affected sources' `committed_amount_cents` and
    `available_amount_cents` are recomputed".

    Design: Difficulty/transitive_cascade/non_renewal_notice_cascade_cancels_successor_and_releases_commitments
    """
    world = _build_renewal_chain()

    _issue_non_renewal(world["decision"]["id"])

    allocations = allocations_of(world["successor_id"])
    assert len(allocations) == 1
    assert allocations[0]["status"] == "RELEASED"
    assert allocations[0]["release_reason"] == "PREDECESSOR_NON_RENEWED"
    assert allocations[0]["allocated_stipend_cents"] == 0
    assert allocations[0]["allocated_remission_cents"] == 0

    successor_source = read_source(world["successor_source_id"])
    assert successor_source["committed_amount_cents"] == 0
    assert successor_source["available_amount_cents"] == 2000000
    assert_funding_conservation(successor_source)

    predecessor_source = read_source(world["source_id"])
    assert predecessor_source["committed_amount_cents"] == 300000, (
        "the predecessor stays in a counted state, so its commitment stands"
    )
    assert predecessor_source["available_amount_cents"] == 2700000
    assert_funding_conservation(predecessor_source)

    student = read_student(world["student_id"])
    assert student["total_effort_pct"] == 75, (
        "only the cancelled successor left the counted set"
    )
