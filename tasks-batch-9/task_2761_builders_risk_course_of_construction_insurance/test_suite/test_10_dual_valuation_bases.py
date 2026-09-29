"""One row, two bases: the project risk index and the claim valuation basis.

The service scores a project twice from the same underlying facts, and it
values a loss twice from the same loss items. Both pairs are exercised here.
"""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    allocation_line,
    assert_claim,
    assert_claim_incurred_identity,
    assert_no_allocation_line,
)
from test_helpers.factories import loss_item


def _harborline_in_force():
    """The reference account: IN_FORCE, four coverage parts, premium 2750440."""
    account = fx.in_force_account()
    assert account.policy["quoted_premium_cents"] == 2750440, account.policy
    assert account.project["submission_risk_score"] == 28, account.project
    return account


def _extend_and_adjust(account):
    """Approve a 120-day slip and adjust one claim, so realised facts exist."""
    endorsement = fx.approved_endorsement(account, 120)
    claim = fx.adjusted_claim(
        account,
        [loss_item("IN_TRANSIT", 12345670)],
        adjustment_basis="ACTUAL_LOSS",
        peril="WIND",
        loss_date="2027-01-15T00:00:00Z",
    )
    return endorsement, claim


def test_submission_score_is_frozen_while_the_audit_score_rescores_realised_facts():
    """The submission basis reads nothing but the project's own submitted values,
    while the audit basis re-scores from the insured TIV, the extension-adjusted
    completion date and the count of qualifying claims. The same row therefore
    carries two different scores: 12 construction + 12 CAT + 4 value gives 28 on
    the submission basis, and the audit basis adds 4 duration points for the
    393-day adjusted schedule and 5 claim points for the adjusted claim.

    Design: Difficulty/dual_variant_calc/project_risk_score_submission_basis_versus_audit_basis
    """
    account = _harborline_in_force()
    _extend_and_adjust(account)

    project = get_success_data(api_client.get_project(
        account.project_id, fx.UW))

    assert project["submission_risk_score"] == 28, (
        "the submission basis must be untouched by the extension and the claim, "
        f"got {project['submission_risk_score']}")
    assert project["audit_risk_score"] == 37, (
        "audit basis is 12 + 12 + 4 value + 4 duration + 5 claim, "
        f"got {project['audit_risk_score']}")
    assert project["audit_risk_score"] - project["submission_risk_score"] == 9


def test_the_extension_and_claim_that_move_the_audit_basis_price_and_allocate_as_specified():
    """The realised facts that drive the audit basis are themselves derived
    figures: the 120-day slip is 120/302 of the original term, which is above a
    quarter and so prices at a slip factor of 1.40 on a 9107-cent daily base,
    and the accompanying claim retains the whole 10000000-cent occurrence
    deductible on its single IN_TRANSIT line.

    Design: Difficulty/dual_variant_calc/project_risk_score_submission_basis_versus_audit_basis
    """
    account = _harborline_in_force()
    endorsement, claim = _extend_and_adjust(account)

    assert endorsement["slip_factor"] == 1.40, endorsement["slip_factor"]
    assert endorsement["additional_premium_cents"] == 1529976, (
        f"9107 * 120 * 1.40 is 1529976, got {endorsement['additional_premium_cents']}")

    policy = account.refresh_policy()
    assert policy["cumulative_extension_days"] == 120, policy
    assert policy["adjusted_completion_date"] == "2027-09-29T00:00:00Z", policy

    assert_claim(claim, adjustment_status="ADJUSTED")
    assert claim["indemnity_cents"] == 2345670, claim["indemnity_cents"]
    assert claim["uncovered_cents"] == 10000000, claim["uncovered_cents"]
    assert_claim_incurred_identity(claim)


IDENTICAL_LOSS_ITEMS = [
    loss_item("MATERIALS_ON_SITE", 45678920),
    loss_item("IN_TRANSIT", 12345670),
]


def test_reconstruction_cost_basis_uplifts_every_line_and_indemnifies_continuing_management():
    """Under RECONSTRUCTION_COST each line's covered_basis_cents is its
    gross_loss_cents multiplied by 1.08 and rounded half up per line, and the
    carrier additionally indemnifies continuing project management at 0.0015 of
    the covered basis per week, appending a SOFT_COST line when the request
    carried none.

    Design: Difficulty/dual_variant_calc/claim_indemnity_reconstruction_cost_versus_actual_loss
    """
    account = _harborline_in_force()
    claim = fx.adjusted_claim(
        account,
        IDENTICAL_LOSS_ITEMS,
        adjustment_basis="RECONSTRUCTION_COST",
        continuing_pm_weeks=6,
    )

    assert claim["indemnity_cents"] == 53230557, (
        "39333234 MATERIALS_ON_SITE net of the deductible + 13333324 IN_TRANSIT "
        f"+ 563999 continuing PM, got {claim['indemnity_cents']}")
    assert len(claim["allocation_lines"]) == 3, claim["allocation_lines"]
    assert allocation_line(claim, "SOFT_COST")["allocated_cents"] == 563999
    assert claim["uncovered_cents"] == 10000000, claim["uncovered_cents"]
    assert_claim_incurred_identity(claim)


def test_actual_loss_basis_pays_documented_invoices_with_no_uplift_and_no_management():
    """Under ACTUAL_LOSS each line's covered_basis_cents is its gross_loss_cents
    unchanged and the project-management amount is forced to zero, so identical
    loss items indemnify 5205967 cents less than they do on the reconstruction
    basis and no SOFT_COST line is created at all.

    Design: Difficulty/dual_variant_calc/claim_indemnity_reconstruction_cost_versus_actual_loss
    """
    account = _harborline_in_force()
    reconstruction_claim = fx.adjusted_claim(
        account,
        IDENTICAL_LOSS_ITEMS,
        adjustment_basis="RECONSTRUCTION_COST",
        continuing_pm_weeks=6,
    )
    actual_loss_claim = fx.adjusted_claim(
        account,
        IDENTICAL_LOSS_ITEMS,
        adjustment_basis="ACTUAL_LOSS",
        continuing_pm_weeks=6,
    )

    assert actual_loss_claim["indemnity_cents"] == 48024590, (
        "35678920 + 12345670 with no uplift and no PM, "
        f"got {actual_loss_claim['indemnity_cents']}")
    assert len(actual_loss_claim["allocation_lines"]) == 2, (
        actual_loss_claim["allocation_lines"])
    assert_no_allocation_line(actual_loss_claim, "SOFT_COST")
    assert actual_loss_claim["uncovered_cents"] == 10000000
    assert (reconstruction_claim["indemnity_cents"]
            - actual_loss_claim["indemnity_cents"]) == 5205967
