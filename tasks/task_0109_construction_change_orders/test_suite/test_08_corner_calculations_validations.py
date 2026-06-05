"""Calculation and validation corner tests (Corner queue: calculations,
validations sections)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    OWNER, CONTRACTOR, ARCHITECT,
    JAN,
    create_project, create_sov_line,
    setup_project_with_one_sov_line, setup_project_with_two_sov_lines,
    create_pay_application, add_pay_app_line, submit_pay_application,
    certify_pay_application, get_project_version,
    create_subcontractor_commitment, create_lien_waiver,
    create_change_order, submit_change_order,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Calculations
# ===========================================================================
class TestCommitmentInvoiceSweepUnconditional:
    def test_unconditional_notarize_credits_largest_balance_commitment(self, api):
        """PRD §3.6: "Making an unconditional waiver effective also runs the
        commitment-invoice sweep ... The credit applied to the chosen commitment is the
        smaller of the waiver's amount_cents and that commitment's remaining balance, and it
        is added to its invoiced_to_date_cents."

        Design: Corner/calculations/commitment_invoice_sweep_unconditional_credits_largest_balance
        """
        project, sov1, sov2, pay_app, commitment, waiver = (
            fx.setup_certified_with_commitment_and_pending_waiver("UNCONDITIONAL_PROGRESS")
        )
        resp = api.notarize_lien_waiver(waiver["id"], CONTRACTOR)
        data = validate_success(resp, 200)
        assert data["status"] == "EFFECTIVE"
        sc = validate_success(
            api.get_subcontractor_commitment(commitment["id"], OWNER), 200
        )
        # credit = min(405000, 500000 - 0) = 405000.
        assert sc["invoiced_to_date_cents"] == 405000


class TestConditionalWaiverNoSweep:
    def test_conditional_notarize_credits_no_commitment(self, api):
        """PRD §3.6: "A conditional waiver — CONDITIONAL_PROGRESS or CONDITIONAL_FINAL —
        moves no invoiced ledger at all on notarization; the sweep applies only to
        unconditional waivers."

        Design: Corner/calculations/conditional_waiver_notarize_no_commitment_credit
        """
        project, sov1, sov2, pay_app, commitment, waiver = (
            fx.setup_certified_with_commitment_and_pending_waiver("CONDITIONAL_PROGRESS")
        )
        resp = api.notarize_lien_waiver(waiver["id"], CONTRACTOR)
        data = validate_success(resp, 200)
        assert data["status"] == "EFFECTIVE"
        sc = validate_success(
            api.get_subcontractor_commitment(commitment["id"], OWNER), 200
        )
        assert sc["invoiced_to_date_cents"] == 0  # conditional waiver does not sweep.


# ===========================================================================
# Validations
# ===========================================================================
class TestLineEditsUnbalancedOnApprove:
    def test_unbalanced_line_edits_rejected_on_approve(self, api):
        """PRD §3.2: "the sum of scheduled_value_delta_cents across the edits exactly equals
        the change order's change_order_amount_cents (else ERR_LINE_EDITS_UNBALANCED, HTTP 422)".

        Design: Corner/validations/line_edits_unbalanced_on_co_approve
        """
        project, sov1, sov2, co = fx.setup_submitted_change_order(
            change_order_amount_cents=150_000,
            line_edits=[
                {"action": "ADJUST", "item_no": "001", "scheduled_value_delta_cents": 100_000},
                {"action": "ADD", "item_no": "003", "description": "X",
                 "scheduled_value_delta_cents": 40_000},
            ],
        )
        pv_cur = get_project_version(project["id"])
        resp = api.approve_change_order(
            co["id"], {"expected_project_version": pv_cur}, OWNER
        )
        validate_error(resp, ApiErrorId.ERR_LINE_EDITS_UNBALANCED.value, 422)


class TestWaiverAmountMismatch:
    def test_waiver_amount_not_matching_cpd_rejected(self, api):
        """PRD §3.6: "The waiver's amount_cents must equal the linked application's
        current_payment_due_cents and its through_date must equal that application's
        period_to; any mismatch is ERR_WAIVER_MISMATCH (HTTP 422)."

        Design: Corner/validations/waiver_amount_mismatch_returns_error
        """
        project, sov1, sov2, pay_app = fx.setup_certified_two_line_project()
        resp = api.create_lien_waiver(
            {"project_id": project["id"], "pay_app_id": pay_app["id"],
             "waiver_type": "CONDITIONAL_PROGRESS",
             "through_date": "2026-01-31T00:00:00.000Z", "amount_cents": 999},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_MISMATCH.value, 422)


class TestWaiverOnUncertifiedPayApp:
    def test_waiver_against_submitted_app_rejected(self, api):
        """PRD §3.6: "The linked pay application must be CERTIFIED, or the create is rejected
        with ERR_PAYAPP_NOT_CERTIFIED (HTTP 409)."

        Per PRD §2.10 the waiver field-match check (ERR_WAIVER_MISMATCH) is evaluated
        BEFORE the pay-application-certified check (ERR_PAYAPP_NOT_CERTIFIED). To isolate
        the not-certified gate, the waiver must already match the application's computed
        current_payment_due_cents (set on submission per PRD §3.3) and its period_to, so the
        field-match check passes and the certified check is the one that fires.

        Design: Corner/validations/waiver_on_uncertified_pay_app_returns_error
        """
        project, sov1, pay_app = fx.setup_submitted_pay_app_one_line()
        resp = api.create_lien_waiver(
            {"project_id": project["id"], "pay_app_id": pay_app["id"],
             "waiver_type": "CONDITIONAL_PROGRESS",
             "through_date": pay_app["period_to"],
             "amount_cents": pay_app["current_payment_due_cents"]},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_PAYAPP_NOT_CERTIFIED.value, 409)


class TestNonsequentialApplicationNumber:
    def test_application_number_two_with_no_prior_rejected(self, api):
        """PRD §3.3: "The application_number must be exactly one greater than the highest
        application_number among the project's pay applications that are not REJECTED — or 1
        if there are none ...; any violation of this sequencing is ERR_NONSEQUENTIAL_APPLICATION
        (HTTP 422)."

        Design: Corner/validations/nonsequential_application_number_returns_error
        """
        project, sov1 = setup_project_with_one_sov_line()
        resp = api.create_pay_application(
            {"project_id": project["id"], "application_number": 2,
             "period_from": JAN[0], "period_to": JAN[1],
             "expected_project_version": project["version"]},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_NONSEQUENTIAL_APPLICATION.value, 422)


class TestCrossProjectPayAppLine:
    def test_pay_app_line_with_foreign_sov_rejected(self, api):
        """PRD §2.8: "When a pay-app line is created, the schedule-of-values line named by
        sov_line_id must belong to the same project as the pay application named by
        pay_app_id ... A foreign key that resolves to a record in a different project is
        rejected with ERR_CROSS_PROJECT_REFERENCE (HTTP 422)."

        Design: Corner/validations/cross_project_pay_app_line_returns_error
        """
        project_a, sov_a = setup_project_with_one_sov_line(name="PA")
        project_b = create_project(1_000_000, name="PB")
        app_b = create_pay_application(project_b["id"], 1, JAN, project_b["version"])
        resp = api.create_pay_app_line(
            {"pay_app_id": app_b["id"], "sov_line_id": sov_a["id"],
             "work_completed_this_period_cents": 100, "materials_stored_cents": 0},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_PROJECT_REFERENCE.value, 422)
