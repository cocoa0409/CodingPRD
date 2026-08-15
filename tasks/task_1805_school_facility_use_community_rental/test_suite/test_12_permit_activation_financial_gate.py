"""Permit activation is gated on the financial dimension: the same clock event
activates a SECURED permit and lapses a DEPOSIT_PENDING one (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success,
    invoice_of_kind,
    make_booking_env, make_approved_permit_in_env,
    capture_deposit, set_clock, get_single_work_order,
    api_client,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]


class TestPermitActivationGatedOnFinancialDimension:
    def test_secured_permit_activates_at_occupancy_start(self, api):
        """PRD §3.5: "When the logical clock reaches `occupancy_start` and the
        financial dimension is `SECURED`, the system moves the permit `ISSUED` →
        `ACTIVE` and starts its custodial work order."

        Design: Difficulty/cross_entity_state_dependency/permit_activation_gated_on_financial_dimension
        """
        env = make_booking_env()
        req, permit = make_approved_permit_in_env(
            env, event_title="Night One", headcount_estimate=100,
            starts_at="2026-09-13T00:00:00Z", ends_at="2026-09-13T03:00:00Z")
        capture_deposit(env, permit["id"], 10000, "dep-h-1")
        assert permit["lifecycle_status"] == "ISSUED"

        set_clock("2026-09-15T00:00:00Z")  # past occupancy_start
        after = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert after["lifecycle_status"] == "ACTIVE"
        assert after["financial_status"] == "SECURED"
        order = get_single_work_order(permit["id"])
        assert order["wo_status"] == "IN_PROGRESS", "activation starts the work order"

    def test_unsecured_permit_lapses_to_expired(self, api):
        """PRD §3.5: "If the clock passes `occupancy_start` while the deposit is
        still `DEPOSIT_PENDING` — the deposit was never secured — the permit
        lapses to `EXPIRED`: its `PROVISIONAL` invoice is voided, its work order
        is cancelled, and the freed interval triggers a waitlist promotion sweep."

        Design: Difficulty/cross_entity_state_dependency/permit_activation_gated_on_financial_dimension
        """
        env = make_booking_env()
        req, permit = make_approved_permit_in_env(
            env, event_title="Night Two", headcount_estimate=100,
            starts_at="2026-09-14T00:00:00Z", ends_at="2026-09-14T03:00:00Z")
        # Deposit never captured: the financial dimension stays DEPOSIT_PENDING.

        set_clock("2026-09-15T00:00:00Z")  # same clock event as the SECURED case
        after = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert after["lifecycle_status"] == "EXPIRED"

        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        prov = invoice_of_kind(invoices, "PROVISIONAL")
        assert prov["invoice_status"] == "VOID", "lapse voids the provisional invoice"
        order = get_single_work_order(permit["id"])
        assert order["wo_status"] == "CANCELLED", "lapse cancels the work order"
