"""Budget plans: allocation math, residual fold, rebalance invariant, OCC,
segregation of duties, supersede-by-create, percent-sum validation, period
mismatch on release, terminated-client gate, plan-not-approved gate."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, make_admin_headers, make_financial_officer_headers,
    make_case_manager_headers,
    create_active_client, create_account, create_active_bond,
    create_and_post_deposit, create_budget_plan_for_client,
    create_approved_budget_plan, create_disbursement,
    create_approved_disbursement, set_clock,
    create_budget_plan_payload, allocated_amount,
    assert_budget_allocation_invariant,
)
from test_helpers.api_client import api_client as api

ADMIN = make_admin_headers()
FO = make_financial_officer_headers()
CM = make_case_manager_headers()


class TestAllocationMath:
    def test_budget_allocation_per_line_rounding_residual_fold(self, api):
        """PRD §3.4: "Allocation is computed once, at creation. Each line's
        planned amount is `source_benefit_cents` multiplied by the line's
        `percent` and divided by one hundred, rounded half-up to whole cents
        per line. Per-line rounding can drift from the basis, so the residual —
        `source_benefit_cents` minus the sum of the rounded line amounts, which
        may be negative — is folded into the `HOUSING` line when the plan has
        one, and otherwise into the first line in the canonical category order
        `HOUSING`, `FOOD`, `CLOTHING`, `PERSONAL`, `MEDICAL`, `EDUCATION`,
        `SAVINGS`. The result is stored as `allocated_lines`, and the invariant
        holds at all times: the per-line amounts always sum to
        `total_planned_cents`, which always equals `source_benefit_cents`."

        Design: Difficulty/combinatorial_formula/budget_allocation_per_line_rounding_residual_fold
        """
        set_clock("2026-06-01T00:00:00Z")
        client, ent = create_active_client(monthly_benefit_cents=100001)
        create_account(client["id"])
        plan = create_budget_plan_for_client(
            client["id"], period_month="2026-06", source_benefit_cents=100001,
            lines=[
                {"category": "HOUSING", "percent": 33},
                {"category": "FOOD", "percent": 33},
                {"category": "SAVINGS", "percent": 34},
            ],
        )
        assert allocated_amount(plan, "HOUSING") == 33001
        assert allocated_amount(plan, "FOOD") == 33000
        assert allocated_amount(plan, "SAVINGS") == 34000
        assert plan["total_planned_cents"] == 100001
        assert_budget_allocation_invariant(plan)

    def test_budget_allocation_residual_folds_into_first_line_without_housing(self, api):
        """PRD §3.4: "Per-line rounding can drift from the basis, so the
        residual — `source_benefit_cents` minus the sum of the rounded line
        amounts, which may be negative — is folded into the `HOUSING` line when
        the plan has one, and otherwise into the first line in the canonical
        category order `HOUSING`, `FOOD`, `CLOTHING`, `PERSONAL`, `MEDICAL`,
        `EDUCATION`, `SAVINGS`."

        Design: Difficulty/combinatorial_formula/budget_allocation_per_line_rounding_residual_fold
        """
        set_clock("2026-06-01T00:00:00Z")
        client, ent = create_active_client(monthly_benefit_cents=100001)
        create_account(client["id"])
        # No HOUSING line: residual -1 (100001 - 33334 - 33334 - 33334 = -1)
        # folds into FOOD, the first line in canonical order among the lines.
        plan = create_budget_plan_for_client(
            client["id"], period_month="2026-06", source_benefit_cents=100001,
            lines=[
                {"category": "FOOD", "percent": 34},
                {"category": "CLOTHING", "percent": 33},
                {"category": "SAVINGS", "percent": 33},
            ],
        )
        # round_half_up(100001*34/100)=34000 (34000.34->34000)
        # round_half_up(100001*33/100)=33000 (33000.33->33000)
        # residual = 100001 - (34000+33000+33000) = 1 -> FOOD gets 34001
        assert allocated_amount(plan, "FOOD") == 34001
        assert allocated_amount(plan, "CLOTHING") == 33000
        assert allocated_amount(plan, "SAVINGS") == 33000
        assert plan["total_planned_cents"] == 100001
        assert_budget_allocation_invariant(plan)


class TestRebalanceInvariant:
    def test_rebalance_conserves_allocation_total(self, api):
        """PRD §3.4: "Rebalancing is the one edit allowed on a live plan: in
        either `DRAFT` or `APPROVED`, a case manager may move `amount_cents`
        from one allocated line named `from_category` to another named
        `to_category`, decreasing the source line and increasing the
        destination line by the same amount so `total_planned_cents` is
        conserved, and advancing the plan's `version` by one."

        Design: Difficulty/compensating_invariant/rebalance_conserves_allocation_total
        """
        set_clock("2026-06-01T00:00:00Z")
        client, ent = create_active_client(monthly_benefit_cents=100001)
        plan = create_budget_plan_for_client(
            client["id"], period_month="2026-06", source_benefit_cents=100001,
            lines=[
                {"category": "HOUSING", "percent": 33},
                {"category": "FOOD", "percent": 33},
                {"category": "SAVINGS", "percent": 34},
            ],
        )
        assert plan["total_planned_cents"] == 100001
        resp = api.rebalance_budget_plan(
            plan["id"],
            {"from_category": "HOUSING", "to_category": "FOOD", "amount_cents": 5000},
            CM,
        )
        after = validate_success(resp, expected_status=200)
        assert after["total_planned_cents"] == 100001
        assert allocated_amount(after, "HOUSING") == 28001
        assert allocated_amount(after, "FOOD") == 38000
        assert allocated_amount(after, "SAVINGS") == 34000
        assert_budget_allocation_invariant(after)

    def test_rebalance_advances_plan_version(self, api):
        """PRD §3.4: "Rebalancing is the one edit allowed on a live plan: in
        either `DRAFT` or `APPROVED`, a case manager may move `amount_cents`
        from one allocated line named `from_category` to another named
        `to_category`, decreasing the source line and increasing the
        destination line by the same amount so `total_planned_cents` is
        conserved, and advancing the plan's `version` by one."

        Design: Difficulty/compensating_invariant/rebalance_conserves_allocation_total
        """
        set_clock("2026-06-01T00:00:00Z")
        client, ent = create_active_client()
        plan = create_budget_plan_for_client(
            client["id"], period_month="2026-06", source_benefit_cents=100000,
            lines=[
                {"category": "HOUSING", "percent": 50},
                {"category": "FOOD", "percent": 50},
            ],
        )
        before_version = plan["version"]
        resp = api.rebalance_budget_plan(
            plan["id"],
            {"from_category": "HOUSING", "to_category": "FOOD", "amount_cents": 1000},
            CM,
        )
        after = validate_success(resp, expected_status=200)
        assert after["version"] == before_version + 1


class TestBudgetCreateValidation:
    def test_budget_create_percent_sum_invalid_returns_invalid_request(self, api):
        """PRD §3.4: "The percents must sum to exactly 100, categories must be
        unique within the plan, and the category vocabulary is `HOUSING`,
        `FOOD`, `CLOTHING`, `PERSONAL`, `MEDICAL`, `EDUCATION`, `SAVINGS`."

        Design: Corner/entities/budget_create_percent_sum_invalid_returns_invalid_request
        """
        client, ent = create_active_client()
        fresh = get_success_data(api.get_client(client["id"], ADMIN))
        resp = api.create_budget_plan(
            create_budget_plan_payload(
                client_id=client["id"], period_month="2026-06",
                source_benefit_cents=100000,
                lines=[
                    {"category": "HOUSING", "percent": 50},
                    {"category": "FOOD", "percent": 40},
                ],
                expected_client_version=fresh["version"],
            ),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_terminated_client_budget_create_rejected(self, api):
        """PRD §3.4: "The create also requires the client to be in any status
        other than `TERMINATED` — drafting against a terminated client fails
        with `ERR_CLIENT_NOT_ACTIVE`."
        PRD §2.9: "Stage seven is the client-activity gate
        (`ERR_CLIENT_NOT_ACTIVE`, HTTP 409), whose per-endpoint status
        requirements are given in §3."

        Design: Corner/validations/intake_client_budget_create_rejected
        """
        client, ent = create_active_client()
        get_success_data(api.terminate_client(client["id"], ADMIN))
        fresh = get_success_data(api.get_client(client["id"], ADMIN))
        assert fresh["status"] == "TERMINATED"
        resp = api.create_budget_plan(
            create_budget_plan_payload(
                client_id=client["id"], period_month="2026-06",
                source_benefit_cents=100000,
                lines=[{"category": "HOUSING", "percent": 100}],
                expected_client_version=fresh["version"],
            ),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE)


class TestOptimisticConcurrency:
    def test_occ_stale_version_rejected_and_fresh_accepted(self, api):
        """PRD §2.8: "A request to create a budget plan must carry
        `expected_client_version`, the `version` of the owning client as last
        observed by the caller. If the client's current `version` has advanced
        since that observation — for example because another writer created a
        superseding plan, or a lifecycle action bumped the client — the create
        is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a writer
        holding stale client state from blindly superseding a plan it never
        saw."
        PRD §3.4: "A successful create stamps `created_by_user_id` from the
        requester's `X-User-ID`, marks any existing non-`SUPERSEDED` plan for
        the same client and `period_month` as `SUPERSEDED` with
        `superseded_by_plan_id` pointing at the new plan, advances the client's
        `version`, and freezes the allocation math described next."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_and_fresh_accepted
        """
        client, ent = create_active_client()
        v_stale = get_success_data(api.get_client(client["id"], ADMIN))["version"]
        p1 = create_budget_plan_for_client(client["id"], period_month="2026-06",
                                           source_benefit_cents=100000)
        # Stale create (same period, old version) is rejected with 412.
        resp = api.create_budget_plan(
            create_budget_plan_payload(
                client_id=client["id"], period_month="2026-06",
                source_benefit_cents=120000,
                lines=[{"category": "HOUSING", "percent": 100}],
                expected_client_version=v_stale,
            ),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Fresh read, then create succeeds and supersedes p1.
        v_fresh = get_success_data(api.get_client(client["id"], ADMIN))["version"]
        assert v_fresh == v_stale + 1
        p2 = get_success_data(api.create_budget_plan(
            create_budget_plan_payload(
                client_id=client["id"], period_month="2026-06",
                source_benefit_cents=120000,
                lines=[{"category": "HOUSING", "percent": 100}],
                expected_client_version=v_fresh,
            ),
            CM,
        ))
        p1_after = get_success_data(api.get_budget_plan(p1["id"], CM))
        assert p1_after["status"] == "SUPERSEDED"
        assert p1_after["superseded_by_plan_id"] == p2["id"]


class TestBudgetSegregationOfDuties:
    def test_sod_budget_approve_same_user_rejected(self, api):
        """PRD §3.4: "Approval enforces segregation of duties: the approver's
        `X-User-ID` must differ from the plan's `created_by_user_id`, and a
        self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_budget_approve_same_user_rejected
        """
        client, ent = create_active_client()
        plan = create_budget_plan_for_client(client["id"], period_month="2026-06",
                                             as_user_id="shared-1")
        plan = get_success_data(
            api.propose_budget_plan(plan["id"], make_case_manager_headers("shared-1"))
        )
        resp = api.approve_budget_plan(plan["id"], make_financial_officer_headers("shared-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api.get_budget_plan(plan["id"], CM))
        assert after["status"] == "PROPOSED"


class TestPlanGatesOnRelease:
    def test_plan_period_mismatch_on_release(self, api):
        """PRD §3.6: "Fourth, the referenced plan's `period_month` must equal
        the calendar month of the current logical clock date, failing with
        `ERR_PLAN_PERIOD_MISMATCH`."

        Design: Corner/validations/plan_period_mismatch_on_release
        """
        set_clock("2026-06-10T00:00:00Z")
        client, ent = create_active_client()
        account = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(account["id"], 50000, received_date="2026-06-05")
        plan = create_approved_budget_plan(client["id"], period_month="2026-06")
        d = create_approved_disbursement(client["id"], account["id"], plan["id"],
                                         amount_cents=10000)
        set_clock("2026-07-02T00:00:00Z")
        resp = api.release_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_PLAN_PERIOD_MISMATCH)

    def test_plan_not_approved_on_release(self, api):
        """PRD §3.6: "Fifth, that plan must be `APPROVED`, failing with
        `ERR_PLAN_NOT_APPROVED`."

        Design: Corner/validations/plan_not_approved_on_release
        """
        set_clock("2026-06-10T00:00:00Z")
        client, ent = create_active_client()
        account = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(account["id"], 50000, received_date="2026-06-05")
        plan = create_budget_plan_for_client(client["id"], period_month="2026-06")
        plan = get_success_data(api.propose_budget_plan(plan["id"], CM))
        d = create_approved_disbursement(client["id"], account["id"], plan["id"],
                                         amount_cents=10000)
        resp = api.release_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_APPROVED)
