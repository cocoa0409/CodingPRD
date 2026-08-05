"""Enrolling a student for a school year: the lifecycle, its caps and its
cascades."""

from test_helpers import (
    REGISTRAR,
    ApiErrorId,
    activate_enrollment,
    assert_enrollment,
    assert_same_instant,
    create_enrollment,
    create_school,
    create_student,
    get_student,
    reinstate_enrollment,
    set_clock,
    setup_visit_scheduled,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_enrollment,
)


def test_enrollment_opens_pending_and_activation_stamps_the_logical_instant(api):
    """PRD §3.3: "A new enrollment is born in `PENDING`, with `activated_at` and
    `withdrawn_at` both null, `withdrawal_reason` null and `reinstated_count` at
    0."
    PRD §3.3: "Moving a `PENDING` enrollment to `ACTIVE` is permitted only from
    `PENDING` and only while the site is `ACTIVE`; it stamps `activated_at` with
    the current logical instant, recomputes the student's immunization compliance
    posture — which now has an anchor for its provisional window — and increments
    the student's `version` by 1."

    Design: Corner/state_machines/enrollment_starts_pending_and_activate_stamps_activated_at
    """
    set_clock("2026-05-04T09:00:00Z")
    school = create_school()
    student = create_student()

    created = validate_success(
        api.create_enrollment(
            student["id"],
            {
                "school_id": school["id"],
                "school_year": "2025-2026",
                "expected_student_version": student["version"],
            },
            REGISTRAR,
        ),
        201,
    )
    assert_enrollment(created)
    assert created["status"] == "PENDING"
    assert created["activated_at"] is None
    assert created["withdrawn_at"] is None
    assert created["withdrawal_reason"] is None
    assert created["reinstated_count"] == 0

    activated = validate_success(api.activate_enrollment(created["id"], REGISTRAR))

    assert activated["status"] == "ACTIVE"
    assert_same_instant(
        activated["activated_at"], "2026-05-04T09:00:00.000Z", "Enrollment.activated_at"
    )
    # Student.version steps once for the create and once for the activation.
    assert get_student(student["id"])["version"] == 3


def test_activating_an_already_active_enrollment_is_a_state_error(api):
    """PRD §3.3: "Moving a `PENDING` enrollment to `ACTIVE` is permitted only from
    `PENDING` and only while the site is `ACTIVE`; it stamps `activated_at` with
    the current logical instant, recomputes the student's immunization compliance
    posture — which now has an anchor for its provisional window — and increments
    the student's `version` by 1."
    PRD §2.6 rung 17: "The target row is in a state from which the requested
    transition exists, on every action endpoint. Otherwise `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/enrollment_activate_twice_returns_invalid_state
    """
    set_clock("2026-05-04T09:00:00Z")
    school = create_school()
    student = create_student()
    enrollment = create_enrollment(student["id"], school["id"])
    activate_enrollment(enrollment["id"])
    set_clock("2026-05-05T09:00:00Z")

    resp = api.activate_enrollment(enrollment["id"], REGISTRAR)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    reread = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
    assert reread["status"] == "ACTIVE"
    assert_same_instant(
        reread["activated_at"], "2026-05-04T09:00:00.000Z", "Enrollment.activated_at"
    )


def test_third_reinstatement_on_the_same_row_is_refused(api):
    """PRD §3.3: "Reinstatement closes the cycle `ACTIVE → WITHDRAWN → ACTIVE` on
    the same row, and it is capped: a row may be reinstated at most 2 times, so
    the third attempt on the same enrollment is refused with
    `ERR_REINSTATEMENT_LIMIT_EXCEEDED`."
    PRD §3.3: "Reinstating requires the row to be `WITHDRAWN`, the site to be
    `ACTIVE`, and `reinstated_count` to be strictly below 2."

    Design: Corner/state_machines/enrollment_third_reinstatement_returns_limit_exceeded
    """
    set_clock("2026-05-04T09:00:00Z")
    school = create_school()
    student = create_student()
    enrollment = create_enrollment(student["id"], school["id"])
    activate_enrollment(enrollment["id"])

    withdraw_enrollment(enrollment["id"], "Family moved out of district")
    reinstate_enrollment(enrollment["id"])
    withdraw_enrollment(enrollment["id"], "Second withdrawal")
    reinstate_enrollment(enrollment["id"])
    withdraw_enrollment(enrollment["id"], "Third withdrawal")

    resp = api.reinstate_enrollment(enrollment["id"], REGISTRAR)

    validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_LIMIT_EXCEEDED.value, 409)

    reread = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
    assert reread["status"] == "WITHDRAWN"
    assert reread["reinstated_count"] == 2


def test_withdrawal_cancels_the_scheduled_encounters_of_that_enrollment(api):
    """PRD §3.3: "Moving an `ACTIVE` enrollment to `WITHDRAWN` requires a
    `reason`, which is stored as `withdrawal_reason`, and stamps `withdrawn_at`
    with the current logical instant. It then cascades: every encounter anchored
    to that enrollment whose clinical state is `SCHEDULED` or `IN_PROGRESS` moves
    to `CANCELLED`"

    Design: Corner/state_machines/enrollment_withdraw_cancels_scheduled_visits_of_that_enrollment
    """
    ctx = setup_visit_scheduled(scheduled_start_at="2026-05-06T10:00:00Z")

    withdrawn = validate_success(
        api.withdraw_enrollment(
            ctx["enrollment"]["id"], {"reason": "Family moved out of district"}, REGISTRAR
        )
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert_same_instant(
        withdrawn["withdrawn_at"], "2026-05-04T09:00:00.000Z", "Enrollment.withdrawn_at"
    )
    assert withdrawn["withdrawal_reason"] == "Family moved out of district"

    visit = validate_success(api.get_visit(ctx["visit"]["id"], REGISTRAR))
    assert visit["clinical_status"] == "CANCELLED"
    assert visit["billing_status"] == "NOT_APPLICABLE"

    charges, meta = validate_paginated(
        api.list_charges(REGISTRAR, params={"visit_id": ctx["visit"]["id"]})
    )
    assert meta["total_count"] == 0, "A cancelled encounter mints no charges"
    assert charges == []


def test_enrollment_create_with_a_stale_student_version_is_rejected(api):
    """PRD §2.7: "**Creating an enrollment** (`POST
    /sbhc/students/{id}/enrollments`) requires `expected_student_version` to match
    the student's current `version`. A new enrollment for the same school year
    legitimately transfers the prior one away, so a writer working from an
    out-of-date view of the student would otherwise move the child to a different
    site on top of a record it has not observed. Mismatch yields
    `ERR_STALE_VERSION` (412)."
    PRD §3.3: "Any enrollment already on file for the same student and the same
    school year whose status is `PENDING` or `ACTIVE` is moved to `TRANSFERRED`
    and stamped with a `withdrawn_at` of the current logical instant"

    Design: Corner/cross_cutting_complexity_layers/enrollment_create_with_stale_student_version_returns_stale_version
    """
    set_clock("2026-05-04T09:00:00Z")
    school_a = create_school(name="Lincoln High", site_code="LHS")
    school_b = create_school(name="Adams Middle", site_code="AMS")
    student = create_student()
    stale_version = student["version"]

    enrollment_a = validate_success(
        api.create_enrollment(
            student["id"],
            {
                "school_id": school_a["id"],
                "school_year": "2025-2026",
                "expected_student_version": stale_version,
            },
            REGISTRAR,
        ),
        201,
    )
    fresh_version = get_student(student["id"])["version"]

    stale_resp = api.create_enrollment(
        student["id"],
        {
            "school_id": school_b["id"],
            "school_year": "2025-2026",
            "expected_student_version": stale_version,
        },
        REGISTRAR,
    )
    validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION.value, 412)

    enrollment_b = validate_success(
        api.create_enrollment(
            student["id"],
            {
                "school_id": school_b["id"],
                "school_year": "2025-2026",
                "expected_student_version": fresh_version,
            },
            REGISTRAR,
        ),
        201,
    )

    assert validate_success(api.get_enrollment(enrollment_a["id"], REGISTRAR))[
        "status"
    ] == "TRANSFERRED"
    assert enrollment_b["status"] == "PENDING"
    assert enrollment_b["school_id"] == school_b["id"]

    rows, meta = validate_paginated(
        api.list_enrollments(REGISTRAR, params={"student_id": student["id"]})
    )
    assert meta["total_count"] == 2, f"Expected exactly two enrollment rows, got {meta['total_count']}"
    assert len(rows) == 2
