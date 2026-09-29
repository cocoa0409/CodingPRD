"""State machines that are not a single forward line.

An appointment carries two independent status axes, and a renewal review carries
a revision loop.  Both are places where a naive single-status model produces the
wrong answer.
"""
from test_helpers import (
    GRAD_SCHOOL_ADMIN_USER_ID,
    GS_ADMIN,
    FACULTY,
    FACULTY_SUPERVISOR_USER_ID,
    MONTHLY_PERIODS_AUTUMN_2026,
    api_client,
    build_funded_appointment,
    build_renewal_review,
    read_appointment,
    read_renewal_decision,
    set_clock,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------- #
# The two appointment axes: suspending pay must not disturb the academic axis
# --------------------------------------------------------------------------- #


def _build_scheduled_payroll_appointment():
    return build_funded_appointment(
        department={"code": "ECON", "name": "Economics"},
        term={
            "term_code": "PAR2026", "term_start": "2026-09-01",
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
            "student_number": "GS-PAR-001", "full_name": "Par Student",
            "degree_level": "DOCTORAL", "cumulative_gpa": 3.55,
            "enrolled_credit_hours": 0,
        },
        source={
            "source_code": "NSF-PAR-01", "source_type": "GRANT",
            "authorized_amount_cents": 5000000,
        },
        appointment={
            "assistantship_type": "RESEARCH", "effort_pct": 75,
            "start_date": "2026-09-01", "end_date": "2026-12-31",
            "monthly_stipend_cents": 300000,
        },
        advance_to="PAYROLL_SCHEDULED",
    )


def test_suspending_pay_leaves_the_appointment_lifecycle_active():
    """Freezing the stipend moves only the payroll axis.

    PRD: "A `GradSchoolAdmin` may move `payroll_status` from either `SCHEDULED`
    or `PARTIALLY_DISBURSED` to `PAY_SUSPENDED`, supplying
    `pay_suspension_reason`, which is stored. The appointment's
    `lifecycle_status` must be `ACTIVE` or `NON_RENEWAL_PENDING`, else
    `ERR_INVALID_APPOINTMENT_STATE` — and, critically, `lifecycle_status` is
    **not** modified by the suspension."

    Design: Difficulty/non_linear_state_machine/appointment_parallel_axes_pay_suspend_leaves_lifecycle_active
    """
    world = _build_scheduled_payroll_appointment()

    suspended = validate_success(api_client.suspend_pay(
        world["appointment_id"],
        {"pay_suspension_reason": "VISA_DOCUMENTATION_PENDING"},
        GS_ADMIN,
    ))

    assert suspended["payroll_status"] == "PAY_SUSPENDED"
    assert suspended["lifecycle_status"] == "ACTIVE", (
        "the academic appointment continues while the stipend is frozen"
    )
    assert suspended["pay_suspension_reason"] == "VISA_DOCUMENTATION_PENDING"
    assert suspended["approved_by_user_id"] == GRAD_SCHOOL_ADMIN_USER_ID


def test_resuming_pay_with_no_paid_history_returns_to_scheduled():
    """Resumption branches on paid history and clears the stored reason.

    PRD: "Resuming pay moves the appointment out of `PAY_SUSPENDED` and clears
    `pay_suspension_reason` to null, and it branches on paid history with equal
    precision in both directions: when the appointment has no disbursement in
    `PAID`, `payroll_status` returns to `SCHEDULED`; when it has at least one
    disbursement in `PAID`, `payroll_status` returns to `PARTIALLY_DISBURSED`."

    Design: Difficulty/non_linear_state_machine/appointment_parallel_axes_pay_suspend_leaves_lifecycle_active
    """
    world = _build_scheduled_payroll_appointment()
    validate_success(api_client.suspend_pay(
        world["appointment_id"],
        {"pay_suspension_reason": "VISA_DOCUMENTATION_PENDING"},
        GS_ADMIN,
    ))

    resumed = validate_success(
        api_client.resume_pay(world["appointment_id"], GS_ADMIN)
    )

    assert resumed["payroll_status"] == "SCHEDULED", (
        "nothing was ever paid, so the axis returns to SCHEDULED"
    )
    assert resumed["lifecycle_status"] == "ACTIVE"
    assert resumed["pay_suspension_reason"] is None


def test_suspend_and_resume_cycle_leaves_every_disbursement_scheduled():
    """The suspension cycle never touches the materialised disbursement rows.

    PRD: "Each new row is `SCHEDULED` with `paid_at`, `voided_at`, `reversed_at`
    and `reversal_reason` all null." Nothing in the suspension or resumption
    rules moves a disbursement, so all four rows of the four-period calendar are
    still scheduled at their full prorated gross afterwards.

    Design: Difficulty/non_linear_state_machine/appointment_parallel_axes_pay_suspend_leaves_lifecycle_active
    """
    world = _build_scheduled_payroll_appointment()
    validate_success(api_client.suspend_pay(
        world["appointment_id"],
        {"pay_suspension_reason": "VISA_DOCUMENTATION_PENDING"},
        GS_ADMIN,
    ))
    validate_success(api_client.resume_pay(world["appointment_id"], GS_ADMIN))

    rows, meta = validate_paginated(api_client.list_stipend_disbursements(
        GS_ADMIN,
        {"appointment_id": world["appointment_id"], "limit": 10, "offset": 0},
    ))

    assert meta["total_count"] == 4, "one row per whole-month pay period"
    for row in rows:
        assert row["status"] == "SCHEDULED"
        assert row["gross_amount_cents"] == 300000, (
            "each whole-month period covers the window entirely, so no proration"
        )
    appointment = read_appointment(world["appointment_id"])
    assert appointment["total_stipend_cents"] == 1200000


# --------------------------------------------------------------------------- #
# The renewal revision loop: SAP_CERTIFIED -> DRAFT -> SAP_CERTIFIED
# --------------------------------------------------------------------------- #


def _build_certifiable_renewal_review():
    """An ACTIVE appointment ending 2026-12-15 with the renewal window open.

    The window opens 120 days before the end date, so the logical clock is moved
    to 2026-10-01 before the review is created.
    """
    set_clock("2026-10-01T00:00:00Z")
    world = build_funded_appointment(
        department={"code": "CHEM", "name": "Chemistry",
                    "non_renewal_notice_days": 60},
        term={
            "term_code": "RNW2026", "term_start": "2026-09-01",
            "term_end": "2026-12-15", "tax_calendar_year": 2026,
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
        pay_periods=[(1, "2026-09-01", "2026-12-16", "2026-12-20")],
        student={
            "student_number": "GS-RNW-001", "full_name": "Rnw Student",
            "degree_level": "DOCTORAL", "cumulative_gpa": 3.50,
            "enrolled_credit_hours": 0,
        },
        source={
            "source_code": "NSF-RNW-01", "source_type": "GRANT",
            "authorized_amount_cents": 3000000,
        },
        appointment={
            "assistantship_type": "RESEARCH", "effort_pct": 75,
            "start_date": "2026-09-01", "end_date": "2026-12-15",
            "monthly_stipend_cents": 300000,
        },
        advance_to="ACTIVE",
    )
    world["decision"] = build_renewal_review(world["appointment_id"])
    return world


def test_progress_downgrade_drives_a_certified_review_back_to_draft():
    """A downgrade in standing invalidates a certification and counts the revision.

    PRD: "Creation computes two dates from the appointment and its department:
    `renewal_window_open_date` is the appointment's `end_date` minus 120 days,
    and `notice_deadline_date` is the appointment's `end_date` minus the
    appointing department's `non_renewal_notice_days` days." PRD: "every renewal
    review belonging to an appointment of that student and currently sitting in
    `SAP_CERTIFIED` is forced back to `DRAFT`, its `sap_certified` flag reset to
    false, its `certified_by_user_id` and `certified_at` cleared, and its
    `revision_count` increased by one."

    Design: Difficulty/non_linear_state_machine/renewal_certification_revoked_cycle_increments_revision_count
    """
    world = _build_certifiable_renewal_review()
    decision = world["decision"]

    assert decision["renewal_window_open_date"] == "2026-08-17", (
        "2026-12-15 minus 120 days"
    )
    assert decision["notice_deadline_date"] == "2026-10-16", (
        "2026-12-15 minus the department's 60 notice days"
    )

    certified = validate_success(
        api_client.certify_progress(decision["id"], FACULTY)
    )
    assert certified["status"] == "SAP_CERTIFIED"
    assert certified["sap_certified"] is True
    assert certified["certified_by_user_id"] == FACULTY_SUPERVISOR_USER_ID
    assert certified["revision_count"] == 0

    validate_success(api_client.patch_academic_progress(
        world["student_id"],
        {"sap_status": "PROBATION", "cumulative_gpa": 2.80},
        GS_ADMIN,
    ))

    revoked = read_renewal_decision(decision["id"])
    assert revoked["status"] == "DRAFT"
    assert revoked["sap_certified"] is False
    assert revoked["certified_by_user_id"] is None
    assert revoked["certified_at"] is None
    assert revoked["revision_count"] == 1
    assert revoked["decision"] == "PENDING", (
        "the revision loop never touches the renew-or-not outcome"
    )


def test_recertifying_after_a_downgrade_keeps_the_incremented_revision_count():
    """The loop count reports how many times certification was redone.

    PRD: "As §3.2 describes, a later progress downgrade drives the review back
    `SAP_CERTIFIED → DRAFT`, clearing the certification and increasing
    `revision_count`; the review can then be certified again, and the pair of
    transitions forms a revision cycle whose loop count `revision_count`
    reports."

    Design: Difficulty/non_linear_state_machine/renewal_certification_revoked_cycle_increments_revision_count
    """
    world = _build_certifiable_renewal_review()
    decision_id = world["decision"]["id"]

    validate_success(api_client.certify_progress(decision_id, FACULTY))
    validate_success(api_client.patch_academic_progress(
        world["student_id"],
        {"sap_status": "PROBATION", "cumulative_gpa": 2.80},
        GS_ADMIN,
    ))
    validate_success(api_client.patch_academic_progress(
        world["student_id"],
        {"sap_status": "SATISFACTORY", "cumulative_gpa": 3.20},
        GS_ADMIN,
    ))

    recertified = validate_success(
        api_client.certify_progress(decision_id, FACULTY)
    )

    assert recertified["status"] == "SAP_CERTIFIED"
    assert recertified["sap_certified"] is True
    assert recertified["certified_by_user_id"] == FACULTY_SUPERVISOR_USER_ID
    assert recertified["revision_count"] == 1, (
        "one completed revision cycle, not a reset to 0 and not a second bump"
    )
    assert recertified["decision"] == "PENDING"


def test_the_renewal_revision_cycle_leaves_the_appointment_untouched():
    """No step of the certification loop reaches the appointment.

    PRD: "When the `decision` is `RENEW`, the appointment's `renewal_eligible`
    stays true and no appointment state changes at all." Only the notice-issuing
    step has a decision branch, so a review that has merely been certified,
    revoked and certified again leaves its appointment exactly as it was.

    Design: Difficulty/non_linear_state_machine/renewal_certification_revoked_cycle_increments_revision_count
    """
    world = _build_certifiable_renewal_review()
    decision_id = world["decision"]["id"]

    for stage in ("certify", "downgrade", "restore", "certify"):
        if stage == "certify":
            validate_success(api_client.certify_progress(decision_id, FACULTY))
        elif stage == "downgrade":
            validate_success(api_client.patch_academic_progress(
                world["student_id"],
                {"sap_status": "PROBATION", "cumulative_gpa": 2.80},
                GS_ADMIN,
            ))
        else:
            validate_success(api_client.patch_academic_progress(
                world["student_id"],
                {"sap_status": "SATISFACTORY", "cumulative_gpa": 3.20},
                GS_ADMIN,
            ))
        appointment = read_appointment(world["appointment_id"])
        assert appointment["lifecycle_status"] == "ACTIVE", (
            f"appointment must stay ACTIVE through the {stage} step"
        )
        assert appointment["renewal_eligible"] is True
