"""Non-linear state machines: the settlement dispute cycle and the lease renewal
self-loop; plus invalid-transition guards on lease activate and order accept.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    open_stall, place_order, reject_order, create_provisional_settlement,
    TEST_USERS,
)

HM = TEST_USERS["hall_manager_headers"]


class TestSettlementDisputeCycle:
    """non_linear_state_machine / settlement_dispute_cycle."""

    def _setup(self):
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        se = create_provisional_settlement(ctx["lease_id"], ctx["lease_version"])
        return ctx, se

    def test_dispute_moves_provisional_to_disputed(self, api):
        """PRD §3.8: "disputing moves a `PROVISIONAL` settlement to `DISPUTED`,
        permitted only while it is `PROVISIONAL` and only for the vendor whose `id`
        equals the settlement's lease's `vendor_id`."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_cycle
        """
        ctx, se = self._setup()
        data = validate_success(api.dispute_settlement(se["id"], ctx["vendor_headers"]), 200)
        assert data["status"] == "DISPUTED"

    def test_resolve_returns_disputed_to_provisional(self, api):
        """PRD §3.8: "A `HallManager` resolves a dispute, returning the settlement
        from `DISPUTED` back to `PROVISIONAL`; the
        `PROVISIONAL`-to-`DISPUTED`-to-`PROVISIONAL` path forms a cycle."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_cycle
        """
        ctx, se = self._setup()
        validate_success(api.dispute_settlement(se["id"], ctx["vendor_headers"]), 200)
        data = validate_success(api.resolve_dispute_settlement(se["id"], HM), 200)
        assert data["status"] == "PROVISIONAL"


class TestLeaseRenewalSelfLoop:
    """non_linear_state_machine / lease_renewal_self_loop."""

    def test_renew_keeps_lease_active(self, api):
        """PRD §3.2: "An `ACTIVE` lease can be renewed in place: renewal keeps the
        lease `ACTIVE` (an `ACTIVE`-to-`ACTIVE` self-loop) and extends its term."

        Design: Difficulty/non_linear_state_machine/lease_renewal_self_loop
        """
        ctx = open_stall()
        data = validate_success(api.renew_lease(ctx["lease_id"], "2027-06-30", HM), 200)
        assert data["status"] == "ACTIVE"

    def test_renew_extends_end_date(self, api):
        """PRD §3.2: "The request supplies a `new_end_date`, which must be strictly
        later than the lease's current `end_date`; the lease's `end_date` is
        extended to that value."

        Design: Difficulty/non_linear_state_machine/lease_renewal_self_loop
        """
        ctx = open_stall()
        data = validate_success(api.renew_lease(ctx["lease_id"], "2027-06-30", HM), 200)
        assert data["end_date"] == "2027-06-30"


def test_activate_already_active_lease_rejected(api):
    """PRD §3.2: "Activating a lease moves it from `DRAFT` to `ACTIVE` and is the
    moment a vendor takes possession of a stall. Activation is permitted only when
    the lease is in `DRAFT`; it further requires that the leasing vendor is
    currently `ACTIVE`..."
    PRD §2.10: "The target resource must be in a state that admits the requested
    transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/lease_activate_when_active_rejected
    """
    ctx = open_stall()
    res = api.activate_lease(ctx["lease_id"], HM)
    validate_error(res, "ERR_INVALID_STATE")


def test_accept_rejected_order_rejected(api):
    """PRD §3.5: "A vendor may reject an order that is in either `ROUTED` or
    `ACCEPTED` status, moving it to the terminal `REJECTED` status..."
    PRD §2.10: "The target resource must be in a state that admits the requested
    transition, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/order_accept_after_reject_rejected
    """
    ctx = open_stall(clock="2026-06-15T18:00:00Z")
    order = place_order(ctx["food_hall_id"], ctx["stall_id"])
    reject_order(order["id"], ctx["vendor_id"])

    res = api.accept_order(order["id"], ctx["vendor_headers"])
    validate_error(res, "ERR_INVALID_STATE")
