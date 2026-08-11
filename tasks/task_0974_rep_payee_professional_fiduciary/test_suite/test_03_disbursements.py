"""Disbursements: approval pipeline, conservator fork-join, release gates,
fiduciary fee math, returns, invalid transitions, terminal lockdown."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, is_valid_uuid,
    ApiErrorId, make_admin_headers, make_financial_officer_headers,
    make_case_manager_headers, make_conservator_headers,
    create_client, create_active_client, create_client_with_verified_entitlement,
    create_account, create_active_bond, create_and_post_deposit,
    create_budget_plan_for_client, create_approved_budget_plan,
    create_disbursement, create_approved_disbursement,
    create_released_disbursement, create_granted_court_order,
    create_conservator, set_clock,
    setup_funded_release_ready, create_surety_bond_payload,
)
from test_helpers.api_client import api_client as api

ADMIN = make_admin_headers()
FO = make_financial_officer_headers()
CM = make_case_manager_headers()


class TestConservatorForkJoin:
    def test_disbursement_conservator_branch_then_join(self, api):
        """PRD §3.5: "When no co-approval is required, approval moves the
        disbursement `REQUESTED` → `APPROVED` and stamps
        `approved_by_user_id`. When an `ACTIVE` conservator of the client has
        `EXCLUSIVE` scope, or `SHARED` scope with the amount at or above the
        50,000-cent threshold, the same approval instead routes the
        disbursement `REQUESTED` → `PENDING_CONSERVATOR`, still stamping
        `approved_by_user_id`. Co-approval is then performed by a
        `ConservatorOfficer` whose `X-User-ID` is the `id` of an `ACTIVE`
        conservator of that client — anything else fails with
        `ERR_CONSERVATOR_NOT_ACTIVE` — moving the disbursement
        `PENDING_CONSERVATOR` → `APPROVED` and stamping
        `co_approved_by_conservator_id`."

        Design: Difficulty/non_linear_state_machine/disbursement_conservator_branch_then_join
        """
        # Client A: no conservator -> approve goes straight to APPROVED.
        client_a, _ = create_active_client(legal_name="Client Alpha")
        acct_a = create_account(client_a["id"])
        plan_a = create_budget_plan_for_client(client_a["id"])
        da = create_disbursement(client_a["id"], acct_a["id"], plan_a["id"],
                                 amount_cents=10000, payee_name="Payee X")
        # Client B: ACTIVE EXCLUSIVE conservator -> approve diverts.
        client_b, _ = create_active_client(legal_name="Client Beta")
        acct_b = create_account(client_b["id"])
        cons = create_conservator(client_b["id"], authority_scope="EXCLUSIVE")
        plan_b = create_budget_plan_for_client(client_b["id"])
        db = create_disbursement(client_b["id"], acct_b["id"], plan_b["id"],
                                 amount_cents=10000, payee_name="Payee Y")

        da_after = get_success_data(api.approve_disbursement(da["id"], FO))
        assert da_after["status"] == "APPROVED"

        db_after = get_success_data(api.approve_disbursement(db["id"], FO))
        assert db_after["status"] == "PENDING_CONSERVATOR"

        db_joined = get_success_data(
            api.co_approve_disbursement(db["id"], make_conservator_headers(cons["id"]))
        )
        assert db_joined["status"] == "APPROVED"
        assert db_joined["co_approved_by_conservator_id"] == cons["id"]

    def test_disbursement_approve_stamps_approved_by(self, api):
        """PRD §3.5: "When no co-approval is required, approval moves the
        disbursement `REQUESTED` → `APPROVED` and stamps
        `approved_by_user_id`."

        Design: Difficulty/non_linear_state_machine/disbursement_conservator_branch_then_join
        """
        client, _ = create_active_client()
        acct = create_account(client["id"])
        plan = create_budget_plan_for_client(client["id"])
        d = create_disbursement(client["id"], acct["id"], plan["id"],
                                amount_cents=10000, payee_name="Stamp Payee",
                                as_user_id="cm-1")
        after = get_success_data(
            api.approve_disbursement(d["id"], make_financial_officer_headers("fo-1"))
        )
        assert after["status"] == "APPROVED"
        assert after["approved_by_user_id"] == "fo-1"

    def test_conservator_shared_threshold_boundary(self, api):
        """PRD §3.5: "Scope semantics govern co-approval: `EXCLUSIVE` requires
        conservator co-approval on every disbursement for that client, `SHARED`
        requires it only when the disbursement's `amount_cents` is at least
        50,000 cents ($500.00), and `ADVISORY` never requires it."

        Design: Corner/state_machines/conservator_shared_threshold_boundary
        """
        client, _ = create_active_client()
        acct = create_account(client["id"])
        cons = create_conservator(client["id"], authority_scope="SHARED")
        plan = create_budget_plan_for_client(client["id"], source_benefit_cents=200000)
        d_under = create_disbursement(client["id"], acct["id"], plan["id"],
                                      amount_cents=49999, payee_name="Under Threshold")
        d_at = create_disbursement(client["id"], acct["id"], plan["id"],
                                   amount_cents=50000, payee_name="At Threshold")
        under_after = get_success_data(api.approve_disbursement(d_under["id"], FO))
        assert under_after["status"] == "APPROVED"
        at_after = get_success_data(api.approve_disbursement(d_at["id"], FO))
        assert at_after["status"] == "PENDING_CONSERVATOR"

    def test_conservator_discharge_rejects_pending(self, api):
        """PRD §3.5: "discharge is terminal for those disbursements — every
        one of the client's `PENDING_CONSERVATOR` disbursements moves to
        `REJECTED` because the co-signing authority is gone."

        Design: Corner/state_machines/conservator_discharge_rejects_pending
        """
        client, _ = create_active_client()
        acct = create_account(client["id"])
        cons = create_conservator(client["id"], authority_scope="EXCLUSIVE")
        plan = create_budget_plan_for_client(client["id"])
        d = create_disbursement(client["id"], acct["id"], plan["id"],
                                amount_cents=7000, payee_name="Pending Payee")
        d = get_success_data(api.approve_disbursement(d["id"], FO))
        assert d["status"] == "PENDING_CONSERVATOR"
        get_success_data(api.discharge_conservator(cons["id"], ADMIN))
        d_after = get_success_data(api.get_disbursement(d["id"], FO))
        assert d_after["status"] == "REJECTED"

    def test_conservator_suspended_coapprove_rejected(self, api):
        """PRD §3.5: "Co-approval is then performed by a `ConservatorOfficer`
        whose `X-User-ID` is the `id` of an `ACTIVE` conservator of that client
        — anything else fails with `ERR_CONSERVATOR_NOT_ACTIVE` — moving the
        disbursement `PENDING_CONSERVATOR` → `APPROVED` and stamping
        `co_approved_by_conservator_id`."

        Design: Corner/validations/conservator_suspended_coapprove_rejected
        """
        client, _ = create_active_client()
        acct = create_account(client["id"])
        cons = create_conservator(client["id"], authority_scope="EXCLUSIVE")
        plan = create_budget_plan_for_client(client["id"])
        d = create_disbursement(client["id"], acct["id"], plan["id"],
                                amount_cents=7000, payee_name="Susp Payee")
        d = get_success_data(api.approve_disbursement(d["id"], FO))
        assert d["status"] == "PENDING_CONSERVATOR"
        get_success_data(api.suspend_conservator(cons["id"], ADMIN))
        resp = api.co_approve_disbursement(d["id"], make_conservator_headers(cons["id"]))
        validate_error(resp, ApiErrorId.ERR_CONSERVATOR_NOT_ACTIVE)


class TestSegregationOfDuties:
    def test_sod_disbursement_approve_same_user_rejected(self, api):
        """PRD §3.5: "Approval is where duties divide. A `FinancialOfficer`
        approves a `REQUESTED` disbursement, and segregation of duties forbids
        the approver's `X-User-ID` from equaling `requested_by_user_id`,
        failing with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_disbursement_approve_same_user_rejected
        """
        client, _ = create_active_client()
        acct = create_account(client["id"])
        plan = create_budget_plan_for_client(client["id"], as_user_id="shared-1")
        d = create_disbursement(client["id"], acct["id"], plan["id"],
                                amount_cents=5000, payee_name="SoD Payee",
                                as_user_id="shared-1")
        resp = api.approve_disbursement(d["id"], make_financial_officer_headers("shared-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(api.get_disbursement(d["id"], FO))
        assert after["status"] == "REQUESTED"


class TestReleaseGates:
    def test_release_rejected_state_error_precedes_fiscal_error(self, api):
        """PRD §3.6: "Release is the most heavily guarded transition in the
        system, moving a disbursement `APPROVED` → `RELEASED` and actually
        moving money."
        PRD §2.9: "Stage five checks that the entity's state machine permits
        the requested transition from its current state (`ERR_INVALID_STATE`,
        HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/release_rejected_state_error_precedes_fiscal_error
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        plan = create_budget_plan_for_client(client["id"])
        d = create_disbursement(client["id"], acct["id"], plan["id"],
                                amount_cents=30000, payee_name="Payee Z")
        resp = api.release_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_disbursement(d["id"], FO))
        assert after["status"] == "REQUESTED"

    def test_release_from_approved_state_passes_state_gate(self, api):
        """PRD §3.6: "Release is the most heavily guarded transition in the
        system, moving a disbursement `APPROVED` → `RELEASED` and actually
        moving money."

        Design: Difficulty/priority_pair_validation_conflict/release_rejected_state_error_precedes_fiscal_error
        """
        set_clock("2026-06-05T00:00:00Z")
        env = setup_funded_release_ready(deposit_amount=50000, disbursement_amount=10000)
        resp = api.release_disbursement(env["disbursement"]["id"], FO)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "RELEASED"

    def test_restricted_create_safety_error_precedes_referential_error(self, api):
        """PRD §3.5: "Creation enforces its checks in a fixed order: the
        client-activity gate first (a `TERMINATED` client fails with
        `ERR_CLIENT_NOT_ACTIVE`), then the restricted-account court-order
        requirement, then the dedicated-account category rule (a `DEDICATED`
        source account may fund only `MEDICAL` and `EDUCATION` categories,
        otherwise `ERR_DEDICATED_ACCOUNT_RESTRICTED`), and finally foreign-key
        coherence — the account, the budget plan, the court order when present,
        and the spend-down plan when present must all belong to the named
        client, or creation fails with `ERR_BUDGET_PLAN_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/restricted_create_safety_error_precedes_referential_error
        """
        set_clock("2026-06-05T00:00:00Z")
        # Client A owns the RESTRICTED account; client B owns the plan.
        client_a, _ = create_active_client(legal_name="Client Aaa")
        acct_r = create_account(client_a["id"], account_type="RESTRICTED")
        client_b, _ = create_active_client(legal_name="Client Bbb")
        plan_b = create_budget_plan_for_client(client_b["id"])
        resp = api.create_disbursement(
            {
                "client_id": client_a["id"],
                "account_id": acct_r["id"],
                "budget_plan_id": plan_b["id"],
                "payee_name": "Payee W",
                "category": "HOUSING",
                "amount_cents": 10000,
                "scheduled_release_date": "2026-06-10",
            },
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_COURT_ORDER_REQUIRED)

    def test_restricted_create_with_court_order_succeeds(self, api):
        """PRD §3.5: "Two optional references ride along: `court_order_id`,
        which is required exactly when the source account is `RESTRICTED` (its
        absence there fails creation with `ERR_COURT_ORDER_REQUIRED`), and
        `spend_down_plan_id`, which links the spend to a Medicaid spend-down
        plan."

        Design: Difficulty/priority_pair_validation_conflict/restricted_create_safety_error_precedes_referential_error
        """
        client, _ = create_active_client()
        acct_r = create_account(client["id"], account_type="RESTRICTED")
        plan = create_budget_plan_for_client(client["id"])
        order = create_granted_court_order(client["id"], amount_limit_cents=50000)
        resp = api.create_disbursement(
            {
                "client_id": client["id"],
                "account_id": acct_r["id"],
                "budget_plan_id": plan["id"],
                "payee_name": "Restricted Payee",
                "category": "HOUSING",
                "amount_cents": 10000,
                "scheduled_release_date": "2026-06-10",
                "court_order_id": order["id"],
            },
            CM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "REQUESTED"
        assert data["court_order_id"] == order["id"]

    def test_insufficient_funds_on_release(self, api):
        """PRD §3.6: "Sixth, the account's `balance_cents` must be at least
        `amount_cents`, failing with `ERR_INSUFFICIENT_FUNDS`."

        Design: Corner/validations/insufficient_funds_on_release
        """
        set_clock("2026-06-10T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 50000, received_date="2026-06-05")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=100000)
        d = create_approved_disbursement(client["id"], acct["id"], plan["id"],
                                         amount_cents=60000, payee_name="Big Payee")
        resp = api.release_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS)

    def test_budget_category_exceeded_on_release(self, api):
        """PRD §3.6: "Seventh, the spend must fit the category's remaining
        allocation: `amount_cents` must not exceed the category's
        `allocated_lines` amount minus the sum of `amount_cents` over
        already-`RELEASED` and not-yet-`RETURNED` disbursements sharing the
        same `budget_plan_id` and `category`, failing with
        `ERR_BUDGET_CATEGORY_EXCEEDED`."

        Design: Corner/validations/budget_category_exceeded_on_release
        """
        set_clock("2026-06-10T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 200000, received_date="2026-06-05")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=50000)
        create_released_disbursement(client["id"], acct["id"], plan["id"],
                                     amount_cents=30000, payee_name="First")
        d2 = create_approved_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=30000, payee_name="Second")
        resp = api.release_disbursement(d2["id"], FO)
        validate_error(resp, ApiErrorId.ERR_BUDGET_CATEGORY_EXCEEDED)
        d2_after = get_success_data(api.get_disbursement(d2["id"], FO))
        assert d2_after["status"] == "APPROVED"
        acct_after = get_success_data(api.get_trust_account(acct["id"], FO))
        assert acct_after["balance_cents"] == 170000

    def test_disbursement_release_requires_active_bond(self, api):
        """PRD §3.6: "Last, an `ACTIVE` surety bond must exist, failing with
        `ERR_NO_ACTIVE_BOND`."

        Design: Difficulty/cross_entity_state_dependency/disbursement_release_requires_active_bond
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        # Post deposit BEFORE any bond exists (posts unbounded without ACTIVE bond).
        create_and_post_deposit(acct["id"], 50000, received_date="2026-06-02")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=100000)
        d = create_approved_disbursement(client["id"], acct["id"], plan["id"],
                                         amount_cents=10000, payee_name="Payee Q")
        bond = get_success_data(api.create_surety_bond(
            create_surety_bond_payload(coverage_amount_cents=1000000), ADMIN
        ))
        resp = api.release_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_BOND)
        get_success_data(api.activate_surety_bond(bond["id"], ADMIN))
        resp2 = api.release_disbursement(d["id"], FO)
        data = validate_success(resp2, expected_status=200)
        assert data["status"] == "RELEASED"

    def test_disbursement_release_succeeds_with_active_bond(self, api):
        """PRD §3.6: "Last, an `ACTIVE` surety bond must exist, failing with
        `ERR_NO_ACTIVE_BOND`."

        Design: Difficulty/cross_entity_state_dependency/disbursement_release_requires_active_bond
        """
        set_clock("2026-06-05T00:00:00Z")
        env = setup_funded_release_ready(deposit_amount=50000, disbursement_amount=10000)
        resp = api.release_disbursement(env["disbursement"]["id"], FO)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "RELEASED"
        assert data["released_at"] is not None


class TestRestrictedAndDedicatedAccounts:
    def test_dedicated_account_category_rejected_at_create(self, api):
        """PRD §3.5: "Creation enforces its checks in a fixed order: the
        client-activity gate first (a `TERMINATED` client fails with
        `ERR_CLIENT_NOT_ACTIVE`), then the restricted-account court-order
        requirement, then the dedicated-account category rule (a `DEDICATED`
        source account may fund only `MEDICAL` and `EDUCATION` categories,
        otherwise `ERR_DEDICATED_ACCOUNT_RESTRICTED`), and finally foreign-key
        coherence — the account, the budget plan, the court order when present,
        and the spend-down plan when present must all belong to the named
        client, or creation fails with `ERR_BUDGET_PLAN_MISMATCH`."

        Design: Corner/validations/dedicated_account_category_rejected_at_create
        """
        client, _ = create_active_client()
        acct_d = create_account(client["id"], account_type="DEDICATED")
        acct_o = create_account(client["id"], account_type="OPERATING")
        plan = create_budget_plan_for_client(client["id"])
        resp = api.create_disbursement(
            {
                "client_id": client["id"], "account_id": acct_d["id"],
                "budget_plan_id": plan["id"], "payee_name": "Ded Payee",
                "category": "HOUSING", "amount_cents": 5000,
                "scheduled_release_date": "2026-06-10",
            },
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_DEDICATED_ACCOUNT_RESTRICTED)
        resp2 = api.create_disbursement(
            {
                "client_id": client["id"], "account_id": acct_o["id"],
                "budget_plan_id": plan["id"], "payee_name": "Op Payee",
                "category": "HOUSING", "amount_cents": 5000,
                "scheduled_release_date": "2026-06-10",
            },
            CM,
        )
        data = validate_success(resp2, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert data["status"] == "REQUESTED"

    def test_court_order_amount_exceeded_on_release(self, api):
        """PRD §3.6: "Second, the disbursement's `amount_cents` must not exceed
        the order's `amount_limit_cents`, failing with
        `ERR_COURT_ORDER_EXCEEDED`."

        Design: Corner/validations/court_order_amount_exceeded_on_release
        """
        set_clock("2026-06-10T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"], account_type="RESTRICTED")
        create_active_bond()
        create_and_post_deposit(acct["id"], 100000, received_date="2026-06-05")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=100000)
        order = create_granted_court_order(client["id"], amount_limit_cents=25000)
        d = create_approved_disbursement(
            client["id"], acct["id"], plan["id"], amount_cents=30000,
            payee_name="Cap Payee", court_order_id=order["id"],
        )
        resp = api.release_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_COURT_ORDER_EXCEEDED)

    def test_restricted_release_executes_court_order(self, api):
        """PRD §3.6: "When the source account is `RESTRICTED`, release also
        consumes the court order: the order moves `GRANTED` → `EXECUTED` and
        records the releasing disbursement's id in `executed_disbursement_id`."
        PRD §3.6: "First, for a `RESTRICTED` source account, the named court
        order must be grantable: the `court_order_id` must be present, the
        order must be `GRANTED`, it must belong to the disbursement's client,
        its `order_type` must be `RESTRICTED_WITHDRAWAL`, and the logical clock
        date must be on or before its `expiry_date` — any failure is
        `ERR_COURT_ORDER_NOT_GRANTABLE`."

        Design: Corner/state_machines/restricted_release_executes_court_order
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"], account_type="RESTRICTED")
        create_active_bond()
        create_and_post_deposit(acct["id"], 100000, received_date="2026-06-02")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=100000)
        order = create_granted_court_order(client["id"], amount_limit_cents=50000,
                                           expiry_date="2026-12-31")
        w1 = create_approved_disbursement(
            client["id"], acct["id"], plan["id"], amount_cents=20000,
            payee_name="Court Payee", court_order_id=order["id"],
        )
        w1_after = get_success_data(api.release_disbursement(w1["id"], FO))
        assert w1_after["status"] == "RELEASED"
        order_after = get_success_data(api.get_court_order(order["id"], ADMIN))
        assert order_after["status"] == "EXECUTED"
        assert order_after["executed_disbursement_id"] == w1["id"]
        # A second release attempt against the consumed order fails.
        w2 = create_approved_disbursement(
            client["id"], acct["id"], plan["id"], amount_cents=10000,
            payee_name="Court Payee 2", court_order_id=order["id"],
            scheduled_release_date="2026-06-11",
        )
        resp = api.release_disbursement(w2["id"], FO)
        validate_error(resp, ApiErrorId.ERR_COURT_ORDER_NOT_GRANTABLE)


class TestFiduciaryFee:
    def test_fiduciary_fee_tier_straddle_with_monthly_cap(self, api):
        """PRD §3.6: "The first tier charges the portion of that interval lying
        at or below 100,000 cents ($1,000.00) at five percent; the second tier
        charges the portion lying above 100,000 cents and at or below 300,000
        cents ($3,000.00) — a span of 200,000 cents — at three percent; the
        third tier charges the portion above 300,000 cents at one and a half
        percent. The raw fee is the sum of the three tier charges, rounded
        half-up to whole cents exactly once, at release. A monthly cap then
        applies: the fee charged is the smaller of the rounded raw fee and the
        remaining headroom under a 20,000-cent ($200.00) monthly cap, where
        headroom is the cap minus the sum of `fee_cents` already charged on the
        client's releases in the same clock month, floored at zero."

        Design: Difficulty/combinatorial_formula/fiduciary_fee_tier_straddle_with_monthly_cap
        """
        set_clock("2026-06-15T00:00:00Z")
        client, _ = create_active_client(claim_type="SSDI", monthly_benefit_cents=90000)
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 950000, received_date="2026-06-10")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=2000000)
        w1 = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=100000, payee_name="Payee A",
                                          scheduled_release_date="2026-06-15")
        assert w1["fee_cents"] == 5000
        w2 = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=200000, payee_name="Payee B",
                                          scheduled_release_date="2026-06-15")
        assert w2["fee_cents"] == 6000
        w3 = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=550000, payee_name="Payee C",
                                          scheduled_release_date="2026-06-15")
        assert w3["fee_cents"] == 8250
        w4 = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=100000, payee_name="Payee D",
                                          scheduled_release_date="2026-06-15")
        assert w4["fee_cents"] == 750
        acct_after = get_success_data(api.get_trust_account(acct["id"], FO))
        assert acct_after["balance_cents"] == 0

    def test_fiduciary_fee_tier1_only_release(self, api):
        """PRD §3.6: "The first tier charges the portion of that interval lying
        at or below 100,000 cents ($1,000.00) at five percent; the second tier
        charges the portion lying above 100,000 cents and at or below 300,000
        cents ($3,000.00) — a span of 200,000 cents — at three percent; the
        third tier charges the portion above 300,000 cents at one and a half
        percent."

        Design: Difficulty/combinatorial_formula/fiduciary_fee_tier_straddle_with_monthly_cap
        """
        set_clock("2026-06-15T00:00:00Z")
        env = setup_funded_release_ready(deposit_amount=200000, budget_basis=1000000,
                                         disbursement_amount=100000)
        resp = api.release_disbursement(env["disbursement"]["id"], FO)
        data = validate_success(resp, expected_status=200)
        # v=0, amount=100000: entirely tier1 at 5% -> 5000
        assert data["fee_cents"] == 5000

    def test_fee_tier_straddle_uncapped(self, api):
        """PRD §3.6: "The first tier charges the portion of that interval lying
        at or below 100,000 cents ($1,000.00) at five percent; the second tier
        charges the portion lying above 100,000 cents and at or below 300,000
        cents ($3,000.00) — a span of 200,000 cents — at three percent; the
        third tier charges the portion above 300,000 cents at one and a half
        percent."

        Design: Corner/calculations/fee_tier_straddle_uncapped
        """
        set_clock("2026-06-10T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 200000, received_date="2026-06-05")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=500000)
        w1 = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=90000, payee_name="Tier One")
        assert w1["fee_cents"] == 4500
        w2 = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=20000, payee_name="Tier Two",
                                          scheduled_release_date="2026-06-11")
        assert w2["fee_cents"] == 800

    def test_fee_rounding_half_up_per_disbursement(self, api):
        """PRD §3.6: "The raw fee is the sum of the three tier charges, rounded
        half-up to whole cents exactly once, at release."
        PRD §3.6: "The month-to-date fee total is therefore the sum of
        individually rounded per-release fees; the tiered fee is never computed
        on aggregated monthly volume and rounded afterwards."

        Design: Corner/calculations/fee_rounding_half_up_per_disbursement
        """
        set_clock("2026-06-10T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 100000, received_date="2026-06-05")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=100000)
        w1 = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=3333, payee_name="Round One")
        w2 = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=3333, payee_name="Round Two")
        assert w1["fee_cents"] == 167
        assert w2["fee_cents"] == 167
        assert w1["fee_cents"] + w2["fee_cents"] == 334


class TestReturnConservation:
    def test_release_then_return_conserves_cash(self, api):
        """PRD §3.6: "When a released payment comes back — a returned check, a
        refused transfer — returning it moves the disbursement `RELEASED` →
        `RETURNED`, stamps `returned_at`, appends a compensating
        `DISBURSEMENT_RETURNED` ledger entry crediting the original
        `amount_cents`, and recomputes the account balance and client rollups."
        PRD §2.6: "No account balance is ever stored as mutable state. A trust
        account's `balance_cents` is derived as the signed sum of its ledger
        entries, and every balance-affecting event in the system — posting a
        deposit, releasing a disbursement, returning either — appends exactly
        one ledger entry and then recomputes the derived balances that depend
        on it."

        Design: Difficulty/compensating_invariant/release_then_return_conserves_cash
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 50000, received_date="2026-06-02")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=100000)
        w = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                         amount_cents=30000, payee_name="Payee R")
        assert w["fee_cents"] == 1500
        acct_mid = get_success_data(api.get_trust_account(acct["id"], FO))
        assert acct_mid["balance_cents"] == 20000
        w_ret = get_success_data(api.return_disbursement(w["id"], FO))
        assert w_ret["status"] == "RETURNED"
        acct_end = get_success_data(api.get_trust_account(acct["id"], FO))
        assert acct_end["balance_cents"] == 50000
        rows, _meta = validate_paginated(api.get_account_ledger(acct["id"], FO))
        assert rows[0]["amount_cents"] == 50000
        assert rows[1]["amount_cents"] == -30000
        assert rows[2]["amount_cents"] == 30000
        assert rows[2]["balance_after_cents"] == 50000

    def test_return_restores_client_rollups(self, api):
        """PRD §3.6: "When a released payment comes back — a returned check, a
        refused transfer — returning it moves the disbursement `RELEASED` →
        `RETURNED`, stamps `returned_at`, appends a compensating
        `DISBURSEMENT_RETURNED` ledger entry crediting the original
        `amount_cents`, and recomputes the account balance and client rollups."

        Design: Difficulty/compensating_invariant/release_then_return_conserves_cash
        """
        set_clock("2026-06-05T00:00:00Z")
        env = setup_funded_release_ready(deposit_amount=50000, disbursement_amount=30000)
        client = env["client"]
        d = env["disbursement"]
        get_success_data(api.release_disbursement(d["id"], FO))
        mid = get_success_data(api.get_client(client["id"], ADMIN))
        assert mid["total_funds_cents"] == 20000
        ret = get_success_data(api.return_disbursement(d["id"], FO))
        assert ret["status"] == "RETURNED"
        assert ret["returned_at"] is not None
        end = get_success_data(api.get_client(client["id"], ADMIN))
        assert end["total_funds_cents"] == 50000
        assert end["countable_resources_cents"] == 50000


class TestInvalidTransitions:
    def test_reject_released_disbursement_returns_invalid_state(self, api):
        """PRD §3.5: "A `FinancialOfficer` may also reject a disbursement
        outright from `REQUESTED` or `PENDING_CONSERVATOR`, moving it to
        `REJECTED`."
        PRD §2.9: "Stage five checks that the entity's state machine permits
        the requested transition from its current state (`ERR_INVALID_STATE`,
        HTTP 409)."

        Design: Corner/state_machines/reject_released_disbursement_returns_invalid_state
        """
        set_clock("2026-06-05T00:00:00Z")
        env = setup_funded_release_ready(deposit_amount=50000, disbursement_amount=10000)
        d = env["disbursement"]
        get_success_data(api.release_disbursement(d["id"], FO))
        resp = api.reject_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_disbursement(d["id"], FO))
        assert after["status"] == "RELEASED"

    def test_approve_rejected_disbursement_returns_already_terminal(self, api):
        """PRD §2.9: "Stage six is the terminal-state guard: an entity already
        in a terminal state — a `TERMINATED` client or entitlement, a `CLOSED`
        account, a `SUPERSEDED` plan, a `REJECTED` or `RETURNED` disbursement,
        an `ACCEPTED` or `REJECTED` report, a `MET` or `LAPSED` spend-down
        plan, a `DISCHARGED` conservator, an `EXECUTED` or `EXPIRED` court
        order, a `LAPSED` bond, a `CLOSED_NO_ACTION` or `MISUSE_CONFIRMED`
        audit — rejects any further action with `ERR_ALREADY_TERMINAL` (HTTP
        409)."

        Design: Corner/state_machines/approve_rejected_disbursement_returns_already_terminal
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        plan = create_budget_plan_for_client(client["id"])
        d = create_disbursement(client["id"], acct["id"], plan["id"],
                                amount_cents=5000, payee_name="Term Payee")
        get_success_data(api.reject_disbursement(d["id"], FO))
        resp = api.approve_disbursement(d["id"], FO)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestImmediateVisibility:
    def test_immediate_visibility_in_mutation_response(self, api):
        """PRD §3.6: "A successful release stamps `released_at` from the
        logical clock, appends a `DISBURSEMENT_RELEASED` ledger entry debiting
        `amount_cents` with the disbursement's id as its `reference_id`,
        recomputes the account balance and the client's fund rollups, and
        computes the fiduciary fee into `fee_cents`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_visibility_in_mutation_response
        """
        set_clock("2026-06-10T00:00:00Z")
        env = setup_funded_release_ready(deposit_amount=50000, disbursement_amount=20000)
        d = env["disbursement"]
        resp = api.release_disbursement(d["id"], FO)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "RELEASED"
        assert data["fee_cents"] == 1000
        assert data["released_at"] is not None
        got = get_success_data(api.get_disbursement(d["id"], FO))
        assert got["status"] == "RELEASED"
        assert got["fee_cents"] == 1000


class TestSuspendConditionalCascade:
    def test_suspend_rejects_only_pending_disbursements(self, api):
        """PRD §3.2: "When an account freezes — through suspension,
        termination, or the misuse cascade — every disbursement posted against
        that account in `REQUESTED`, `PENDING_CONSERVATOR`, or `APPROVED` moves
        to `REJECTED`; this rejection is the freeze cascade's second link and
        needs no operator action."

        Design: Corner/state_machines/suspend_rejects_only_pending_disbursements
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client()
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 80000, received_date="2026-06-02")
        plan = create_approved_budget_plan(client["id"], source_benefit_cents=100000)
        d1 = create_released_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=10000, payee_name="Payee R1",
                                          scheduled_release_date="2026-06-05")
        d2 = create_disbursement(client["id"], acct["id"], plan["id"],
                                 amount_cents=5000, payee_name="Payee R2",
                                 scheduled_release_date="2026-06-06")
        d3 = create_approved_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=6000, payee_name="Payee R3",
                                          scheduled_release_date="2026-06-06")
        get_success_data(api.suspend_client(client["id"], ADMIN))
        assert get_success_data(api.get_disbursement(d1["id"], FO))["status"] == "RELEASED"
        assert get_success_data(api.get_disbursement(d2["id"], FO))["status"] == "REJECTED"
        assert get_success_data(api.get_disbursement(d3["id"], FO))["status"] == "REJECTED"
        acct_after = get_success_data(api.get_trust_account(acct["id"], FO))
        assert acct_after["status"] == "FROZEN"
        assert acct_after["balance_cents"] == 70000
