"""Concerns that cut across every collection: version counters and the tax cap.

The two optimistic-concurrency preconditions are exercised against a stale read,
the version counter is followed across a chain of accepted writes including the
ones a cascade performs, and the exemption cap is probed at the exact boundary
where it is still inclusive.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEPT_ADMIN,
    FACULTY,
    GRAD_SCHOOL_ADMIN_USER_ID,
    GS_ADMIN,
    SINGLE_PERIOD_AUTUMN_2026,
    allocation_entry,
    allocations_of,
    api_client,
    assert_assessment_identity,
    build_funded_appointment,
    build_term_frame,
    funding_plan_payload,
    make_appointment,
    make_funding_source,
    make_student,
    open_term,
    read_appointment,
    read_student,
    read_term,
    set_funding_plan,
    tax_assessment_payload,
    validate_error,
    validate_success,
)


def test_replaying_a_superseded_appointment_version_on_a_plan_is_refused():
    """A second replacement has to re-read the appointment it supersedes.

    PRD: "Replacing an appointment's funding plan requires the request to carry
    `expected_appointment_version`, a non-optional field holding the `version` of
    the `Appointment` as the client last read it. If that value does not equal the
    appointment's current `version`, the replacement is rejected with
    `ERR_STALE_APPOINTMENT_VERSION` (HTTP 412)." PRD: "A successful replacement
    increments the appointment's `version` by one, so a second replacement must
    re-read the appointment first."

    Design: Corner/cross-cutting complexity layers/funding_plan_stale_appointment_version_rejected
    """
    frame = build_term_frame(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
    )
    grant_a = make_funding_source(frame["department_id"], source_code="NSF-A")
    grant_b = make_funding_source(frame["department_id"], source_code="NSF-B")
    student = make_student(student_number="GS-1090")
    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=75, monthly_stipend_cents=300000,
    )
    assert appointment["version"] == 1

    first = set_funding_plan(
        appointment["id"], [(grant_a["id"], 100.00)], expected_version=1,
    )
    assert first["version"] == 2
    second = set_funding_plan(
        appointment["id"], [(grant_a["id"], 60.00), (grant_b["id"], 40.00)],
        expected_version=2,
    )
    assert second["version"] == 3

    validate_error(
        api_client.replace_funding_plan(
            appointment["id"],
            funding_plan_payload(
                [allocation_entry(grant_b["id"], 100.00)],
                expected_appointment_version=2,
            ),
            DEPT_ADMIN,
        ),
        ApiErrorId.ERR_STALE_APPOINTMENT_VERSION.value, 412,
    )

    unchanged = read_appointment(appointment["id"])
    assert unchanged["version"] == 3, "the refused replacement was not a mutation"
    proposed = allocations_of(appointment["id"], status="PROPOSED")
    assert len(proposed) == 2, "the accepted second plan is still in force"
    assert proposed[0]["funding_source_id"] == grant_a["id"]
    assert proposed[1]["funding_source_id"] == grant_b["id"]
    # The appointment is still DRAFT, so the §3.5 stipend split has never run:
    # "New rows have allocated_stipend_cents, allocated_remission_cents and
    # disbursed_amount_cents all 0 and release_reason null."
    assert proposed[0]["allocated_stipend_cents"] == 0
    assert proposed[1]["allocated_stipend_cents"] == 0


def test_an_assessment_quoting_a_pre_patch_student_version_is_refused():
    """The progress patch moved the student on, so the quoted version is stale.

    PRD: "Creating a tuition-benefit tax assessment requires the request to carry
    `expected_student_version`, a non-optional field holding the `version` of the
    `GraduateStudent` as the client last read it. If that value does not equal the
    student's current `version`, the creation is rejected with
    `ERR_STALE_STUDENT_VERSION` (HTTP 412)." PRD: "The patched fields are written
    and the student's `version` is incremented."

    Design: Corner/cross-cutting complexity layers/assessment_stale_student_version_rejected
    """
    world = build_funded_appointment(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1091", "enrolled_credit_hours": 9},
        advance_to="ACTIVE",
    )
    stale_version = read_student(world["student_id"])["version"]

    patched = validate_success(api_client.patch_academic_progress(
        world["student_id"], {"cumulative_gpa": 3.75}, FACULTY,
    ))
    assert patched["version"] == stale_version + 1

    validate_error(
        api_client.create_tax_assessment(tax_assessment_payload(
            world["student_id"], world["term_id"],
            expected_student_version=stale_version,
        ), GS_ADMIN),
        ApiErrorId.ERR_STALE_STUDENT_VERSION.value, 412,
    )

    fresh_version = read_student(world["student_id"])["version"]
    assert fresh_version == patched["version"], (
        "the refused creation left the student untouched"
    )
    created = validate_success(api_client.create_tax_assessment(
        tax_assessment_payload(
            world["student_id"], world["term_id"],
            expected_student_version=fresh_version,
        ), GS_ADMIN,
    ), expected_status=201)
    assert created["status"] == "PROVISIONAL"
    assert created["benefit_cents"] == 450000
    assert read_student(world["student_id"])["version"] == fresh_version + 1


def test_every_accepted_write_advances_the_version_by_exactly_one():
    """Terms, students and appointments all count up, cascades included.

    PRD: "Every mutation — whether client-driven or server-driven inside a cascade
    — refreshes the mutated row's `updated_at` to the current logical-clock instant
    and increments its `version` by exactly one. This applies to derived fields as
    much as to input fields: when an appointment's submission recomputes a
    student's `total_effort_pct`, that recomputation is a mutation of the
    `GraduateStudent` row and increments the student's `version`." PRD: "`version`
    (integer): an integer that starts at 1 on creation and increments by one on
    every mutation, including mutations performed by a server-driven cascade."

    Design: Corner/cross-cutting complexity layers/version_increments_on_every_accepted_write
    """
    frame = build_term_frame(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        open_the_term=False,
    )
    assert frame["term"]["version"] == 1
    # The single accepted pay period recomputed the term's pay_period_count, and
    # "This applies to derived fields as much as to input fields", so the term is
    # already at version 2 before it is opened.
    assert read_term(frame["term_id"])["version"] == 2
    open_term(frame["term_id"])
    assert read_term(frame["term_id"])["version"] == 3

    student = make_student(student_number="GS-1092", enrolled_credit_hours=9)
    assert student["version"] == 1
    graded = validate_success(api_client.patch_academic_progress(
        student["id"], {"cumulative_gpa": 3.80}, FACULTY,
    ))
    assert graded["version"] == 2
    raised = validate_success(api_client.effort_cap_override(
        student["id"],
        {"approved_max_effort_pct": 100,
         "justification": "Dean-approved dual appointment."},
        GS_ADMIN,
    ))
    assert raised["version"] == 3
    assert raised["cap_override_by_user_id"] == GRAD_SCHOOL_ADMIN_USER_ID

    source = make_funding_source(frame["department_id"], source_code="NSF-A")
    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=75, monthly_stipend_cents=300000,
    )
    assert appointment["version"] == 1
    planned = set_funding_plan(appointment["id"], [(source["id"], 100.00)])
    assert planned["version"] == 2
    submitted = validate_success(
        api_client.submit_appointment(appointment["id"], DEPT_ADMIN)
    )
    assert submitted["version"] == 3

    after = read_student(student["id"])
    assert after["version"] == 4, (
        "the submission recomputed the student's aggregates, which is a mutation"
    )
    assert after["total_effort_pct"] == 75
    assert read_term(frame["term_id"])["version"] >= 2, "no version ever decreases"


def test_a_year_benefit_exactly_at_the_cap_is_exempt_in_full():
    """Cap comparisons are inclusive, so the boundary leaves nothing taxable.

    PRD: "Cap comparisons are inclusive: a year total exactly equal to the cap is
    fully exempt." PRD: "The year exemption is the smaller of that year benefit and
    the cap." PRD: "Two invariants hold: `benefit_cents` always equals
    `exempt_cents` plus `taxable_cents`, and the sum of `exempt_cents` over a
    student's `FINAL` assessments within one `tax_calendar_year` never exceeds the
    cap."

    Design: Corner/cross-cutting complexity layers/tuition_tax_exempt_cap_boundary_at_exact_cap_is_fully_exempt
    """
    world = build_funded_appointment(
        policy={"per_credit_tuition_cents": 43750,
                "max_remission_cents_per_term": 900000,
                "term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1093", "enrolled_credit_hours": 12},
        advance_to="ACTIVE",
    )
    appointment = read_appointment(world["appointment_id"])
    assert appointment["tuition_remission_pct"] == 100
    assert appointment["tuition_remission_cents"] == 525000, (
        "twelve doctoral credits at 43750 cents land exactly on the cap"
    )

    student_version = read_student(world["student_id"])["version"]
    provisional = validate_success(api_client.create_tax_assessment(
        tax_assessment_payload(
            world["student_id"], world["term_id"],
            expected_student_version=student_version,
        ), GS_ADMIN,
    ), expected_status=201)

    assert provisional["benefit_cents"] == 525000
    assert provisional["exempt_cents"] == 525000
    assert provisional["taxable_cents"] == 0
    assert provisional["imputed_withholding_cents"] == 0
    assert_assessment_identity(provisional)

    finalized = validate_success(
        api_client.finalize_tax_assessment(provisional["id"], GS_ADMIN)
    )

    assert finalized["status"] == "FINAL"
    assert finalized["variant_applied"] == "CALENDAR_YEAR_FINAL"
    assert finalized["benefit_cents"] == 525000
    assert finalized["exempt_cents"] == 525000, (
        "a year total equal to the cap is not one cent short of exempt"
    )
    assert finalized["taxable_cents"] == 0
    assert finalized["imputed_withholding_cents"] == 0
    assert_assessment_identity(finalized)

    student = read_student(world["student_id"])
    assert student["tuition_benefit_ytd_cents"] == 525000
    assert student["taxable_tuition_benefit_ytd_cents"] == 0
    assert float(appointment["weekly_hours"]) == pytest.approx(30.0, abs=0.01)
