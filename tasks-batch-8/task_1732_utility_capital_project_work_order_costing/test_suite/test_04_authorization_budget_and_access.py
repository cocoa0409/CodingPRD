"""Authorization tiers, program budget enforcement, segregation of duties,
and role-based access control (PRD §2.1, §2.8, §3.3, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_estimate,
    assert_program_budget_invariants,
    create_approved_work_order,
    create_catalog_entry,
    create_period,
    create_program,
    create_reg_asset,
    create_schedule,
    create_submitted_work_order,
    create_unit_catalog_payload,
    create_work_order,
    get_estimate_for_order,
    get_program,
    get_success_data,
    get_work_order,
    make_headers,
    setup_charging_world,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
SUPERVISOR2 = TEST_USERS["supervisor2_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["clerk_headers"]
RATES = TEST_USERS["rates_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAuthorizeBudget:
    def test_program_budget_exceeded_and_exact_fit_boundary(self, api):
        """PRD §3.3: "The referential check follows — an estimate in `APPROVED` must exist, else `ERR_NO_APPROVED_ESTIMATE` — and the fiscal test comes last: the program's `available_amount_cents` must be at least the `approved_estimate_cents`, else `ERR_PROGRAM_BUDGET_EXCEEDED`."
        PRD §3.3: "Throughout these states the program's budget accounting obeys a conservation law: `committed_amount_cents` is the sum of `approved_estimate_cents` over the program's work orders in `AUTHORIZED`, `IN_PROGRESS`, `SUSPENDED`, or `COMPLETED` — a completed order stays committed until its closeout — and `available_amount_cents` is always the authorized amount minus the committed amount."

        Design: Corner/validations/program_budget_exceeded_and_exact_fit_boundary
        """
        program = create_program(code="CAP-BUDG", authorized_amount_cents=500_000)

        wo_a, _ = create_approved_work_order(
            program["id"], title="Too big", initial_estimated_cost_cents=600_000)
        resp = api.authorize_work_order(wo_a["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_BUDGET_EXCEEDED, 422)

        # Exactly equal to available (500,000) passes — "at least" is inclusive.
        wo_b, _ = create_approved_work_order(
            program["id"], title="Exact fit", initial_estimated_cost_cents=500_000)
        authorized = validate_success(api.authorize_work_order(wo_b["id"], SUPERVISOR))
        assert authorized["status"] == "AUTHORIZED"
        program_view = get_program(program["id"])
        assert program_view["committed_amount_cents"] == 500_000
        assert program_view["available_amount_cents"] == 0
        assert_program_budget_invariants(program_view)

    def test_authorize_without_approved_estimate_rejected(self, api):
        """PRD §3.3: "The referential check follows — an estimate in `APPROVED` must exist, else `ERR_NO_APPROVED_ESTIMATE` — and the fiscal test comes last: the program's `available_amount_cents` must be at least the `approved_estimate_cents`, else `ERR_PROGRAM_BUDGET_EXCEEDED`."

        Design: Corner/validations/authorize_without_approved_estimate_rejected
        """
        program = create_program(code="CAP-NOAPP", authorized_amount_cents=50_000_000)
        wo, _est = create_submitted_work_order(
            program["id"], title="Unapproved", initial_estimated_cost_cents=100_000)
        resp = api.authorize_work_order(wo["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_ESTIMATE, 422)


class TestAuthorizeTier:
    def test_authorize_tier_boundary_exact_threshold(self, api):
        """PRD §3.3: "The tier rule comes first: when the `approved_estimate_cents` is strictly below 10,000,000 cents — one hundred thousand dollars — a `WorkOrderSupervisor` may authorize, while at or above that amount only a `Controller` may, and exactly 10,000,000 cents belongs to the `Controller`; a supervisor reaching above the tier is rejected with `ERR_APPROVAL_TIER_REQUIRED`."

        Design: Corner/calculations/authorize_tier_boundary_exact_threshold
        """
        program = create_program(code="CAP-AUTHZ", authorized_amount_cents=50_000_000)
        wo, _est = create_approved_work_order(
            program["id"], title="Big order",
            initial_estimated_cost_cents=10_000_000)

        # Exactly 10,000,000 is not strictly below the threshold: Supervisor out.
        resp = api.authorize_work_order(wo["id"], SUPERVISOR2)
        validate_error(resp, ApiErrorId.ERR_APPROVAL_TIER_REQUIRED, 403)

        authorized = validate_success(api.authorize_work_order(wo["id"], CONTROLLER))
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["authorized_by_user_id"] == "ctrl-1"
        assert get_program(program["id"])["committed_amount_cents"] == 10_000_000


class TestSegregationOfDuties:
    def test_segregation_of_duties_denials(self, api):
        """PRD §2.8: "8. Segregation of duties — the actor repeats a prior step's actor — `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.3: "Then segregation of duties: the authorizer's `X-User-ID` must differ from the order's `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.4: "Segregation of duties applies to both decisions: the decider's `X-User-ID` must differ from the estimate's `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.7: "Only a `Controller` may decide it, and never the proposer: both approval and rejection require the decider's `X-User-ID` to differ from `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.8: "Segregation of duties comes first among them: the closer's `X-User-ID` must differ from the order's `completed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_denials
        """
        program = create_program(code="CAP-SOD")
        catalog = create_catalog_entry()
        create_period()
        wo, est1 = create_submitted_work_order(program["id"], title="SoD order",
                                               initial_estimated_cost_cents=400_000)
        ra = create_reg_asset(description="SoD deferral", original_cents=5_000,
                              amortization_months=5)

        # The estimate's submitter (eng-1) cannot approve it, even as Controller.
        engineer_as_controller = make_headers("Controller", "eng-1")
        resp = api.approve_estimate(est1["id"], wo["version"],
                                    engineer_as_controller)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        approve_estimate(est1["id"], wo["id"], SUPERVISOR)

        # The work order's creator (eng-1) cannot authorize it, even as a
        # WorkOrderSupervisor.
        engineer_as_supervisor = make_headers("WorkOrderSupervisor", "eng-1")
        resp = api.authorize_work_order(wo["id"], engineer_as_supervisor)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        authorized = get_success_data(api.authorize_work_order(wo["id"], SUPERVISOR))
        assert authorized["status"] == "AUTHORIZED"

        # The regulatory asset's proposer (rates-1) cannot approve it.
        rates_as_controller = make_headers("Controller", "rates-1")
        resp = api.approve_regulatory_asset(ra["id"], rates_as_controller)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        approved_ra = validate_success(api.approve_regulatory_asset(ra["id"], CONTROLLER))
        assert approved_ra["status"] == "APPROVED"

        # The completer (sup-1) cannot close out the same order.
        get_success_data(api.start_work_order(wo["id"], SUPERVISOR))
        completed = get_success_data(
            api.complete_work_order(wo["id"], "2026-08-20", SUPERVISOR))
        assert completed["status"] == "COMPLETED"
        supervisor_as_controller = make_headers("Controller", "sup-1")
        resp = api.closeout_work_order(
            wo["id"], [{"unit_catalog_id": catalog["id"], "quantity": 1}],
            supervisor_as_controller)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        closed = validate_success(api.closeout_work_order(
            wo["id"], [{"unit_catalog_id": catalog["id"], "quantity": 1}],
            CONTROLLER))
        assert closed["status"] == "CLOSED"


class TestRoleDenials:
    def test_rbac_exclusive_operation_denials(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's permitted role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "The `WorkOrderSupervisor` runs field execution — returning, starting, suspending, resuming, cancelling, and completing work orders, authorizing orders whose approved estimate falls below the controller threshold, and deciding estimates within the supervisor routing tier. The `Controller` is the corporate authority: authorizing work orders of any amount, deciding estimates of any tier, closing and reopening accounting periods, closing out work orders, approving or rejecting regulatory assets, retiring fixed-asset units, and closing capital programs. The `FieldClerk` posts and reverses labor, equipment, and material charges. The `RateAnalyst` manages CIAC pledges and receipts and proposes regulatory asset deferrals. The `Auditor` is read-only."

        Design: Corner/rbac/rbac_exclusive_operation_denials
        """
        world = setup_charging_world(estimate_cents=400_000)
        period, wo = world["period"], world["work_order"]
        catalog = create_catalog_entry()
        completed = get_success_data(
            api.complete_work_order(wo["id"], "2026-08-20", SUPERVISOR))
        assert completed["status"] == "COMPLETED"

        # FieldClerk may not authorize.
        resp = api.authorize_work_order(wo["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

        # Auditor may not post charges.
        resp = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 1_000, "charge_date": "2026-08-10"}, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

        # ProjectEngineer may not close a period.
        resp = api.close_accounting_period(period["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

        # WorkOrderSupervisor may not close out.
        resp = api.closeout_work_order(
            wo["id"], [{"unit_catalog_id": catalog["id"], "quantity": 1}],
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

        # RateAnalyst may not create catalog rows.
        resp = api.create_unit_catalog_entry(
            create_unit_catalog_payload(asset_class="POLE",
                                        standard_cost_cents=10_000,
                                        annual_depreciation_rate_pct=4.0), RATES)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestAuthorizeCancelBudgetInvariant:
    def test_authorize_commits_budget(self, api):
        """PRD §3.3: "On success the program's `committed_amount_cents` increases by the approved estimate, `authorized_by_user_id` records the authorizer, the order's `variance_posture` is re-derived against the newly committed estimate per the rule of §3.5, and the order's `version` increments by one."
        PRD §3.3: "Throughout these states the program's budget accounting obeys a conservation law: `committed_amount_cents` is the sum of `approved_estimate_cents` over the program's work orders in `AUTHORIZED`, `IN_PROGRESS`, `SUSPENDED`, or `COMPLETED` — a completed order stays committed until its closeout — and `available_amount_cents` is always the authorized amount minus the committed amount."

        Design: Difficulty/compensating_invariant/authorize_cancel_conserves_committed_budget
        """
        program = create_program(code="CAP-INV2", authorized_amount_cents=500_000)
        before = get_program(program["id"])
        assert before["committed_amount_cents"] == 0
        assert before["available_amount_cents"] == 500_000

        wo, _ = create_approved_work_order(
            program["id"], title="Budget invariant order",
            initial_estimated_cost_cents=400_000)
        # Approval alone does not commit budget: the order is only SUBMITTED.
        assert get_program(program["id"])["committed_amount_cents"] == 0

        authorized = validate_success(api.authorize_work_order(wo["id"], SUPERVISOR))
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["authorized_by_user_id"] == "sup-1"

        mid = get_program(program["id"])
        assert mid["committed_amount_cents"] == 400_000
        assert mid["available_amount_cents"] == 100_000
        assert_program_budget_invariants(mid)

    def test_cancel_releases_committed_budget(self, api):
        """PRD §3.3: "Authorizing and then cancelling (or closing out) the same order therefore leaves the program's commitment identical to its pre-authorization value."
        PRD §3.7: "From `AUTHORIZED` the consequences deepen. The committed budget is released — the program's `committed_amount_cents` decreases by the order's `approved_estimate_cents` — and whenever the order's `cwip_cents` is greater than zero, the cancellation request must carry a `writeoff_disposition`, else it is rejected with `ERR_WRITEOFF_DISPOSITION_REQUIRED` (HTTP 400); choosing `REGULATORY_DEFERRAL` additionally requires a `writeoff_amortization_months` term."

        Design: Difficulty/compensating_invariant/authorize_cancel_conserves_committed_budget
        """
        program = create_program(code="CAP-INV2B", authorized_amount_cents=500_000)
        wo, _ = create_approved_work_order(
            program["id"], title="Budget invariant order",
            initial_estimated_cost_cents=400_000)
        get_success_data(api.authorize_work_order(wo["id"], SUPERVISOR))
        assert get_program(program["id"])["committed_amount_cents"] == 400_000

        # Zero CWIP: no writeoff_disposition is required.
        cancelled = validate_success(api.cancel_work_order(wo["id"], SUPERVISOR))
        assert cancelled["status"] == "CANCELLED"

        after = get_program(program["id"])
        assert after["committed_amount_cents"] == 0
        assert after["available_amount_cents"] == 500_000
        assert_program_budget_invariants(after)
