"""Fixed validation-priority ordering (PRD §2.10): when two checks both fail on one
request, the higher-priority error is the one returned. Each pair also carries a
control where only the lower-priority check fails, proving it would otherwise fire.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    open_stall, create_draft_lease, create_order_payload,
    TEST_USERS,
)

HM = TEST_USERS["hall_manager_headers"]
HI = TEST_USERS["health_inspector_headers"]
POS = TEST_USERS["pos_operator_headers"]


class TestOrderStateBeatsTemporal:
    """priority_pair_validation_conflict / order_state_beats_temporal. State
    precondition (priority 7) outranks temporal window (priority 10)."""

    def test_suspended_and_out_of_hours_returns_stall_suspended(self, api):
        """PRD §2.10: "The target resource must be in a state that admits the
        requested transition, else `ERR_INVALID_STATE` (409). Domain-specific state
        failures use their own codes: `ERR_VENDOR_NOT_ACTIVE` when activating a lease
        whose vendor is not `ACTIVE`, `ERR_STALL_SUSPENDED` when routing an order to
        a `SUSPENDED` stall..."
        PRD §2.10: "An order must be placed within operating hours (else
        `ERR_OUTSIDE_OPERATING_HOURS`, 409)..."

        Design: Difficulty/priority_pair_validation_conflict/order_state_beats_temporal
        """
        # clock 05:00 (300 min) is before hall open 480; revoke permit -> SUSPENDED.
        ctx = open_stall(clock="2026-06-15T05:00:00Z")
        validate_success(api.revoke_permit(ctx["permit_id"], HI), 200)

        res = api.create_order(
            create_order_payload(ctx["food_hall_id"], ctx["stall_id"]), POS)
        validate_error(res, "ERR_STALL_SUSPENDED")

    def test_control_out_of_hours_alone_returns_operating_hours(self, api):
        """PRD §2.10: "An order must be placed within operating hours (else
        `ERR_OUTSIDE_OPERATING_HOURS`, 409)..."

        Design: Difficulty/priority_pair_validation_conflict/order_state_beats_temporal
        """
        # Stall left OPEN; only the temporal check fails at 05:00.
        ctx = open_stall(clock="2026-06-15T05:00:00Z")
        res = api.create_order(
            create_order_payload(ctx["food_hall_id"], ctx["stall_id"]), POS)
        validate_error(res, "ERR_OUTSIDE_OPERATING_HOURS")


class TestLeaseSafetyBeatsReferential:
    """priority_pair_validation_conflict / lease_safety_beats_referential. Health
    gate (priority 8) outranks referential business rule (priority 9)."""

    def test_permit_not_issued_and_already_leased_returns_permit_not_issued(self, api):
        """PRD §2.10: "On lease activation, the stall's latest health permit must be
        `ISSUED`, else `ERR_PERMIT_NOT_ISSUED` (409)."
        PRD §2.10: "On lease activation, the stall must not already carry another
        `ACTIVE` lease, else `ERR_STALL_ALREADY_LEASED` (409)..."

        Design: Difficulty/priority_pair_validation_conflict/lease_safety_beats_referential
        """
        ctx = open_stall()
        validate_success(api.revoke_permit(ctx["permit_id"], HI), 200)
        lease2 = create_draft_lease(ctx["stall_id"], ctx["vendor_id"],
                                    start_date="2027-01-01", end_date="2027-12-31")
        res = api.activate_lease(lease2["id"], HM)
        validate_error(res, "ERR_PERMIT_NOT_ISSUED")

    def test_control_already_leased_alone_returns_already_leased(self, api):
        """PRD §2.10: "On lease activation, the stall must not already carry another
        `ACTIVE` lease, else `ERR_STALL_ALREADY_LEASED` (409)..."

        Design: Difficulty/priority_pair_validation_conflict/lease_safety_beats_referential
        """
        # Permit left ISSUED so the health gate passes; only referential fails.
        ctx = open_stall()
        lease2 = create_draft_lease(ctx["stall_id"], ctx["vendor_id"],
                                    start_date="2027-01-01", end_date="2027-12-31")
        res = api.activate_lease(lease2["id"], HM)
        validate_error(res, "ERR_STALL_ALREADY_LEASED")
