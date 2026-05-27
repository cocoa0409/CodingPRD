"""GarnishmentOrder state machine — ACTIVE ↔ SUSPENDED cyclic, RELEASED terminal."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    set_clock,
    seed_federal_and_california_2025,
    setup_employee_with_filed_w4,
    create_employee,
    create_garnishment_order,
    suspend_garnishment,
    reactivate_garnishment,
    release_garnishment,
    get_garnishment_order,
    TEST_USERS,
)


# =========================================================================
# Queue (A) Difficulty — rule 3 non_linear_state_machine (instance 2)
# =========================================================================

class TestGarnishmentCyclicActiveSuspendedActive:
    """ACTIVE → SUSPENDED → ACTIVE cycle per PRD §3.5."""

    def test_suspended_garnishment_can_reactivate_to_active(self, api):
        """PRD §3.5: "The `ComplianceOfficer` may move an `ACTIVE` order to
        `SUSPENDED` by suspending it"
        PRD §3.5: "may move a `SUSPENDED` order back to `ACTIVE` by
        reactivating it"

        Sequence: create ACTIVE → suspend → reactivate → status is ACTIVE.

        Design: Difficulty/non_linear_state_machine/garnishment_order_cyclic_active_suspended_active
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        g = create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=30000, original_balance_cents=100000,
            served_on="2025-06-01T00:00:00.000Z",
        )
        suspend_garnishment(g["id"])
        reactivate_garnishment(g["id"])

        after = get_garnishment_order(g["id"])
        assert after["status"] == "ACTIVE"


# =========================================================================
# Queue (B) Corner — state_machines
# =========================================================================

class TestGarnishmentReleaseFromActive:
    def test_release_from_active_transitions_to_released(self, api):
        """PRD §3.5: "The `ComplianceOfficer` may also release an order
        outright, transitioning to `RELEASED` from any of `ACTIVE`,
        `SATISFIED`, or `SUSPENDED`; `RELEASED` is the terminal court-ordered
        release"

        Design: Corner/state_machines/garnishment_order_release_from_active
        """
        emp = create_employee()
        g = create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=30000, original_balance_cents=100000,
            served_on="2025-06-01T00:00:00.000Z",
        )
        release_garnishment(g["id"])
        after = get_garnishment_order(g["id"])
        assert after["status"] == "RELEASED"
