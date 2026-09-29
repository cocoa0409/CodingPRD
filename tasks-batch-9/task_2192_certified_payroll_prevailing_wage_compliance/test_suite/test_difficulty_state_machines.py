"""Parallel and cyclic state-machine shapes."""
from test_helpers import (
    build_finding,
    compliant_paid_line,
    get_success_data,
    setup_accepted_submission,
)

WEEK = "2026-08-01T00:00:00.000Z"


def _accepted_compliant(api):
    """An ACCEPTED, COMPLIANT weekly payroll of 40.00 fully paid journeyworker hours."""
    return setup_accepted_submission(
        api,
        lines=[compliant_paid_line(fringe_cash_paid_cents=2000)],
        week_ending_date=WEEK,
        rates=[{"fringe_hourly_rate_cents": 2000}],
    )


def test_compliance_axis_moves_while_the_workflow_axis_stays_accepted(api, cruz_headers):
    """A finding drives the accepted payroll COMPLIANT -> DEFICIENT without touching filing.

    PRD 3.6: "The two axes evolve independently from this point onward: a submission can be
    `ACCEPTED` on the filing axis while cycling through `DEFICIENT`,
    `RESTITUTION_PENDING` and `REMEDIED` on the compliance axis, and the compliance axis has
    no terminal state at all."

    Design: Difficulty/non_linear_state_machine/payroll_submission_parallel_axes_move_independently
    """
    env, submission, _rows = _accepted_compliant(api)
    assert submission["workflow_status"] == "ACCEPTED"
    assert submission["compliance_status"] == "COMPLIANT"

    build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="APPRENTICE_RATIO", severity="MINOR", restitution_required_cents=0,
    )

    after = get_success_data(api.get_payroll_submission(submission["id"], cruz_headers))
    assert after["workflow_status"] == "ACCEPTED"
    assert after["compliance_status"] == "DEFICIENT"
    project = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert project["open_finding_count"] == 1
    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], cruz_headers)
    )
    assert float(assignment["cumulative_certified_hours"]) == 40.00


def test_withdrawing_the_finding_remedies_the_compliance_axis_only(api, cruz_headers):
    """Withdrawal returns the compliance axis to REMEDIED while filing stays ACCEPTED.

    PRD 3.10: "Withdrawal sets `status` to `WITHDRAWN`, forces
    `restitution_outstanding_cents` to 0, advances the finding's `version` by one, sets every
    restitution payment on the finding that is still `PENDING` to `VOIDED`, and then
    recomputes the project's finding counters, outstanding restitution and `posture`".

    Design: Difficulty/non_linear_state_machine/payroll_submission_parallel_axes_move_independently
    """
    env, submission, _rows = _accepted_compliant(api)
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="APPRENTICE_RATIO", severity="MINOR", restitution_required_cents=0,
    )
    withdrawn = get_success_data(
        api.withdraw_finding(
            finding["id"],
            {"withdrawal_reason": "Transmittal evidence located in the portal archive."},
            cruz_headers,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    after = get_success_data(api.get_payroll_submission(submission["id"], cruz_headers))
    assert after["workflow_status"] == "ACCEPTED"
    assert after["compliance_status"] == "REMEDIED"
    project = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert project["open_finding_count"] == 0
    assert project["posture"] == "OPEN"
    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], cruz_headers)
    )
    assert float(assignment["cumulative_certified_hours"]) == 40.00


def test_rejecting_a_response_returns_the_finding_to_response_rejected(api, officer_2_headers):
    """The first round lands on RESPONSE_SUBMITTED and a rejection sends it back.

    PRD 3.10: "A successful filing writes the `response_narrative` ... advances
    `response_round` by one, moves the finding `OPEN → RESPONSE_SUBMITTED` or
    `RESPONSE_REJECTED → RESPONSE_SUBMITTED`". PRD 3.10: "A `decision` to reject moves the
    finding `RESPONSE_SUBMITTED → RESPONSE_REJECTED` and advances its `version` by one,
    which reopens the contractor's ability to file a further response."

    Design: Difficulty/non_linear_state_machine/finding_response_rejection_revision_loop_increments_round
    """
    env, submission, _rows = _accepted_compliant(api)
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="APPRENTICE_RATIO", severity="MINOR", restitution_required_cents=0,
    )
    responded = get_success_data(
        api.file_finding_response(
            finding["id"],
            {
                "response_narrative": "Transmittal page 2 lists the apprentice period.",
                "expected_finding_version": finding["version"],
            },
            env["certifier_headers"],
        )
    )
    assert responded["status"] == "RESPONSE_SUBMITTED"
    assert responded["response_round"] == 1

    rejected = get_success_data(
        api.review_finding_response(
            finding["id"],
            {"decision": "REJECT", "reviewer_note": "Page 2 was not attached to the response."},
            officer_2_headers,
        )
    )
    assert rejected["status"] == "RESPONSE_REJECTED"
    # Revisiting a state does not reset the running count of filed rounds.
    assert rejected["response_round"] == 1


def test_the_revision_loop_advances_response_round_to_two(api, officer_2_headers, cruz_headers):
    """RESPONSE_REJECTED -> RESPONSE_SUBMITTED fires a second time and round reaches 2.

    PRD 3.10: "That revision loop — `RESPONSE_REJECTED → RESPONSE_SUBMITTED →
    RESPONSE_REJECTED` — may repeat without bound, and `response_round` is the running count
    of how many rounds have been filed."

    Design: Difficulty/non_linear_state_machine/finding_response_rejection_revision_loop_increments_round
    """
    env, submission, _rows = _accepted_compliant(api)
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="APPRENTICE_RATIO", severity="MINOR", restitution_required_cents=0,
    )
    v1 = get_success_data(
        api.file_finding_response(
            finding["id"],
            {
                "response_narrative": "Transmittal page 2 lists the apprentice period.",
                "expected_finding_version": finding["version"],
            },
            env["certifier_headers"],
        )
    )
    v3 = get_success_data(
        api.review_finding_response(
            finding["id"],
            {"decision": "REJECT", "reviewer_note": "Page 2 was not attached to the response."},
            officer_2_headers,
        )
    )
    assert v3["version"] > v1["version"]
    v4 = get_success_data(
        api.file_finding_response(
            finding["id"],
            {
                "response_narrative": "Page 2 re-attached with the JATC registration extract.",
                "expected_finding_version": v3["version"],
            },
            env["certifier_headers"],
        )
    )
    assert v4["status"] == "RESPONSE_SUBMITTED"
    assert v4["response_round"] == 2
    assert v4["response_narrative"] == "Page 2 re-attached with the JATC registration extract."

    after = get_success_data(api.get_payroll_submission(submission["id"], cruz_headers))
    assert after["compliance_status"] == "DEFICIENT"
    assert after["workflow_status"] == "ACCEPTED"
    project = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert project["open_finding_count"] == 1
