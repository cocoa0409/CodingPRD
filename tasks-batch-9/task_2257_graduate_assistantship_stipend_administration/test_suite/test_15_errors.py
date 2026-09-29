"""The shape check that collapses three unrelated range violations into one error.

Every declared numeric range shares a single error identifier, so the same 422
answers a bad effort percentage, a bad grade average and a bad page size.
"""
from test_helpers import (
    ApiErrorId,
    DEPT_ADMIN,
    GS_ADMIN,
    SINGLE_PERIOD_AUTUMN_2026,
    api_client,
    appointment_payload,
    build_term_frame,
    make_student,
    student_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_three_out_of_range_scalars_all_report_one_invalid_request_error():
    """Effort above 100, a grade average above 4.00 and a page size above 100.

    PRD: "6. **Request shape** — required fields present, enum values within
    their declared sets, dates formatted as ISO 8601 calendar dates, `effort_pct`
    within 1 through 100, `share_pct` within 0.01 through 100.00 with at most two
    decimal places, an `allocations` array holding between 1 and 5 elements,
    `limit` within 1 through 100, `offset` at least 0, `end_date` on or after
    `start_date`, and `period_end_exclusive` strictly after `period_start`. Any
    failure is `ERR_INVALID_REQUEST` (422)." PRD: "and a `cumulative_gpa` between
    0.00 and 4.00 carried to two decimal places."

    Design: Corner/errors/out_of_range_scalars_rejected
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    student = make_student(student_number="GS-1070")

    responses = [
        api_client.create_appointment(appointment_payload(
            student["id"], frame["department_id"], frame["term_id"],
            effort_pct=110,
        ), DEPT_ADMIN),
        api_client.create_student(student_payload(
            student_number="GS-1071", full_name="Ben Ortiz",
            cumulative_gpa=5.00,
        ), GS_ADMIN),
        api_client.list_appointments(
            GS_ADMIN, {"term_id": frame["term_id"], "limit": 500},
        ),
    ]

    for response in responses:
        body = validate_error(
            response, ApiErrorId.ERR_INVALID_REQUEST.value, 422
        )
        assert isinstance(body["message"], str)
        assert body["message"] != "", "every error carries a readable message"

    _, meta = validate_paginated(api_client.list_appointments(
        GS_ADMIN, {"term_id": frame["term_id"], "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 0, "the rejected draft was never persisted"

    accepted = validate_success(api_client.create_student(student_payload(
        student_number="GS-1071", full_name="Ben Ortiz", cumulative_gpa=3.20,
    ), GS_ADMIN), expected_status=201)
    assert accepted["student_number"] == "GS-1071", (
        "the number is still free, so the rejected registration created nothing"
    )
