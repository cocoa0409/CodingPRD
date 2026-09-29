"""Depth-4 transitive cascades in the freezing and the thawing direction."""
from test_helpers import (
    build_finding,
    build_payment,
    certify,
    compliant_paid_line,
    finalize,
    build_line,
    build_submission,
    build_worker,
    accept,
    begin_review,
    get_success_data,
    setup_deficient_submission_under_review,
    setup_two_project_env,
)

WEEK = "2026-08-01T00:00:00.000Z"


def _two_projects_with_accepted_payroll(api):
    """P1 carries an ACCEPTED, COMPLIANT payroll; P2 carries no payroll and no findings."""
    p1, p2 = setup_two_project_env(api)
    worker = build_worker(api, p1["contractor"]["id"], p1["preparer_headers"])
    submission = build_submission(api, p1, week_ending_date=WEEK)
    build_line(
        api, p1, submission["id"], worker["id"],
        **compliant_paid_line(fringe_cash_paid_cents=2000),
    )
    finalize(api, p1, submission["id"])
    certify(api, p1, submission["id"])
    begin_review(api, submission["id"])
    submission = accept(api, submission["id"])
    return p1, p2, submission


def test_finding_creation_cascades_to_debarment_proposal_and_cross_project_suspension(
    api, cruz_headers
):
    """Three findings reach a score of exactly 70, proposing debarment and suspending both tiers.

    PRD 3.11: "Each such finding whose `severity` is `CRITICAL` contributes forty points,
    each `MAJOR` fifteen points, and each `MINOR` eight points." PRD 3.11: "A contractor in
    `CLEAR` whose recomputed score reaches seventy is driven `CLEAR → PROPOSED`; the
    threshold is inclusive, so a score of exactly 70 does propose debarment. That transition
    ... drives every one of that contractor's `ACTIVE` tiers on every project through
    `ACTIVE → SUSPENDED`."

    Design: Difficulty/transitive_cascade/finding_creation_cascades_to_debarment_proposal_and_cross_project_suspension
    """
    p1, p2, submission = _two_projects_with_accepted_payroll(api)
    build_finding(
        api, p1["project"]["id"], submission["id"],
        finding_type="UNDERPAYMENT", severity="CRITICAL", restitution_required_cents=0,
    )
    build_finding(
        api, p1["project"]["id"], submission["id"],
        finding_type="FRINGE_CREDIT", severity="MAJOR", restitution_required_cents=0,
    )
    build_finding(
        api, p1["project"]["id"], submission["id"],
        finding_type="MISCLASSIFICATION", severity="MAJOR", restitution_required_cents=0,
    )

    contractor = get_success_data(api.get_contractor(p1["contractor"]["id"], cruz_headers))
    assert contractor["debarment_risk_score"] == 70
    assert contractor["debarment_status"] == "PROPOSED"

    a1 = get_success_data(api.get_contract_assignment(p1["assignment"]["id"], cruz_headers))
    a2 = get_success_data(api.get_contract_assignment(p2["assignment"]["id"], cruz_headers))
    assert a1["status"] == "SUSPENDED"
    assert a2["status"] == "SUSPENDED"

    project1 = get_success_data(api.get_project(p1["project"]["id"], cruz_headers))
    assert project1["posture"] == "FROZEN"
    assert project1["open_finding_count"] == 3
    assert project1["open_critical_finding_count"] == 1


def test_suspension_propagates_across_the_aggregate_boundary_to_a_finding_free_project(
    api, cruz_headers
):
    """P2 carries no findings at all yet becomes RESTRICTED off its suspended tier.

    PRD 2.9: "Step four: otherwise, if at least one assignment on the project is suspended,
    the posture is `RESTRICTED`." PRD 3.4: "Suspension advances the tier's `version` by one
    and then, as a consequence of the suspension itself, forces the parent project to
    recompute `suspended_assignment_count` and re-evaluate `posture`".

    Design: Difficulty/transitive_cascade/finding_creation_cascades_to_debarment_proposal_and_cross_project_suspension
    """
    p1, p2, submission = _two_projects_with_accepted_payroll(api)
    for finding_type, severity in (
        ("UNDERPAYMENT", "CRITICAL"),
        ("FRINGE_CREDIT", "MAJOR"),
        ("MISCLASSIFICATION", "MAJOR"),
    ):
        build_finding(
            api, p1["project"]["id"], submission["id"],
            finding_type=finding_type, severity=severity, restitution_required_cents=0,
        )

    project2 = get_success_data(api.get_project(p2["project"]["id"], cruz_headers))
    assert project2["open_finding_count"] == 0
    assert project2["suspended_assignment_count"] == 1
    assert project2["posture"] == "RESTRICTED"


def test_disbursement_cascades_to_auto_acceptance_and_remediation(api, officer_headers):
    """Paying the demand in full auto-accepts the finding and remedies the compliance axis.

    PRD 3.11: "When the disbursement drives the finding's outstanding balance to exactly zero
    while its `finding_type` is `UNDERPAYMENT` and it sits in `RESPONSE_SUBMITTED`, the
    finding auto-advances `RESPONSE_SUBMITTED → RESPONSE_ACCEPTED` without any agency action
    — full payment of an underpayment demand settles it — and that auto-acceptance in turn
    advances the cited submission's compliance axis to `REMEDIED` when no other finding on
    that submission remains non-terminal".

    Design: Difficulty/transitive_cascade/restitution_disbursement_cascades_to_auto_acceptance_and_posture_thaw
    """
    env, submission, rows = setup_deficient_submission_under_review(api)
    assert submission["make_whole_underpayment_cents"] == 560000
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="UNDERPAYMENT", severity="MAJOR", restitution_required_cents=560000,
    )
    get_success_data(
        api.file_finding_response(
            finding["id"],
            {
                "response_narrative": "Back wages computed and scheduled for payment.",
                "expected_finding_version": finding["version"],
            },
            env["certifier_headers"],
        )
    )
    payment = build_payment(api, env, finding["id"], rows[0]["worker_id"], 560000)
    disbursed = get_success_data(
        api.disburse_restitution_payment(payment["id"], env["preparer_headers"])
    )

    assert disbursed["status"] == "DISBURSED"
    settled = get_success_data(api.get_finding(finding["id"], officer_headers))
    assert settled["restitution_outstanding_cents"] == 0
    assert settled["status"] == "RESPONSE_ACCEPTED"
    after = get_success_data(api.get_payroll_submission(submission["id"], officer_headers))
    assert after["make_whole_underpayment_cents"] == 560000
    assert after["compliance_status"] == "REMEDIED"
    assert after["workflow_status"] == "UNDER_REVIEW"


def test_disbursement_thaws_the_project_posture(api, officer_headers):
    """A 560000 demand freezes the project and settling it in full returns the posture to OPEN.

    PRD 2.9: "Step two: otherwise, if the project's outstanding restitution is strictly
    greater than five thousand dollars — that is, more than 500,000 cents — the posture is
    `FROZEN`". PRD 3.11 recomputes "the project's counters and `posture`" behind the
    auto-acceptance.

    Design: Difficulty/transitive_cascade/restitution_disbursement_cascades_to_auto_acceptance_and_posture_thaw
    """
    env, submission, rows = setup_deficient_submission_under_review(api)
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="UNDERPAYMENT", severity="MAJOR", restitution_required_cents=560000,
    )
    frozen = get_success_data(api.get_project(env["project"]["id"], officer_headers))
    assert frozen["outstanding_restitution_cents"] == 560000
    assert frozen["posture"] == "FROZEN"

    get_success_data(
        api.file_finding_response(
            finding["id"],
            {
                "response_narrative": "Back wages computed and scheduled for payment.",
                "expected_finding_version": finding["version"],
            },
            env["certifier_headers"],
        )
    )
    payment = build_payment(api, env, finding["id"], rows[0]["worker_id"], 560000)
    get_success_data(api.disburse_restitution_payment(payment["id"], env["preparer_headers"]))

    thawed = get_success_data(api.get_project(env["project"]["id"], officer_headers))
    assert thawed["outstanding_restitution_cents"] == 0
    assert thawed["open_finding_count"] == 0
    assert thawed["posture"] == "OPEN"
    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], officer_headers)
    )
    assert assignment["cumulative_restitution_cents"] == 560000
