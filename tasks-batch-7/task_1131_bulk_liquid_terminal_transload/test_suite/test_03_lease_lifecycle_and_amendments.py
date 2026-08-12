"""Lease lifecycle cycle, reserved-capacity invariant, lazy expiry, and
amendment optimistic concurrency (PRD §2.4, §2.5, §3.2, §3.3, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_customer,
    create_lease,
    get_lease,
    is_valid_uuid,
    make_customer_rep_headers,
    propose_amendment,
    setup_lease_with_allocation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    MANAGER,
    OPERATOR,
    activate_allocation,
    create_allocation,
    create_tank,
    release_allocation,
    set_clock,
    suspend_lease,
    reactivate_lease,
    terminate_lease,
)


def _suspendable_lease():
    return setup_lease_with_allocation(product_grade="JET", capacity_bbl=80000, heel_bbl=50,
                                       allocated_bbl=30000, customer_name="Harbor Trading",
                                       lease_overrides={"throughput_fee_per_bbl": 0.60,
                                                        "shortfall_fee_per_bbl": 0.60,
                                                        "loss_allowance_pct": 0.004,
                                                        "excess_loss_rate_per_bbl": 70.00,
                                                        "min_monthly_throughput_bbl": 500})


class TestLeaseSuspendReactivateCycle:
    def test_suspend_records_manual_reason(self, api):
        """PRD §3.2: "From `ACTIVE`, a manager may suspend the lease, which
        records `suspension_reason` as `MANUAL`; the system itself may also
        suspend an `ACTIVE` lease when a recomputed open statement's excess
        loss breaches the cap described in §3.8, in which case
        `suspension_reason` is recorded as `LOSS_CONTROL`."

        Design: Difficulty/non_linear_state_machine/lease_suspend_reactivate_cycle
        """
        bundle = _suspendable_lease()
        suspended = suspend_lease(bundle["lease"]["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL", (
            f"operator suspend must record MANUAL, got {suspended['suspension_reason']}"
        )

    def test_reactivate_closes_cycle_and_clears_reason(self, api):
        """PRD §3.2: "A suspended lease may be reactivated by a manager, which
        clears `suspension_reason` back to null." The ACTIVE -> SUSPENDED ->
        ACTIVE loop is legal; the lease returns to ACTIVE without recreation.

        Design: Difficulty/non_linear_state_machine/lease_suspend_reactivate_cycle
        """
        bundle = _suspendable_lease()
        suspend_lease(bundle["lease"]["id"])
        reactivated = reactivate_lease(bundle["lease"]["id"])
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["suspension_reason"] is None, (
            f"reactivate must clear suspension_reason, got {reactivated['suspension_reason']}"
        )
        reread = get_lease(bundle["lease"]["id"])
        assert reread["status"] == "ACTIVE"
        assert reread["suspension_reason"] is None


class TestReservedCapacityInvariant:
    def _draft_lease_with_reserved_allocation(self):
        customer = create_customer(name="Frontier Oil", contact_email="capacity@frontier.example")
        tank = create_tank(capacity_bbl=200000, heel_bbl=100)
        lease = create_lease(customer["id"], committed_capacity_bbl=100000)
        allocation = create_allocation(lease["id"], tank["id"], allocated_bbl=10000)
        return customer, tank, lease, allocation

    def test_activate_allocation_recomputes_reserved_capacity(self, api):
        """PRD §3.4: "Activation recomputes the lease's `reserved_capacity_bbl`
        as the sum of `allocated_bbl` over the lease's `ACTIVE` allocations and
        increments the lease's `version` by 1."
        A fresh lease starts at reserved_capacity_bbl 0; activating the 10000
        bbl allocation raises it to 10000.

        Design: Difficulty/compensating_invariant/activate_then_release_leaves_reserved_capacity_unchanged
        """
        _, _, lease, allocation = self._draft_lease_with_reserved_allocation()
        before = get_lease(lease["id"])
        assert before["reserved_capacity_bbl"] == 0
        activate_allocation(allocation["id"])
        mid = get_lease(lease["id"])
        assert mid["reserved_capacity_bbl"] == 10000, (
            f"activation must add allocated_bbl, got {mid['reserved_capacity_bbl']}"
        )

    def test_release_restores_reserved_capacity_to_zero(self, api):
        """PRD §3.4: "Release — the compensating action of activation — moves
        an `ACTIVE` allocation to `RELEASED`, but only when no movement on the
        same lease-and-tank pair is in `SCHEDULED`, `ARRIVED`, `IN_PROGRESS`,
        or `SUSPENDED` status; otherwise the release is rejected with
        `ERR_INVALID_STATE`. Release likewise recomputes the lease's
        `reserved_capacity_bbl` and increments its `version`."
        The forward activation (+10000) paired with its compensating release
        leaves reserved_capacity_bbl identical to the pre-activation value.

        Design: Difficulty/compensating_invariant/activate_then_release_leaves_reserved_capacity_unchanged
        """
        _, _, lease, allocation = self._draft_lease_with_reserved_allocation()
        activate_allocation(allocation["id"])
        released = release_allocation(allocation["id"])
        assert released["status"] == "RELEASED"
        after = get_lease(lease["id"])
        assert after["reserved_capacity_bbl"] == 0, (
            f"release must restore reserved_capacity_bbl to 0, got {after['reserved_capacity_bbl']}"
        )


class TestTerminalLockdown:
    def test_suspend_from_terminated_rejected(self, api):
        """PRD §3.2: "Termination releases every allocation of the lease that
        is `RESERVED` or `ACTIVE` into `RELEASED` and recomputes
        `reserved_capacity_bbl` to 0."
        PRD §2.9: "then state-machine from-state matching (`ERR_INVALID_STATE`)"
        — TERMINATED is terminal, so a later suspend is rejected.

        Design: Corner/state_machines/lease_suspend_from_terminated_rejected
        """
        bundle = setup_lease_with_allocation(customer_name="Terminal Co", allocated_bbl=10000)
        terminate_lease(bundle["lease"]["id"])
        resp = api.suspend_lease(bundle["lease"]["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        lease = get_lease(bundle["lease"]["id"])
        assert lease["status"] == "TERMINATED"
        assert lease["reserved_capacity_bbl"] == 0
        alloc = validate_success(api.get_tank_allocation(bundle["allocation"]["id"], OPERATOR))
        assert alloc["status"] == "RELEASED", "terminate must cascade-release the allocation"


class TestLazyExpiry:
    def test_lease_expires_when_clock_passes_end_date(self, api):
        """PRD §2.4: "A lease whose `end_date` is earlier than the current
        logical clock date transitions from `ACTIVE` or `SUSPENDED` to
        `EXPIRED` the next time the lease is read or its state is evaluated as
        a precondition."

        Design: Corner/state_machines/lease_expires_when_clock_passes_end_date
        """
        customer = create_customer(name="Expiry Co", contact_email="ex@example.com")
        tank = create_tank()
        lease = create_lease(customer["id"], start_date="2026-01-01", end_date="2026-05-31")
        alloc = create_allocation(lease["id"], tank["id"], allocated_bbl=10000,
                                  period_start="2026-01-01", period_end="2026-05-31")
        activate_allocation(alloc["id"])
        activate = validate_success(api.activate_lease(lease["id"], MANAGER))
        assert activate["status"] == "ACTIVE"
        set_clock("2026-06-15T00:00:00Z")
        lease_after = get_lease(lease["id"])
        assert lease_after["status"] == "EXPIRED", (
            f"lazy expiry must apply on read once end_date has passed, got {lease_after['status']}"
        )


class TestAmendmentOcc:
    def _active_lease(self):
        bundle = setup_lease_with_allocation(customer_name="OCC Co")
        return bundle

    def test_stale_expected_version_rejected(self, api):
        """PRD §2.5: "If the lease's current `version` has advanced beyond that
        value — because another amendment was proposed, an allocation was
        activated or released, or the lease was suspended, reactivated, or
        otherwise mutated — the proposal is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the rejected proposal is not persisted."
        PRD §3.3: "the act of proposing itself increments the lease's `version`
        by 1, because a live proposal legitimately supersedes the prior
        negotiation basis."

        Design: Corner/cross_cutting_layers/stale_version_occ_on_amendment_create
        """
        bundle = self._active_lease()
        lease_id = bundle["lease"]["id"]
        customer_id = bundle["customer"]["id"]
        observed = get_lease(lease_id)["version"]
        first = propose_amendment(lease_id, customer_id, observed,
                                  proposed_throughput_fee_per_bbl=0.55)
        assert is_valid_uuid(first["id"])
        assert first["base_lease_version"] == observed
        assert first["status"] == "PROPOSED"
        resp = api.create_lease_amendment(
            lease_id,
            {"expected_lease_version": observed, "proposed_min_monthly_throughput_bbl": 200},
            make_customer_rep_headers(customer_id))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

    def test_stale_base_rejected_at_approval_latest_applies(self, api):
        """PRD §3.3: "If the lease has moved on since the proposal — through
        any version-incrementing mutation — approval fails with
        `ERR_AMENDMENT_STALE_BASE` (HTTP 409). On a successful approval, each
        non-null proposed field is applied onto the lease and the lease's
        `version` increments by 1 again."

        Design: Corner/cross_cutting_layers/amendment_approval_stale_base_rejected
        """
        bundle = setup_lease_with_allocation(customer_name="Amend Co")
        lease_id = bundle["lease"]["id"]
        customer_id = bundle["customer"]["id"]
        v1 = get_lease(lease_id)["version"]
        a1 = propose_amendment(lease_id, customer_id, v1, proposed_throughput_fee_per_bbl=0.55)
        v2 = get_lease(lease_id)["version"]
        assert v2 == v1 + 1, "the proposal itself increments the lease version"
        a2 = propose_amendment(lease_id, customer_id, v2, proposed_committed_capacity_bbl=75000)
        # A1's base is superseded by A2's proposal: approval of A1 must fail.
        resp1 = api.approve_amendment(a1["id"], MANAGER)
        validate_error(resp1, ApiErrorId.ERR_AMENDMENT_STALE_BASE)
        assert resp1.status_code == 409
        from test_helpers import validate_paginated
        amendments, _meta = validate_paginated(api.list_lease_amendments(lease_id, MANAGER))
        a1_row = [a for a in amendments if a["id"] == a1["id"]][0]
        assert a1_row["status"] == "PROPOSED"
        # A2 is the live proposal: approval applies the proposed capacity.
        approved = validate_success(api.approve_amendment(a2["id"], MANAGER))
        assert approved["status"] == "APPROVED"
        lease_after = get_lease(lease_id)
        assert lease_after["committed_capacity_bbl"] == 75000, (
            f"approved proposal must apply onto the lease, got {lease_after['committed_capacity_bbl']}"
        )
