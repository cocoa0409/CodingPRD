"""G702/G703 calculation tests (Difficulty queue: dual_variant_calc,
combinatorial_formula)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    OWNER, CONTRACTOR, ARCHITECT,
    JAN, FEB,
    create_project, create_sov_line,
    setup_project_with_two_sov_lines, setup_project_with_one_sov_line,
    create_pay_application, add_pay_app_line, submit_pay_application,
    certify_pay_application, get_project_version,
    create_change_order, submit_change_order,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Rule: dual_variant_calc
# ===========================================================================
class TestPayAppCurrentPaymentDueFirstVsSubsequent:
    """Design: Difficulty/dual_variant_calc/payapp_current_payment_due_first_vs_subsequent"""

    def test_first_application_payment_due_no_prior_certificates(self, api):
        """PRD §3.4: "For the project's first certified application that prior-certificates
        draw is zero, so the payment due equals completed-and-stored less retainage".

        Design: Difficulty/dual_variant_calc/payapp_current_payment_due_first_vs_subsequent
        """
        project, sov1, sov2 = setup_project_with_two_sov_lines()
        pv1 = project["version"]
        app1 = create_pay_application(project["id"], 1, JAN, pv1)
        add_pay_app_line(app1["id"], sov1["id"], 300_000, 0)
        add_pay_app_line(app1["id"], sov2["id"], 100_000, 50_000)
        resp = api.submit_pay_application(app1["id"], CONTRACTOR)
        data = validate_success(resp, 200)
        # completed+stored = 450000, retainage = 45000, prior = 0 -> 405000.
        assert data["current_payment_due_cents"] == 405000

    def test_subsequent_application_subtracts_prior_certified_draw(self, api):
        """PRD §3.4: "for a subsequent application it subtracts the running total of
        previously certified payment-due amounts, the chronological less-previous-certificates draw."

        Design: Difficulty/dual_variant_calc/payapp_current_payment_due_first_vs_subsequent
        """
        project, sov1, sov2 = setup_project_with_two_sov_lines()
        pv1 = project["version"]
        app1 = create_pay_application(project["id"], 1, JAN, pv1)
        add_pay_app_line(app1["id"], sov1["id"], 300_000, 0)
        add_pay_app_line(app1["id"], sov2["id"], 100_000, 50_000)
        submit_pay_application(app1["id"])
        certify_pay_application(app1["id"])
        pv_cur = get_project_version(project["id"])
        app2 = create_pay_application(project["id"], 2, FEB, pv_cur)
        add_pay_app_line(app2["id"], sov1["id"], 300_000, 0)
        add_pay_app_line(app2["id"], sov2["id"], 200_000, 0)
        resp = api.submit_pay_application(app2["id"], CONTRACTOR)
        data = validate_success(resp, 200)
        # cumulative 600000 / 300000 -> completed 900000, retainage 90000, prior 405000.
        assert data["total_completed_and_stored_cents"] == 900000
        assert data["total_retainage_cents"] == 90000
        assert data["current_payment_due_cents"] == 405000


class TestRevisedContractSumAdditiveVsDeductive:
    """Design: Difficulty/dual_variant_calc/revised_contract_sum_additive_vs_deductive"""

    def test_deductive_change_order_lowers_revised_sum(self, api):
        """PRD §3.2: "the project's revised_contract_sum_cents is recomputed as the
        original_contract_sum_cents plus the sum of change_order_amount_cents over every
        change order on the project now in APPROVED status".

        Design: Difficulty/dual_variant_calc/revised_contract_sum_additive_vs_deductive
        """
        project, sov1, sov2, co = fx.setup_submitted_change_order(
            change_order_amount_cents=-50_000,
            line_edits=[{"action": "ADJUST", "item_no": "002",
                         "scheduled_value_delta_cents": -50_000}],
        )
        pv_cur = get_project_version(project["id"])
        resp = api.approve_change_order(
            co["id"], {"expected_project_version": pv_cur}, OWNER
        )
        co_data = validate_success(resp, 200)
        assert co_data["status"] == "APPROVED"
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        # 1000000 + (-50000) = 950000.
        assert proj["revised_contract_sum_cents"] == 950000

    def test_additive_change_order_raises_revised_sum(self, api):
        """PRD §3.2: "the project's revised_contract_sum_cents is recomputed as the
        original_contract_sum_cents plus the sum of change_order_amount_cents over every
        change order on the project now in APPROVED status".

        Design: Difficulty/dual_variant_calc/revised_contract_sum_additive_vs_deductive
        """
        project, sov1, sov2, co = fx.setup_submitted_change_order(
            change_order_amount_cents=150_000,
            line_edits=[{"action": "ADJUST", "item_no": "001",
                         "scheduled_value_delta_cents": 150_000}],
        )
        pv_cur = get_project_version(project["id"])
        resp = api.approve_change_order(
            co["id"], {"expected_project_version": pv_cur}, OWNER
        )
        validate_success(resp, 200)
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        # 1000000 + 150000 = 1150000.
        assert proj["revised_contract_sum_cents"] == 1150000


# ===========================================================================
# Rule: combinatorial_formula
# ===========================================================================
class TestG703RetainageRoundPerLineThenSum:
    """Design: Difficulty/combinatorial_formula/g703_retainage_round_per_line_then_sum_mode_b"""

    def test_total_retainage_rounds_per_line_then_sums(self, api):
        """PRD §2.9: "retainage is rounded to a whole cent per line first, and only then
        are the per-line results summed to form the application total. The system rounds
        each line, then sums; it never sums the raw products and rounds once at the end."

        Design: Difficulty/combinatorial_formula/g703_retainage_round_per_line_then_sum_mode_b
        """
        project = create_project(1000, 0.10, name="Q")
        sov1 = create_sov_line(project["id"], "001", 600, "A")
        sov2 = create_sov_line(project["id"], "002", 400, "B")
        app1 = create_pay_application(project["id"], 1, JAN, project["version"])
        add_pay_app_line(app1["id"], sov1["id"], 125, 0)
        add_pay_app_line(app1["id"], sov2["id"], 125, 0)
        resp = api.submit_pay_application(app1["id"], CONTRACTOR)
        data = validate_success(resp, 200)
        assert data["total_completed_and_stored_cents"] == 250
        # round-per-line: round(0.10*125)=13 twice -> 26 (NOT sum-then-round 25).
        assert data["total_retainage_cents"] == 26
        assert data["current_payment_due_cents"] == 224

    def test_per_line_retainage_is_rounded_half_up(self, api):
        """PRD §3.3: "it applies the linked schedule-of-values line's retainage_pct to the
        sum of work_completed_previous_cents, work_completed_this_period_cents, and
        materials_stored_cents, and rounds that product to a whole cent half-up."

        Design: Difficulty/combinatorial_formula/g703_retainage_round_per_line_then_sum_mode_b
        """
        project = create_project(1000, 0.10, name="QLine")
        sov1 = create_sov_line(project["id"], "001", 600, "A")
        app1 = create_pay_application(project["id"], 1, JAN, project["version"])
        resp = api.create_pay_app_line(
            {"pay_app_id": app1["id"], "sov_line_id": sov1["id"],
             "work_completed_this_period_cents": 125, "materials_stored_cents": 0},
            CONTRACTOR,
        )
        data = validate_success(resp, 201)
        # 0.10 * 125 = 12.5 -> round-half-up -> 13.
        assert data["line_retainage_cents"] == 13


class TestG702CpdThreeInputCertifiedOnlyFilter:
    """Design: Difficulty/combinatorial_formula/g702_cpd_three_input_nonlinear_mode_a"""

    def _project_with_one_rejected_app(self, api):
        project, sov1, sov2 = setup_project_with_two_sov_lines()
        pv1 = project["version"]
        # First app gets REJECTED; its number is freed and it never certifies.
        app_r = create_pay_application(project["id"], 1, JAN, pv1)
        add_pay_app_line(app_r["id"], sov1["id"], 1, 0)
        submit_pay_application(app_r["id"])
        validate_success(api.reject_pay_application(app_r["id"], ARCHITECT), 200)
        return project, sov1, sov2

    def test_cpd_excludes_rejected_app_from_prior_certificates(self, api):
        """PRD §3.4: "the prior-certificates draw is the sum of current_payment_due_cents
        over the project's already-certified applications."

        Design: Difficulty/combinatorial_formula/g702_cpd_three_input_nonlinear_mode_a
        """
        project, sov1, sov2 = self._project_with_one_rejected_app(api)
        pv_cur = get_project_version(project["id"])
        app1 = create_pay_application(project["id"], 1, JAN, pv_cur)
        add_pay_app_line(app1["id"], sov1["id"], 300_000, 0)
        add_pay_app_line(app1["id"], sov2["id"], 100_000, 50_000)
        resp = api.submit_pay_application(app1["id"], CONTRACTOR)
        data = validate_success(resp, 200)
        assert data["total_completed_and_stored_cents"] == 450000
        assert data["total_retainage_cents"] == 45000
        # prior_certificates 0 (the rejected app is excluded) -> 405000.
        assert data["current_payment_due_cents"] == 405000

    def test_rejected_app_frees_application_number_one(self, api):
        """PRD §3.4: "A rejection performs no schedule-of-values or project ledger mutation,
        and the `application_number` it consumed is freed for reuse, because sequencing counts
        only non-rejected applications."

        Design: Difficulty/combinatorial_formula/g702_cpd_three_input_nonlinear_mode_a
        """
        project, sov1, sov2 = self._project_with_one_rejected_app(api)
        pv_cur = get_project_version(project["id"])
        # The next create reuses application_number 1 (freed by the rejection).
        resp = api.create_pay_application(
            {"project_id": project["id"], "application_number": 1,
             "period_from": JAN[0], "period_to": JAN[1],
             "expected_project_version": pv_cur},
            CONTRACTOR,
        )
        data = validate_success(resp, 201)
        assert data["application_number"] == 1
        assert data["status"] == "DRAFT"
