"""Conserved ledgers and their exactly compensating reverse movements."""
from test_helpers import (
    assert_restitution_identity,
    build_finding,
    build_payment,
    compliant_paid_line,
    get_success_data,
    setup_accepted_submission,
    setup_deficient_submission_under_review,
)

WEEK = "2026-08-01T00:00:00.000Z"


def _disbursed_in_full(api):
    """A 560000 UNDERPAYMENT demand answered and paid in full. Returns (env, sub, finding, pay)."""
    env, submission, rows = setup_deficient_submission_under_review(api)
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="UNDERPAYMENT", severity="MAJOR", restitution_required_cents=560000,
    )
    get_success_data(
        api.file_finding_response(
            finding["id"],
            {
                "response_narrative": "Back wages computed; cheque issued to the worker.",
                "expected_finding_version": finding["version"],
            },
            env["certifier_headers"],
        )
    )
    payment = build_payment(api, env, finding["id"], rows[0]["worker_id"], 560000)
    payment = get_success_data(
        api.disburse_restitution_payment(payment["id"], env["preparer_headers"])
    )
    return env, submission, finding, payment


def test_reversing_a_disbursement_restores_every_derived_value(api, officer_headers):
    """The reversal restores the balance, the tier ledger, the finding status and the posture.

    PRD 2.10: "reversing a disbursed payment increases the outstanding balance and reduces the
    assignment's cumulative restitution by that same amount, returning both to their exact
    pre-disbursement values." PRD 3.11: "If that finding had auto-advanced to
    `RESPONSE_ACCEPTED` solely because its balance hit zero, it rolls back to
    `RESPONSE_SUBMITTED`; the cited submission's compliance axis then returns to
    `RESTITUTION_PENDING` when at least one `DISBURSED` payment still exists on any finding
    citing that submission, and to `DEFICIENT` when none does."

    Design: Difficulty/compensating_invariant/restitution_obligation_cents_conserved_across_disburse_and_reverse
    """
    env, submission, finding, payment = _disbursed_in_full(api)
    reversed_payment = get_success_data(
        api.reverse_restitution_payment(
            payment["id"],
            {"reversal_reason": "Cheque returned unpaid by the drawee bank."},
            officer_headers,
        )
    )
    assert reversed_payment["status"] == "REVERSED"
    assert reversed_payment["amount_cents"] == 560000

    after = get_success_data(api.get_finding(finding["id"], officer_headers))
    assert after["restitution_required_cents"] == 560000
    assert after["restitution_outstanding_cents"] == 560000
    assert after["status"] == "RESPONSE_SUBMITTED"

    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], officer_headers)
    )
    assert assignment["cumulative_restitution_cents"] == 0
    cited = get_success_data(api.get_payroll_submission(submission["id"], officer_headers))
    assert cited["compliance_status"] == "DEFICIENT"
    project = get_success_data(api.get_project(env["project"]["id"], officer_headers))
    assert project["outstanding_restitution_cents"] == 560000
    assert project["open_finding_count"] == 1
    assert project["posture"] == "FROZEN"


def test_the_restitution_identity_holds_at_every_point_of_the_cycle(api, officer_headers):
    """required == outstanding + sum of DISBURSED amounts, before, during and after.

    PRD 2.10: "For every finding whose `status` is not `WITHDRAWN`, the finding's
    `restitution_required_cents` must at all times equal its `restitution_outstanding_cents`
    plus the sum of `amount_cents` over the restitution payments on that finding whose `status`
    is `DISBURSED`. Payments in `PENDING`, `VOIDED` or `REVERSED` contribute zero to the
    disbursed side of that identity."

    Design: Difficulty/compensating_invariant/restitution_obligation_cents_conserved_across_disburse_and_reverse
    """
    env, submission, rows = setup_deficient_submission_under_review(api)
    finding = build_finding(
        api, env["project"]["id"], submission["id"],
        finding_type="UNDERPAYMENT", severity="MAJOR", restitution_required_cents=560000,
    )
    get_success_data(
        api.file_finding_response(
            finding["id"],
            {
                "response_narrative": "Back wages computed; cheque issued to the worker.",
                "expected_finding_version": finding["version"],
            },
            env["certifier_headers"],
        )
    )
    payment = build_payment(api, env, finding["id"], rows[0]["worker_id"], 560000)
    assert payment["status"] == "PENDING"
    # A promise, not a movement: the PENDING row contributes zero.
    assert_restitution_identity(
        get_success_data(api.get_finding(finding["id"], officer_headers)), 0
    )

    get_success_data(api.disburse_restitution_payment(payment["id"], env["preparer_headers"]))
    assert_restitution_identity(
        get_success_data(api.get_finding(finding["id"], officer_headers)), 560000
    )

    get_success_data(
        api.reverse_restitution_payment(
            payment["id"],
            {"reversal_reason": "Cheque returned unpaid by the drawee bank."},
            officer_headers,
        )
    )
    assert_restitution_identity(
        get_success_data(api.get_finding(finding["id"], officer_headers)), 0
    )


def _accepted_forty_hours(api):
    return setup_accepted_submission(
        api,
        lines=[compliant_paid_line(fringe_cash_paid_cents=2000)],
        week_ending_date=WEEK,
        rates=[{"fringe_hourly_rate_cents": 2000}],
    )


def test_rescinding_acceptance_returns_the_hours_ledger_to_zero(api, officer_headers):
    """The 40.00 credited hours are subtracted back exactly, not netted or left behind.

    PRD 3.8: "An `AgencyComplianceOfficer` supplying a `rescission_reason` — which must be
    present — moves the axis `ACCEPTED → UNDER_REVIEW`, clears `accepted_by_user_id` back to
    null, and subtracts the submission's `total_hours_reported` from the tier's
    `cumulative_certified_hours`, restoring exactly the value that stood before acceptance."

    Design: Difficulty/compensating_invariant/certified_hours_ledger_conserved_across_accept_and_rescind
    """
    env, submission, _rows = _accepted_forty_hours(api)
    credited = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], officer_headers)
    )
    assert float(credited["cumulative_certified_hours"]) == 40.00

    rescinded = get_success_data(
        api.rescind_acceptance(
            submission["id"],
            {"rescission_reason": "Acceptance recorded against the wrong week; reopening for review."},
            officer_headers,
        )
    )
    assert rescinded["workflow_status"] == "UNDER_REVIEW"
    assert rescinded["accepted_by_user_id"] is None
    assert float(rescinded["total_hours_reported"]) == 40.00
    assert rescinded["compliance_status"] == "COMPLIANT"

    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], officer_headers)
    )
    assert float(assignment["cumulative_certified_hours"]) == 0.00
    project = get_success_data(api.get_project(env["project"]["id"], officer_headers))
    assert project["posture"] == "OPEN"


def test_the_accept_rescind_cycle_keeps_the_hours_ledger_exact(api, officer_headers):
    """Re-accepting after a rescission credits the 40.00 hours exactly once again.

    PRD 2.10: "A contract assignment's `cumulative_certified_hours` must at all times equal
    the sum of `total_hours_reported` over the payroll submissions on that assignment whose
    `workflow_status` is `ACCEPTED`." PRD 3.8: "The `UNDER_REVIEW → ACCEPTED → UNDER_REVIEW`
    cycle may repeat, and the certified-hours ledger described in §2.10 stays exact across
    every traversal."

    Design: Difficulty/compensating_invariant/certified_hours_ledger_conserved_across_accept_and_rescind
    """
    env, submission, _rows = _accepted_forty_hours(api)
    get_success_data(
        api.rescind_acceptance(
            submission["id"], {"rescission_reason": "Reopening for a second read."}, officer_headers
        )
    )
    reaccepted = get_success_data(api.accept_payroll_submission(submission["id"], officer_headers))
    assert reaccepted["workflow_status"] == "ACCEPTED"

    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], officer_headers)
    )
    assert float(assignment["cumulative_certified_hours"]) == 40.00

    get_success_data(
        api.rescind_acceptance(
            submission["id"], {"rescission_reason": "Reopening once more."}, officer_headers
        )
    )
    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], officer_headers)
    )
    assert float(assignment["cumulative_certified_hours"]) == 0.00
