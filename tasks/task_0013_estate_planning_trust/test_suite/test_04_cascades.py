"""Transitive cascade chains.

Death registration triggers a depth-3 cascade (Decedent->Estate->POA/Asset/Guardianship);
close-estate triggers a depth-2 cascade (ProbateOrder->Estate->Executor).
"""
import pytest

from test_helpers import (
    validate_success,
    bootstrap_estate_with_non_durable_and_durable_poas,
    bootstrap_estate_closed,
    bootstrap_estate_in_administration,
    bootstrap_two_scope_poas_on_decedent,
    register_death,
    create_probate_order,
    enter_probate_order,
    allow_creditor_claim,
    create_creditor_claim,
    make_executor_headers,
    make_registrar_headers,
    make_planner_headers,
    make_judge_headers,
)


class TestDeathRegistrationCascadeDepth3:
    """PRD §3.3: register-death drives the multi-entity cascade."""

    def test_death_terminates_non_durable_poa_and_excludes_ira(self, api):
        """PRD §3.3: "Every PowerOfAttorney on this decedent whose scope is
        FINANCIAL or HEALTHCARE (the two non-durable variants) and whose
        current status is ACTIVE is terminated — moved to the TERMINATED
        state — because non-durable powers do not survive incapacity or
        death. The two durable variants — DURABLE_FINANCIAL and
        DURABLE_HEALTHCARE — explicitly survive and are not touched by this
        cascade."

        Design: Difficulty/transitive_cascade/death_registration_cascade_depth_3
        """
        ctx = bootstrap_estate_with_non_durable_and_durable_poas()
        # Verify initial gross.
        assert ctx["estate"]["gross_estate_value_cents"] == 1500000
        # Register death.
        register_death(ctx["decedent"]["id"], "2026-02-01T00:00:00Z")
        # Estate should be DECEASED, non-durable POA TERMINATED,
        # durable POA still ACTIVE, IRA asset EXCLUDED.
        est = validate_success(
            api.get_estate(ctx["estate"]["id"], make_planner_headers()),
            expected_status=200,
        )
        assert est["status"] == "DECEASED"
        # After IRA EXCLUDED, gross drops to bank-only value 500_000.
        assert est["gross_estate_value_cents"] == 500000, (
            f"Gross should reflect IRA exclusion (500_000), "
            f"got {est['gross_estate_value_cents']}"
        )

        poa_nd = validate_success(
            api.get_poa(ctx["poa_non_durable"]["id"], make_planner_headers()),
            expected_status=200,
        )
        assert poa_nd["status"] == "TERMINATED", (
            f"Non-durable POA (FINANCIAL) should be TERMINATED, "
            f"got {poa_nd['status']!r}"
        )

        poa_d = validate_success(
            api.get_poa(ctx["poa_durable"]["id"], make_planner_headers()),
            expected_status=200,
        )
        assert poa_d["status"] == "ACTIVE", (
            f"Durable POA (DURABLE_HEALTHCARE) should remain ACTIVE, "
            f"got {poa_d['status']!r}"
        )

        ira = validate_success(
            api.get_asset(
                ctx["ira_asset"]["id"],
                make_executor_headers(ctx["executor"]["id"]),
            ),
            expected_status=200,
        )
        assert ira["status"] == "EXCLUDED", (
            f"IRA with beneficiary designation should be EXCLUDED on death, "
            f"got {ira['status']!r}"
        )

    def test_death_registration_advances_estate_status(self, api):
        """PRD §3.3: "The estate, which must currently be in ALIVE for the
        cascade to be permitted, transitions to DECEASED."

        Design: Difficulty/transitive_cascade/death_registration_cascade_depth_3
        """
        ctx = bootstrap_estate_with_non_durable_and_durable_poas()
        assert ctx["estate"]["status"] == "ALIVE"
        register_death(ctx["decedent"]["id"], "2026-02-01T00:00:00Z")
        est = validate_success(
            api.get_estate(ctx["estate"]["id"], make_planner_headers()),
            expected_status=200,
        )
        assert est["status"] == "DECEASED"


class TestCloseEstateCascadeDepth2:
    """PRD §3.8: CLOSE_ESTATE entry cascades Estate->CLOSED and
    Executor->DISCHARGED."""

    def test_close_estate_advances_estate_and_discharges_executor(self, api):
        """PRD §3.8: "On entry, the estate advances from ADMINISTRATION to
        CLOSED, Estate.closed_at is stamped with the current server time, and
        the COURT_CONFIRMED executor is automatically discharged to
        DISCHARGED."

        Design: Difficulty/transitive_cascade/close_estate_cascade_depth_2
        """
        ctx = bootstrap_estate_closed(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-15T00:00:00Z",
            asset_value_cents=1000000,
            domicile_state_code="NY",
        )
        est_id = ctx["estate"]["id"]
        exec_id = ctx["executor"]["id"]
        est = validate_success(
            api.get_estate(est_id, make_planner_headers()), expected_status=200,
        )
        assert est["status"] == "CLOSED"
        executor = validate_success(
            api.get_executor(exec_id, make_executor_headers(exec_id)),
            expected_status=200,
        )
        assert executor["status"] == "DISCHARGED", (
            f"Executor should cascade COURT_CONFIRMED->DISCHARGED on close, "
            f"got {executor['status']!r}"
        )

    def test_close_estate_stamps_closed_at(self, api):
        """PRD §3.8: "Estate.closed_at is stamped with the current server time"

        Design: Difficulty/transitive_cascade/close_estate_cascade_depth_2
        """
        ctx = bootstrap_estate_closed(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-15T00:00:00Z",
            asset_value_cents=1000000,
            domicile_state_code="NY",
        )
        est = validate_success(
            api.get_estate(ctx["estate"]["id"], make_planner_headers()),
            expected_status=200,
        )
        assert est["closed_at"] is not None, (
            "Estate.closed_at must be stamped on transition into CLOSED"
        )
