"""Permit parallel state dimensions: lifecycle and financial tracks move
independently (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    validate_success,
    setup_approved_permit,
    setup_secured_permit,
    capture_deposit,
    set_clock,
    api_client,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]

EVENT_START = "2026-09-13T00:00:00Z"
EVENT_END = "2026-09-13T04:00:00Z"


class TestPermitParallelFinancialLifecycleDimensions:
    def test_deposit_capture_moves_only_financial_dimension(self, api):
        """PRD §3.5: "Every permit lives on two independent state dimensions."
        PRD §3.5: "on success the financial dimension moves `DEPOSIT_PENDING` →
        `SECURED` with `deposit_held_cents` set to the captured amount."

        Design: Difficulty/non_linear_state_machine/permit_parallel_financial_lifecycle_dimensions
        """
        env, req, permit = setup_approved_permit(
            event_title="Charity Auction", headcount_estimate=200,
            starts_at=EVENT_START, ends_at=EVENT_END)
        assert (permit["lifecycle_status"], permit["financial_status"]) == (
            "ISSUED", "DEPOSIT_PENDING")
        assert permit["deposit_held_cents"] == 0

        capture_deposit(env, permit["id"], 10000, "dep-e-1")
        after = validate_success(api.get_permit(permit["id"], DIRECTOR))
        # Financial moved; lifecycle did NOT.
        assert (after["lifecycle_status"], after["financial_status"]) == (
            "ISSUED", "SECURED")
        assert after["deposit_held_cents"] == 10000

    def test_activation_and_completion_move_dimensions_independently(self, api):
        """PRD §3.5: "When the logical clock reaches `occupancy_start` and the
        financial dimension is `SECURED`, the system moves the permit `ISSUED` →
        `ACTIVE` and starts its custodial work order."
        PRD §3.6: "Completion voids the `PROVISIONAL` invoice, generates the
        `FINAL` invoice from actuals, and moves the financial dimension to
        `INVOICED` if it is not already there."

        Design: Difficulty/non_linear_state_machine/permit_parallel_financial_lifecycle_dimensions
        """
        env, req, permit = setup_secured_permit(
            10000, idempotency_key="dep-e-2",
            event_title="Charity Auction", headcount_estimate=200,
            starts_at=EVENT_START, ends_at=EVENT_END)

        set_clock("2026-09-13T12:00:00Z")  # past occupancy_start; SECURED gate met
        active = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert (active["lifecycle_status"], active["financial_status"]) == (
            "ACTIVE", "SECURED")

        orders = validate_success(api.list_permit_work_orders(permit["id"], SUPERVISOR))
        assert orders[0]["wo_status"] == "IN_PROGRESS", (
            "activation starts the custodial work order")

        validate_success(api.complete_permit(permit["id"], COORDINATOR))
        done = validate_success(api.get_permit(permit["id"], DIRECTOR))
        # Lifecycle and financial moved via distinct triggers (the complete call;
        # FINAL invoice issuance).
        assert (done["lifecycle_status"], done["financial_status"]) == (
            "COMPLETED", "INVOICED")
