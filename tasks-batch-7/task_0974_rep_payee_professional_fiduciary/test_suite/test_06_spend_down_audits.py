"""Spend-down plans and audits: provisional-vs-final divergence, Medicaid
boundary precision, lapsed branch, misuse cascade, RBAC on audit endpoints."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId, make_admin_headers, make_financial_officer_headers,
    make_case_manager_headers, make_auditor_headers,
    create_client, create_active_client, create_client_with_verified_entitlement,
    create_account, create_active_bond, create_and_post_deposit,
    create_budget_plan_for_client, create_approved_budget_plan,
    create_disbursement, create_approved_disbursement,
    create_released_disbursement, create_spend_down_plan,
    create_active_spend_down_plan, create_audit_with_findings, set_clock,
    create_audit_case_payload,
)
from test_helpers.api_client import api_client as api

ADMIN = make_admin_headers()
FO = make_financial_officer_headers()
CM = make_case_manager_headers()
AUD = make_auditor_headers()


class TestProvisionalVsFinal:
    def test_spend_down_provisional_vs_final_divergence(self, api):
        """PRD §3.9: "At creation the plan computes its provisional excess: the
        client's current `countable_resources_cents`, plus the expected inflow
        — the sum of `monthly_benefit_cents` over the client's `VERIFIED`
        entitlements whose half-open effective window covers at least one day
        of `target_month`, where a null `effective_end_date` covers every month
        from the start onward — minus `medicaid_resource_limit_cents`, floored
        at zero, stored as `provisional_excess_cents`."
        PRD §3.9: "Finalization, allowed once the logical clock date has
        reached the `target_month`, computes the final excess — the client's
        actual `countable_resources_cents` at finalize time minus the resource
        limit, floored at zero, with no expected-inflow term — into
        `final_excess_cents` and routes the plan by its value: a final excess
        of exactly zero moves the plan `ACTIVE` → `MET`, while a positive final
        excess moves it `ACTIVE` → `LAPSED`."

        Design: Difficulty/dual_variant_calc/spend_down_provisional_vs_final_divergence
        """
        set_clock("2026-06-05T00:00:00Z")
        client, ent = create_active_client(medicaid_enrolled=True)
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 150000, received_date="2026-06-02")
        sp = create_spend_down_plan(client["id"], target_month="2026-06",
                                    entries=[{"category": "MEDICAL",
                                              "planned_amount_cents": 40000}])
        assert sp["provisional_excess_cents"] == 30000
        sp = get_success_data(api.activate_spend_down_plan(sp["id"], CM))
        plan = create_approved_budget_plan(client["id"], period_month="2026-06",
                                           source_benefit_cents=200000,
                                           lines=[{"category": "MEDICAL", "percent": 100}])
        w = create_approved_disbursement(
            client["id"], acct["id"], plan["id"], amount_cents=40000,
            category="MEDICAL", payee_name="Clinic North",
            scheduled_release_date="2026-06-10", spend_down_plan_id=sp["id"],
        )
        get_success_data(api.release_disbursement(w["id"], FO))
        finalized = get_success_data(api.finalize_spend_down_plan(sp["id"], CM))
        assert finalized["final_excess_cents"] == 0
        assert finalized["status"] == "MET"
        assert sp["provisional_excess_cents"] != finalized["final_excess_cents"]

    def test_spend_down_provisional_includes_expected_inflow(self, api):
        """PRD §3.9: "At creation the plan computes its provisional excess: the
        client's current `countable_resources_cents`, plus the expected inflow
        — the sum of `monthly_benefit_cents` over the client's `VERIFIED`
        entitlements whose half-open effective window covers at least one day
        of `target_month`, where a null `effective_end_date` covers every month
        from the start onward — minus `medicaid_resource_limit_cents`, floored
        at zero, stored as `provisional_excess_cents`."

        Design: Difficulty/dual_variant_calc/spend_down_provisional_vs_final_divergence
        """
        set_clock("2026-06-05T00:00:00Z")
        # Open-ended entitlement contributes 80000 expected inflow to June.
        client, ent = create_active_client(medicaid_enrolled=True)
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 150000, received_date="2026-06-02")
        sp = create_spend_down_plan(client["id"], target_month="2026-06",
                                    entries=[{"category": "MEDICAL",
                                              "planned_amount_cents": 40000}])
        # max(0, 150000 + 80000 - 200000) = 30000
        assert sp["provisional_excess_cents"] == 30000
        assert sp["auto_created"] is False

    def test_spend_down_finalize_lapsed_branch(self, api):
        """PRD §3.9: "Finalization, allowed once the logical clock date has
        reached the `target_month`, computes the final excess — the client's
        actual `countable_resources_cents` at finalize time minus the resource
        limit, floored at zero, with no expected-inflow term — into
        `final_excess_cents` and routes the plan by its value: a final excess
        of exactly zero moves the plan `ACTIVE` → `MET`, while a positive final
        excess moves it `ACTIVE` → `LAPSED`."

        Design: Corner/state_machines/spend_down_finalize_lapsed_branch
        """
        set_clock("2026-06-20T00:00:00Z")
        client, _ = create_active_client(medicaid_enrolled=True)
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 250000, received_date="2026-06-02")
        sp = create_spend_down_plan(client["id"], target_month="2026-06",
                                    entries=[{"category": "MEDICAL",
                                              "planned_amount_cents": 50000}])
        assert sp["provisional_excess_cents"] == 130000
        sp = get_success_data(api.activate_spend_down_plan(sp["id"], CM))
        finalized = get_success_data(api.finalize_spend_down_plan(sp["id"], CM))
        assert finalized["status"] == "LAPSED"
        assert finalized["final_excess_cents"] == 50000


class TestMedicaidBoundary:
    def test_medicaid_resource_limit_exact_boundary(self, api):
        """PRD §3.1: "and `medicaid_at_risk`, which is true exactly when the
        client is Medicaid-enrolled and `countable_resources_cents` is strictly
        greater than `medicaid_resource_limit_cents` — equality with the
        ceiling is not at risk."
        PRD §3.9: "Activation moves a plan `DRAFT` → `ACTIVE` and requires
        genuine necessity: a plan whose `provisional_excess_cents` is zero is
        not activatable and fails with `ERR_SPEND_DOWN_NOT_REQUIRED`."

        Design: Difficulty/boundary_precision_check/medicaid_resource_limit_exact_boundary
        """
        set_clock("2026-06-05T00:00:00Z")
        # Entitlement window [2026-01-01, 2026-06-01): end-exclusive, June inflow = 0.
        client, ent = create_active_client(
            medicaid_enrolled=True, effective_end_date="2026-06-01"
        )
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 200000, received_date="2026-06-02")
        client_before = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_before["medicaid_at_risk"] is False
        sp1 = create_spend_down_plan(client["id"], target_month="2026-06",
                                     entries=[{"category": "MEDICAL",
                                               "planned_amount_cents": 1000}])
        assert sp1["provisional_excess_cents"] == 0
        resp = api.activate_spend_down_plan(sp1["id"], CM)
        validate_error(resp, ApiErrorId.ERR_SPEND_DOWN_NOT_REQUIRED)
        # One cent over flips the boundary.
        create_and_post_deposit(acct["id"], 1, received_date="2026-06-06")
        client_after = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_after["countable_resources_cents"] == 200001
        assert client_after["medicaid_at_risk"] is True
        sp2 = create_spend_down_plan(client["id"], target_month="2026-06",
                                     entries=[{"category": "MEDICAL",
                                               "planned_amount_cents": 1000}])
        assert sp2["provisional_excess_cents"] == 1
        sp2_after = get_success_data(api.activate_spend_down_plan(sp2["id"], CM))
        assert sp2_after["status"] == "ACTIVE"

    def test_medicaid_at_risk_strict_greater_than_semantics(self, api):
        """PRD §3.1: "and `medicaid_at_risk`, which is true exactly when the
        client is Medicaid-enrolled and `countable_resources_cents` is strictly
        greater than `medicaid_resource_limit_cents` — equality with the
        ceiling is not at risk."

        Design: Difficulty/boundary_precision_check/medicaid_resource_limit_exact_boundary
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client(medicaid_enrolled=True)
        acct = create_account(client["id"])
        create_active_bond()
        create_and_post_deposit(acct["id"], 200000, received_date="2026-06-02")
        at_limit = get_success_data(api.get_client(client["id"], ADMIN))
        assert at_limit["countable_resources_cents"] == 200000
        assert at_limit["medicaid_at_risk"] is False
        create_and_post_deposit(acct["id"], 1, received_date="2026-06-06")
        over = get_success_data(api.get_client(client["id"], ADMIN))
        assert over["countable_resources_cents"] == 200001
        assert over["medicaid_at_risk"] is True


class TestAuditMisuseCascade:
    def test_audit_misuse_triggers_suspension_cascade(self, api):
        """PRD §3.9: "Closing a findings-issued case forks on the misuse
        amount: with `misuse_amount_cents` equal to zero the case moves
        `FINDINGS_ISSUED` → `CLOSED_NO_ACTION`; with any positive misuse amount
        it moves `FINDINGS_ISSUED` → `MISUSE_CONFIRMED`, and that confirmation
        fires the misuse cascade in three links — the client moves `ACTIVE` →
        `SUSPENDED`, every `OPEN` account of the client freezes to `FROZEN`,
        and each frozen account rejects its pending disbursements in
        `REQUESTED`, `PENDING_CONSERVATOR`, and `APPROVED` to `REJECTED`."

        Design: Difficulty/transitive_cascade/audit_misuse_triggers_suspension_cascade
        """
        set_clock("2026-06-05T00:00:00Z")
        client, _ = create_active_client(claim_type="SSDI", monthly_benefit_cents=90000)
        acct = create_account(client["id"])
        plan = create_budget_plan_for_client(client["id"])
        d1 = create_disbursement(client["id"], acct["id"], plan["id"],
                                 amount_cents=5000, payee_name="Payee One")
        d2 = create_approved_disbursement(client["id"], acct["id"], plan["id"],
                                          amount_cents=6000, payee_name="Payee Two")
        case = create_audit_with_findings(client["id"], misuse_amount_cents=5000,
                                          findings_count=2)
        closed = get_success_data(api.close_audit_case(case["id"], AUD))
        assert closed["status"] == "MISUSE_CONFIRMED"
        client_after = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_after["status"] == "SUSPENDED"
        acct_after = get_success_data(api.get_trust_account(acct["id"], FO))
        assert acct_after["status"] == "FROZEN"
        assert get_success_data(api.get_disbursement(d1["id"], FO))["status"] == "REJECTED"
        assert get_success_data(api.get_disbursement(d2["id"], FO))["status"] == "REJECTED"

    def test_audit_close_clean_findings_no_action(self, api):
        """PRD §3.9: "Closing a findings-issued case forks on the misuse
        amount: with `misuse_amount_cents` equal to zero the case moves
        `FINDINGS_ISSUED` → `CLOSED_NO_ACTION`; with any positive misuse amount
        it moves `FINDINGS_ISSUED` → `MISUSE_CONFIRMED`, and that confirmation
        fires the misuse cascade in three links — the client moves `ACTIVE` →
        `SUSPENDED`, every `OPEN` account of the client freezes to `FROZEN`,
        and each frozen account rejects its pending disbursements in
        `REQUESTED`, `PENDING_CONSERVATOR`, and `APPROVED` to `REJECTED`."

        Design: Difficulty/transitive_cascade/audit_misuse_triggers_suspension_cascade
        """
        client, _ = create_active_client()
        case = create_audit_with_findings(client["id"], misuse_amount_cents=0,
                                          findings_count=0)
        closed = get_success_data(api.close_audit_case(case["id"], AUD))
        assert closed["status"] == "CLOSED_NO_ACTION"
        client_after = get_success_data(api.get_client(client["id"], ADMIN))
        assert client_after["status"] == "ACTIVE"
