"""Compliance posture threshold and address-report timeliness claims
(PRD §2.10, §3.10)."""
from test_helpers import (
    ALT_STUDENT,
    assert_address_report,
    create_address_report_payload,
    create_student,
    get_authorization,
    get_student,
    make_student_headers,
    set_clock,
    setup_opt_post_approved,
    validate_paginated,
    validate_success,
)


def test_posture_at_risk_at_unemployment_warning_75(api, dso_headers):
    """PRD §2.10: "Otherwise, if any of the student's address reports is
    `FLAGGED_LATE`, or any of the student's OPT_POST authorizations has
    `unemployment_days_settled` of at least 75 days, the posture is `AT_RISK`."
    PRD §3.5: "The clock sweep watches the settled counter: when
    `unemployment_days_settled` exceeds 90 days, the system opens an
    `UNEMPLOYMENT_LIMIT_EXCEEDED` violation in `OPEN` status for the student."

    Design: Corner/cross_cutting_layers/posture_at_risk_at_unemployment_warning_75
    """
    # Settled horizon 2027-03-03: elapsed 2026-12-19..2027-03-03 = 75 days.
    ctx = setup_opt_post_approved(eval_clock="2027-03-04T00:00:00Z")
    auth = get_authorization(ctx["authorization"]["id"])
    assert auth["unemployment_days_settled"] == 75

    student = get_student(ctx["student"]["id"])
    assert student["compliance_posture"] == "AT_RISK", (
        "75 settled days meets the warning threshold but not the violation limit"
    )

    violations, meta = validate_paginated(
        api.list_status_violations(ctx["student"]["id"], dso_headers)
    )
    assert meta["total_count"] == 0, "75 is not over 90: no violation opens"


def test_address_report_boundary_10_days(api, dso_headers):
    """PRD §3.10: "The filing's `status` is computed at creation: it is
    `REPORTED` when the clock date is no later than 10 days after the
    `move_date` — filing exactly on the tenth day counts as on time — and
    `FLAGGED_LATE` otherwise. A late landing recomputes the student's
    `compliance_posture`, which under §2.10 moves the student to `AT_RISK` in
    the absence of any open violation."

    Design: Corner/cross_cutting_layers/address_report_boundary_10_days
    """
    set_clock("2026-08-11T00:00:00Z")
    stu_a = create_student()
    stu_b = create_student(**ALT_STUDENT)

    # Filed exactly 10 days after the move: on time.
    report_a = validate_success(
        api.create_address_report(
            stu_a["id"],
            create_address_report_payload(move_date="2026-08-01"),
            make_student_headers(stu_a["id"]),
        ),
        201,
    )
    assert_address_report(report_a)
    assert report_a["status"] == "REPORTED"

    # Filed 11 days after the move: late, and the posture degrades to AT_RISK.
    report_b = validate_success(
        api.create_address_report(
            stu_b["id"],
            create_address_report_payload(
                move_date="2026-07-31", address_line1="2 College Ave",
            ),
            make_student_headers(stu_b["id"]),
        ),
        201,
    )
    assert report_b["status"] == "FLAGGED_LATE"
    assert get_student(stu_b["id"])["compliance_posture"] == "AT_RISK"
    assert get_student(stu_a["id"])["compliance_posture"] == "CLEAR"
