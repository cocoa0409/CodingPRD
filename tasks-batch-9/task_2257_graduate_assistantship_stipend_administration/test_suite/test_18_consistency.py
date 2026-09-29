"""The write that computes the most, checked in the body it returns.

Submission runs four calculations and one aggregate recomputation, and every one
of their results has to be present in the very response that reports the new
state — no second read required.
"""
import pytest

from test_helpers import (
    DEPT_ADMIN,
    SINGLE_PERIOD_AUTUMN_2026,
    api_client,
    build_term_frame,
    fund_wholly_from,
    make_appointment,
    make_funding_source,
    make_student,
    read_student,
    validate_success,
)


def test_the_submit_response_already_carries_every_computed_money_field():
    """Schedule, remission, split and insurance all land in one response body.

    PRD: "Once the battery passes, the appointment's `lifecycle_status` becomes
    `SUBMITTED`, `submitted_by_user_id` records the acting `X-User-ID`, and
    `return_reason` is cleared to null. Four calculations then run, in this order,
    and together they populate every money field on the appointment and on its
    allocations." PRD: "Submission finally recomputes the student's
    `total_effort_pct` and `assigned_hours_per_week` and increments the student's
    `version`, because the student now carries effort it did not carry a moment
    ago."

    Design: Corner/consistency model/submit_response_reflects_all_computed_fields_immediately
    """
    frame = build_term_frame(
        policy={"per_credit_tuition_cents": 50000,
                "term_insurance_premium_cents": 600000},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
    )
    source = make_funding_source(frame["department_id"], source_code="NSF-A")
    student = make_student(student_number="GS-1094", enrolled_credit_hours=9)
    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=75, monthly_stipend_cents=300000,
    )
    fund_wholly_from(appointment["id"], source["id"])

    submitted = validate_success(
        api_client.submit_appointment(appointment["id"], DEPT_ADMIN)
    )

    assert submitted["lifecycle_status"] == "SUBMITTED"
    assert submitted["return_reason"] is None
    assert submitted["projected_pay_period_count"] == 1
    assert submitted["total_stipend_cents"] == 300000
    assert submitted["tuition_remission_pct"] == 100
    assert submitted["tuition_remission_cents"] == 450000
    assert submitted["insurance_eligible"] is True
    assert submitted["insurance_subsidy_cents"] == 540000, (
        "a gross below 1200000 takes the 90 percent tier"
    )
    assert submitted["employee_premium_cents"] == 60000
    assert submitted["net_term_stipend_cents"] == 240000

    aggregates = read_student(student["id"])
    assert aggregates["total_effort_pct"] == 75
    assert float(aggregates["assigned_hours_per_week"]) == pytest.approx(
        30.0, abs=0.01
    )
