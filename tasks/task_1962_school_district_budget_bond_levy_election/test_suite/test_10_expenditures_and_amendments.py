"""Project execution: expenditures with their parallel review/payment
dimensions, retainage, project completion, and capital-plan amendments
(PRD §3.9)."""
from test_helpers import (
    ApiErrorId, assert_money, get_success_data, validate_error,
    validate_paginated, validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    amendment_adjustment, create_amendment_payload, create_expenditure_payload,
    review_payload,
)
from test_helpers.fixtures import (
    APPROVER_USER_ID, SUBMITTER_USER_ID, activate_project, add_project,
    approve_amendment, approve_board, create_amendment, create_bond_proposal,
    create_bond_sale, create_expenditure, set_clock, submit_amendment,
    setup_closed_sale, setup_passed_proposal, setup_project_in_progress,
)
from test_helpers.test_users import (
    TEST_USERS, make_budget_analyst_headers, make_superintendent_headers,
)

BM = TEST_USERS["business_manager_headers"]
SU = TEST_USERS["superintendent_headers"]
DT = TEST_USERS["district_treasurer_headers"]
AU = TEST_USERS["auditor_headers"]

ONE_PROJECT = [("Roof Replacement", "HS-01", 6000000, "2028-06-01",
                "2028-08-15")]
THREE_PROJECTS = [
    ("Roof Replacement", "HS-01", 6000000, "2028-06-01", "2028-08-15"),
    ("HVAC Replacement", "HS-01", 5000000, "2028-09-01", "2028-11-30"),
    ("Gym Renovation", "ES-02", 7000000, "2028-06-01", "2028-12-15"),
]


class TestReviewAndPaymentDimensions:
    def test_disburse_gated_on_review_and_review_cycles(self, api):
        """PRD §3.9: "Only a `REVIEWED` expenditure may be paid: disbursement
        against any other review state fails with
        `ERR_EXPENDITURE_NOT_REVIEWED`." and "A verdict of true moves
        `PENDING_REVIEW` → `REVIEWED`, and also rehabilitates a `FLAGGED`
        expenditure to `REVIEWED` on re-review; a verdict of false moves
        `PENDING_REVIEW` → `FLAGGED`."

        Design: Difficulty/non_linear_state_machine/expenditure_parallel_review_and_payment_dimensions
        """
        ctx = setup_project_in_progress()
        prj_id = ctx["projects"][0]["id"]
        ex = create_expenditure(prj_id, amount=100000,
                                description="tear-off and disposal")
        assert ex["review_status"] == "PENDING_REVIEW"
        assert ex["payment_status"] == "UNPAID"
        # Payment dimension is gated on the review dimension.
        resp = api.disburse_expenditure(ex["id"], DT)
        validate_error(resp, ApiErrorId.ERR_EXPENDITURE_NOT_REVIEWED, 409)
        # Review dimension cycles while payment stays UNPAID.
        flagged = validate_success(
            api.review_expenditure(ex["id"], review_payload(False), BM), 200)
        assert flagged["review_status"] == "FLAGGED"
        assert flagged["payment_status"] == "UNPAID"
        reviewed = validate_success(
            api.review_expenditure(ex["id"], review_payload(True), BM), 200)
        assert reviewed["review_status"] == "REVIEWED"
        assert reviewed["payment_status"] == "UNPAID"

    def test_disburse_then_review_rejected(self, api):
        """PRD §3.9: "Disbursement by the `DistrictTreasurer` moves the
        payment `UNPAID` → `DISBURSED`, withholds a retainage of ten percent —
        `retainage_amount` is the `amount` multiplied by 0.10, rounded half-up
        to two decimal places — and pays out the remainder as
        `disbursed_amount`" and "review of an expenditure whose
        `payment_status` is not `UNPAID` fails with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/expenditure_parallel_review_and_payment_dimensions
        """
        ctx = setup_project_in_progress()
        prj_id = ctx["projects"][0]["id"]
        ex = create_expenditure(prj_id, amount=100000,
                                description="tear-off and disposal")
        get_success_data(api.review_expenditure(ex["id"],
                                                review_payload(True), BM))
        disbursed = validate_success(api.disburse_expenditure(ex["id"], DT),
                                     200)
        assert disbursed["payment_status"] == "DISBURSED"
        assert_money(disbursed["retainage_amount"], 10000.00, "retainage")
        assert_money(disbursed["disbursed_amount"], 90000.00, "disbursed")
        # Review transitions require payment UNPAID: after disbursement the
        # review flip is rejected.
        resp = api.review_expenditure(ex["id"], review_payload(False), BM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestProceedsInvariant:
    def test_post_debits_available_proceeds(self, api):
        """PRD §3.9: "A posted expenditure starts with `review_status` in
        `PENDING_REVIEW` and `payment_status` in `UNPAID`, with
        `retainage_amount` and `disbursed_amount` both zero while unpaid;
        posting immediately adds the `amount` to the project's `spent_amount`
        and subtracts it from the proposal's `available_proceeds`."

        Design: Difficulty/compensating_invariant/expenditure_post_and_void_conserves_available_proceeds
        """
        ctx = setup_project_in_progress()  # one CLOSED sale, net 10,070,000
        bp_id = ctx["bp"]["id"]
        prj_id = ctx["projects"][0]["id"]
        bp = validate_success(api.get_bond_proposal(bp_id, AU), 200)
        assert_money(bp["available_proceeds"], 10070000.00, "baseline pool")
        create_expenditure(prj_id, amount=1000000, description="roof tear-off")
        bp = validate_success(api.get_bond_proposal(bp_id, AU), 200)
        assert_money(bp["available_proceeds"], 9070000.00, "pool after post")
        prj = validate_success(api.get_bond_project(prj_id, AU), 200)
        assert_money(prj["spent_amount"], 1000000.00, "spent after post")

    def test_void_restores_available_proceeds_exactly(self, api):
        """PRD §3.9: "voiding moves the payment to `VOIDED`, compensates the
        ledgers by subtracting the `amount` from the project's `spent_amount`
        and adding it back to the proposal's `available_proceeds`, resets
        `retainage_amount` and `disbursed_amount` to zero when the expenditure
        had been disbursed".

        Design: Difficulty/compensating_invariant/expenditure_post_and_void_conserves_available_proceeds
        """
        ctx = setup_project_in_progress()
        bp_id = ctx["bp"]["id"]
        prj_id = ctx["projects"][0]["id"]
        ex = create_expenditure(prj_id, amount=1000000,
                                description="roof tear-off")
        voided = validate_success(api.void_expenditure(ex["id"], DT), 200)
        assert voided["payment_status"] == "VOIDED"
        bp = validate_success(api.get_bond_proposal(bp_id, AU), 200)
        assert_money(bp["available_proceeds"], 10070000.00,
                     "pool after compensating void")
        prj = validate_success(api.get_bond_project(prj_id, AU), 200)
        assert_money(prj["spent_amount"], 0.00, "spent after void")


class TestProjectExecutionGates:
    def test_activate_project_without_closed_sale_rejected(self, api):
        """PRD §3.9: "With bond proceeds in hand, the `Superintendent`
        activates a project — `AUTHORIZED` → `IN_PROGRESS` — which requires at
        least one `CLOSED` bond sale on the owning proposal, failing otherwise
        with `ERR_NO_CLOSED_BOND_SALE`".

        Design: Corner/validations/activate_project_without_closed_sale_rejected
        """
        ctx = setup_passed_proposal()
        # The sale exists but is PLANNED, not CLOSED.
        create_bond_sale(ctx["bp"]["id"], "2027-A", 10000000, 150000, 80000,
                         "2027-12-01")
        prj = ctx["projects"][0]
        resp = api.activate_bond_project(prj["id"], SU)
        validate_error(resp, ApiErrorId.ERR_NO_CLOSED_BOND_SALE, 409)
        prj_now = validate_success(api.get_bond_project(prj["id"], AU), 200)
        assert prj_now["status"] == "AUTHORIZED"

    def test_expenditure_on_authorized_not_in_progress_project_rejected(
            self, api):
        """PRD §3.9: "Construction accounting happens through **project
        expenditures**, which the `DistrictTreasurer` posts against an
        `IN_PROGRESS` project — any other project state fails with
        `ERR_INVALID_STATE`".

        Design: Corner/validations/expenditure_on_authorized_not_in_progress_project_rejected
        """
        ctx = setup_passed_proposal()  # project AUTHORIZED, never activated
        prj = ctx["projects"][0]
        resp = api.create_expenditure(
            prj["id"],
            create_expenditure_payload("Roofing Co", 1000, "mobilization"),
            DT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_expenditure_at_exact_available_budget_then_over_rejected(
            self, api):
        """PRD §3.9: "Two fiscal guards apply, both permitting exact equality:
        the `amount` may not exceed the project's available budget — its
        `authorized_amount` minus its `spent_amount` — failing with
        `ERR_PROJECT_BUDGET_EXCEEDED`".

        Design: Corner/validations/expenditure_at_exact_available_budget_allowed_then_over_rejected
        """
        ctx = setup_project_in_progress(par_amount=18000000, premium=0,
                                        issuance_costs=0)
        prj_id = ctx["projects"][0]["id"]  # authorized 6,000,000
        create_expenditure(prj_id, amount=1000000, description="roof tear-off")
        # Remaining budget is exactly 5,000,000: exact equality is allowed.
        create_expenditure(prj_id, amount=5000000,
                           description="roof installation")
        # One cent over the 6,000,000 authorization: rejected.
        resp = api.create_expenditure(
            prj_id,
            create_expenditure_payload("Roofing Co", 0.01, "one cent over"),
            DT)
        validate_error(resp, ApiErrorId.ERR_PROJECT_BUDGET_EXCEEDED, 422)
        prj = validate_success(api.get_bond_project(prj_id, AU), 200)
        assert_money(prj["spent_amount"], 6000000.00, "spent after rejection")

    def test_expenditure_beyond_available_proceeds_rejected(self, api):
        """PRD §3.9: "it may not exceed the proposal's `available_proceeds`,
        failing with `ERR_INSUFFICIENT_PROCEEDS`."

        Design: Corner/validations/expenditure_beyond_available_proceeds_rejected
        """
        # Only 1,000,000 of closed proceeds; the project budget (6,000,000)
        # would allow the spend, so the proceeds pool is the binding gate.
        ctx = setup_project_in_progress(par_amount=1000000, premium=0,
                                        issuance_costs=0)
        prj_id = ctx["projects"][0]["id"]
        resp = api.create_expenditure(
            prj_id,
            create_expenditure_payload("Roofing Co", 2000000,
                                       "roof tear-off"),
            DT)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PROCEEDS, 422)

    def test_complete_project_with_unreviewed_then_release_retainage(
            self, api):
        """PRD §3.9: "The `Superintendent`'s completion of an `IN_PROGRESS`
        project requires that no expenditure of the project remain in
        `PENDING_REVIEW` or `FLAGGED` with a `payment_status` other than
        `VOIDED` — unreviewed work blocks the close with
        `ERR_UNREVIEWED_EXPENDITURES_EXIST`. Completion moves the project to
        `COMPLETED`, releases every `DISBURSED` expenditure's retainage by
        moving it to `RETAINAGE_RELEASED`".

        Design: Corner/validations/complete_project_with_unreviewed_expenditure_then_release_retainage
        """
        ctx = setup_project_in_progress()
        prj_id = ctx["projects"][0]["id"]
        ex = create_expenditure(prj_id, amount=1000000,
                                description="roof tear-off")
        # PENDING_REVIEW blocks completion.
        resp = api.complete_bond_project(prj_id, SU)
        validate_error(resp, ApiErrorId.ERR_UNREVIEWED_EXPENDITURES_EXIST, 409)
        # Review, disburse, then complete: retainage is released.
        get_success_data(api.review_expenditure(ex["id"],
                                                review_payload(True), BM))
        get_success_data(api.disburse_expenditure(ex["id"], DT))
        completed = validate_success(api.complete_bond_project(prj_id, SU),
                                     200)
        assert completed["status"] == "COMPLETED"
        expenditures, _ = validate_paginated(api.list_expenditures(prj_id, AU))
        assert expenditures[0]["payment_status"] == "RETAINAGE_RELEASED"


class TestAmendmentLifecycle:
    def test_reject_revise_resubmit_loop(self, api):
        """PRD §3.9: "Rejection moves a `SUBMITTED` amendment to `REJECTED`
        with a version increment, and a rejected amendment may be returned
        `REJECTED` → `DRAFT` for revision, which clears `submitted_by_user_id`
        back to null and increments the `version` once more." and "Submission
        by the analyst moves it `DRAFT` → `SUBMITTED`, records the submitting
        operator in `submitted_by_user_id`".

        Design: Difficulty/non_linear_state_machine/capital_plan_amendment_reject_revise_resubmit_loop
        """
        ctx = setup_passed_proposal(projects=THREE_PROJECTS)
        p2, p3 = ctx["projects"][1]["id"], ctx["projects"][2]["id"]
        ca = create_amendment(ctx["bp"]["id"], [
            amendment_adjustment(p2, -1000000),
            amendment_adjustment(p3, 1000000)],
            reason="Reallocate HVAC savings to gym")
        ca = submit_amendment(ca["id"], "analyst-7")
        assert ca["status"] == "SUBMITTED"
        assert ca["submitted_by_user_id"] == "analyst-7"
        rejected = validate_success(api.reject_amendment(ca["id"], SU), 200)
        assert rejected["status"] == "REJECTED"
        revised = validate_success(api.revise_amendment(
            ca["id"], make_budget_analyst_headers("analyst-7")), 200)
        assert revised["status"] == "DRAFT"
        assert revised["submitted_by_user_id"] is None
        resubmitted = validate_success(api.submit_amendment(
            ca["id"], make_budget_analyst_headers("analyst-8")), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submitted_by_user_id"] == "analyst-8"
        approved = approve_amendment(ca["id"], "supt-9")
        assert approved["status"] == "APPROVED"

    def test_deltas_apply_once_at_approval(self, api):
        """PRD §3.9: "Approval applies each delta to its project's
        `authorized_amount`, moves the amendment `SUBMITTED` → `APPROVED`, and
        increments its `version`." — the rejected pass leaves the project
        authorizations untouched; the deltas land exactly once, at approval.

        Design: Difficulty/non_linear_state_machine/capital_plan_amendment_reject_revise_resubmit_loop
        """
        ctx = setup_passed_proposal(projects=THREE_PROJECTS)
        bp_id = ctx["bp"]["id"]
        p1, p2, p3 = (p["id"] for p in ctx["projects"])
        ca = create_amendment(bp_id, [amendment_adjustment(p2, -1000000),
                                      amendment_adjustment(p3, 1000000)],
                              reason="Reallocate HVAC savings to gym")
        ca = submit_amendment(ca["id"], "analyst-7")
        get_success_data(api.reject_amendment(ca["id"], SU))
        # The rejected pass applied nothing.
        projects, _ = validate_paginated(api.list_bond_projects(bp_id, AU))
        by_id = {p["id"]: p for p in projects}
        assert_money(by_id[p2]["authorized_amount"], 5000000.00)
        assert_money(by_id[p3]["authorized_amount"], 7000000.00)
        get_success_data(api.revise_amendment(
            ca["id"], make_budget_analyst_headers("analyst-7")))
        get_success_data(api.submit_amendment(
            ca["id"], make_budget_analyst_headers("analyst-8")))
        validate_success(api.approve_amendment(
            ca["id"], make_superintendent_headers("supt-9")), 200)
        projects, _ = validate_paginated(api.list_bond_projects(bp_id, AU))
        by_id = {p["id"]: p for p in projects}
        assert_money(by_id[p1]["authorized_amount"], 6000000.00)
        assert_money(by_id[p2]["authorized_amount"], 4000000.00)
        assert_money(by_id[p3]["authorized_amount"], 8000000.00)
        total = sum(p["authorized_amount"] for p in projects)
        assert_money(total, 18000000.00, "proposal total conserved")


class TestAmendmentGates:
    def test_amendment_below_spent_rejected(self, api):
        """PRD §3.9: "Then the floors: for every adjusted project, the
        resulting `authorized_amount` after applying the `delta_authorized`
        must not fall below the project's `spent_amount` — landing exactly on
        it is permitted — failing with `ERR_AMENDMENT_BELOW_SPENT`."

        Design: Corner/validations/amendment_below_spent_rejected
        """
        ctx = setup_project_in_progress()
        prj = ctx["projects"][0]  # authorized 6,000,000
        create_expenditure(prj["id"], amount=1000000,
                           description="roof tear-off")  # spent 1,000,000
        ca = create_amendment(ctx["bp"]["id"], [
            amendment_adjustment(prj["id"], -5500000)], reason="Cut roof scope")
        ca = submit_amendment(ca["id"], SUBMITTER_USER_ID)
        # New authorized 500,000 < spent 1,000,000: rejected at approval.
        resp = api.approve_amendment(
            ca["id"], make_superintendent_headers(APPROVER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_BELOW_SPENT, 422)
        prj_now = validate_success(api.get_bond_project(prj["id"], AU), 200)
        assert_money(prj_now["authorized_amount"], 6000000.00,
                     "authorized_amount unchanged after rejection")

    def test_amendment_exceeds_total_authorization_rejected(self, api):
        """PRD §3.9: "Finally the ceiling: the summed `authorized_amount` over
        all of the proposal's non-`CANCELLED` projects after the deltas must
        not exceed the proposal's `total_amount`, failing with
        `ERR_AMENDMENT_EXCEEDS_AUTHORIZATION`."

        Design: Corner/validations/amendment_exceeds_total_authorization_rejected
        """
        ctx = setup_passed_proposal(projects=THREE_PROJECTS)
        p3 = ctx["projects"][2]["id"]
        ca = create_amendment(ctx["bp"]["id"], [
            amendment_adjustment(p3, 1000000)], reason="Grow gym scope")
        ca = submit_amendment(ca["id"], SUBMITTER_USER_ID)
        # 6M + 5M + 8M = 19M > 18M total: rejected.
        resp = api.approve_amendment(
            ca["id"], make_superintendent_headers(APPROVER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_EXCEEDS_AUTHORIZATION,
                       422)
        projects, _ = validate_paginated(
            api.list_bond_projects(ctx["bp"]["id"], AU))
        assert sorted(p["authorized_amount"] for p in projects) == [
            5000000, 6000000, 7000000]

    def test_amendment_referencing_other_proposals_project_rejected(self, api):
        """PRD §3.9: "Ownership next: every adjustment must reference a
        project of the amendment's own proposal, failing with
        `ERR_AMENDMENT_PROJECT_MISMATCH`."

        Design: Corner/validations/amendment_referencing_other_proposals_project_rejected
        """
        ctx = setup_passed_proposal(
            total_amount=1000000,
            projects=[("Roof", "HS-01", 1000000, "2028-06-01", "2028-08-15")])
        fy_id = ctx["fy"]["id"]
        bp_b = create_bond_proposal(fy_id, total_amount=2000000,
                                    question_title="Bond Question B",
                                    purpose="HVAC")
        prj_b = add_project(bp_b["id"], "HVAC", "ES-02", 2000000,
                            "2028-06-01", "2028-08-15", 1)
        # The amendment is drafted on proposal A but references B's project.
        ca = create_amendment(ctx["bp"]["id"], [
            amendment_adjustment(prj_b["id"], -100000)],
            reason="Move funds from B's project")
        ca = submit_amendment(ca["id"], SUBMITTER_USER_ID)
        resp = api.approve_amendment(
            ca["id"], make_superintendent_headers(APPROVER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_PROJECT_MISMATCH, 422)

    def test_amendment_approve_by_submitter_rejected_sod(self, api):
        """PRD §3.9: "Segregation of duties first: the approver's `X-User-ID`
        must differ from `submitted_by_user_id`, and self-approval is refused
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/amendment_approve_by_submitter_rejected_segregation_of_duties
        """
        ctx = setup_passed_proposal(projects=THREE_PROJECTS)
        p2, p3 = ctx["projects"][1]["id"], ctx["projects"][2]["id"]
        ca = create_amendment(ctx["bp"]["id"], [
            amendment_adjustment(p2, -1000000),
            amendment_adjustment(p3, 1000000)],
            reason="Reallocate HVAC savings to gym")
        ca = submit_amendment(ca["id"], "user-x")
        # The same operator id approving (as Superintendent) self-approves.
        resp = api.approve_amendment(
            ca["id"], make_superintendent_headers("user-x"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        amendments, _ = validate_paginated(
            api.list_amendments(ctx["bp"]["id"], AU))
        assert amendments[0]["status"] == "SUBMITTED"
