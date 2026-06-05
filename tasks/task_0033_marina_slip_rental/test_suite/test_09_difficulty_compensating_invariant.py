"""Difficulty Rule 9 — compensating_invariant.

Two compensating-action pairs:
  (A) Cancel a RESERVED lease restores the slip to AVAILABLE — count of
      AVAILABLE slips at the marina is conserved across reserve+cancel.
  (B) Revoke then re-apply + re-approve preserves Marina.liveaboard_current_count.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_marina,
    create_slip,
    create_tenant,
    create_vessel,
    setup_tenant_with_vessel,
    apply_liveaboard,
    approve_liveaboard,
    revoke_liveaboard,
    reserve_lease,
    cancel_lease,
    TEST_USERS,
)


class TestCancelReservedLeaseRestoresSlipAvailability:
    """Lease reserve + lease cancel: the slip returns to AVAILABLE."""

    def _setup_and_cancel(self):
        marina = create_marina(liveaboard_cap=1)
        slip_1 = create_slip(
            marina["id"], slip_number="Q-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        slip_2 = create_slip(
            marina["id"], slip_number="Q-2",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel()
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip_1["id"], tenant["id"], vessel["id"],
            "2026-07-10", "2026-07-15", slip_1["version"],
        )
        cancel_lease(lease["id"], tenant["id"])
        return marina, slip_1, slip_2, lease

    def test_cancel_transitions_lease_to_cancelled(self, api):
        """PRD §3.8: "A reserved lease that has not yet been checked in may instead be cancelled by the owning tenant, transitioning the lease from `RESERVED` to `CANCELLED` and the slip from `RESERVED` back to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/cancel_reserved_lease_restores_slip_availability
        """
        _, _, _, lease = self._setup_and_cancel()
        res = api.get_lease(lease["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CANCELLED", \
            f"lease must be CANCELLED, got {data['status']}"

    def test_cancel_restores_slip_to_available(self, api):
        """PRD §3.8: "A reserved lease that has not yet been checked in may instead be cancelled by the owning tenant, transitioning the lease from `RESERVED` to `CANCELLED` and the slip from `RESERVED` back to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/cancel_reserved_lease_restores_slip_availability
        """
        _, slip_1, slip_2, _ = self._setup_and_cancel()
        # Both slips are now AVAILABLE — the conserved count of AVAILABLE slots
        # at the marina returns to its pre-reservation value.
        r1 = api.get_slip(slip_1["id"], TEST_USERS["harbor_master_headers"])
        d1 = validate_success(r1, expected_status=200)
        assert d1["status"] == "AVAILABLE", \
            f"cancelled lease must restore slip to AVAILABLE, got {d1['status']}"
        r2 = api.get_slip(slip_2["id"], TEST_USERS["harbor_master_headers"])
        d2 = validate_success(r2, expected_status=200)
        assert d2["status"] == "AVAILABLE", \
            f"unrelated slip must remain AVAILABLE, got {d2['status']}"


class TestRevokeThenReapprovePreservesMarinaCounter:
    """Approve+Revoke+ReApply+ReApprove on the same tenant preserves the
    marina's liveaboard_current_count at its pre-pair value.
    """

    def _walk_the_cycle(self):
        marina = create_marina(liveaboard_cap=3)
        tn = create_tenant(full_name="T N")
        apply_liveaboard(tn["id"], marina["id"])
        approve_liveaboard(tn["id"], marina["id"])
        # count == 1 here
        revoke_liveaboard(tn["id"], marina["id"])
        # count == 0
        apply_liveaboard(tn["id"], marina["id"])
        approve_liveaboard(tn["id"], marina["id"])
        # count == 1 again
        return marina, tn

    def test_tenant_is_approved_again_after_cycle(self, api):
        """PRD §3.3: "This re-application loop makes the tenant's liveaboard machine cyclic: a previously revoked tenant can return to the queue and be approved again."

        Design: Difficulty/compensating_invariant/revoke_then_reapprove_preserves_marina_counter
        """
        _, tn = self._walk_the_cycle()
        res = api.get_tenant(tn["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        assert data["liveaboard_status"] == "APPROVED", \
            f"tenant must be APPROVED after cycle, got {data['liveaboard_status']}"

    def test_marina_liveaboard_count_returns_to_one_after_cycle(self, api):
        """PRD §3.3: "The harbor master supplies the `marina_id` whose count was previously incremented; the system decrements that marina's `liveaboard_current_count` by 1, advances the marina's `version`, and cascades a second mutation"
        PRD §3.3: "From `PENDING`, two outcomes are reachable. A harbor master may approve, transitioning the tenant to `APPROVED`, stamping `liveaboard_approved_at` to the current UTC instant, incrementing the named marina's `liveaboard_current_count` by 1, and bumping both the tenant's and the marina's `version`."

        Design: Difficulty/compensating_invariant/revoke_then_reapprove_preserves_marina_counter
        """
        marina, _ = self._walk_the_cycle()
        res = api.get_marina(marina["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        # Pre-cycle: count was 1 after first approve; cycle nets 0; +1 again on re-approve.
        assert data["liveaboard_current_count"] == 1, \
            f"count must return to 1 after revoke+re-apply+re-approve, got {data['liveaboard_current_count']}"
