"""Corner-design coverage for errors and rbac sections."""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    set_clock,
    create_decedent,
    create_estate,
    create_asset,
    create_designation,
    create_executor,
    accept_executor,
    create_guardianship,
    finalize_plan,
    register_death,
    file_for_probate,
    create_probate_order,
    enter_probate_order,
    create_creditor_claim,
    bootstrap_estate_in_administration,
    make_planner_headers,
    make_judge_headers,
    make_executor_headers,
    make_registrar_headers,
    make_creditor_headers,
)


class TestUnauthorizedJudgeCannotRegisterDeath:
    def test_only_registrar_can_register_death(self, api):
        """PRD §4 (endpoint row): "POST /decedents/{id}/register-death ...
        Record date of death; drives Estate, POA, asset, and guardianship
        cascade. Registrar"
        PRD §2.1: "A request that is authenticated but whose role is not
        permitted for the requested operation is rejected with
        ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/errors/unauthorized_judge_cannot_register_death
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Nash N",
            domicile_state_code="CA", ssn_last4="0020",
        )
        resp = api.register_death(
            dec["id"], {"date_of_death": "2026-02-01T00:00:00Z"},
            make_judge_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestRbacEstatePlannerCannotEnterProbateOrder:
    def test_planner_cannot_enter_probate_order(self, api):
        """PRD §4 (endpoint row): "POST /probate-orders/{id}/enter ... Judge
        signs order: DRAFT to ENTERED; cascade per order_type. Judge"
        PRD §2.1: "A request that is authenticated but whose role is not
        permitted for the requested operation is rejected with
        ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/estate_planner_cannot_enter_probate_order
        """
        # Walk to PROBATE_PENDING with an OPEN_PROBATE order in DRAFT.
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Pip P",
            domicile_state_code="CA", ssn_last4="0022",
        )
        estate = create_estate(dec["id"])
        create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
        create_designation(estate["id"], "Heir P", "CHILD", 10000)
        executor = create_executor(estate["id"], "Exec P", "EXECUTOR", False)
        executor = accept_executor(executor["id"])
        finalize_plan(estate["id"])
        register_death(dec["id"], "2026-01-15T00:00:00Z")
        file_for_probate(estate["id"], executor["id"])
        order = create_probate_order(estate["id"], "OPEN_PROBATE")
        # Try to enter as planner.
        resp = api.enter_probate_order(order["id"], make_planner_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestRbacCreditorCannotAllowClaim:
    def test_creditor_cannot_allow_claim(self, api):
        """PRD §4 (endpoint row): "POST /creditor-claims/{id}/allow ...
        FILED to ALLOWED. Executor"
        PRD §2.1: "A request that is authenticated but whose role is not
        permitted for the requested operation is rejected with
        ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/creditor_cannot_allow_claim
        """
        ctx = bootstrap_estate_in_administration(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-15T00:00:00Z",
            asset_value_cents=1000000,
            domicile_state_code="NY",
        )
        claim = create_creditor_claim(
            ctx["estate"]["id"], "C1", 100000, "UNSECURED",
            "2026-02-01T00:00:00Z",
        )
        resp = api.allow_creditor_claim(claim["id"], make_creditor_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
