"""Difficulty Rule 4 — transitive_cascade.

Two transitive-cascade chains:
  (A) Check-out triggers three hops: Lease ACTIVE→ENDED, marina counter
      decrement, then waitlist head QUEUED→PROMOTED.
  (B) Tenant liveaboard revoke cascades to cancel RESERVED liveaboard leases.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_marina,
    create_slip,
    create_tenant,
    create_vessel,
    apply_liveaboard,
    approve_liveaboard,
    reserve_lease,
    check_in_lease,
    create_transfer_waitlist_entry,
    setup_tenant_with_vessel,
    make_tenant_approved_for_liveaboard,
    TEST_USERS,
)


class TestCheckoutTriggersThreeHopCascadeToWaitlist:
    """Slip A is OCCUPIED by L1 (liveaboard); L2 (T7 on slip B) holds an
    ACTIVE lease at the marina; T7 has a QUEUED waitlist entry targeting slip A.
    Check out L1 -> Lease ENDED, marina count decrements, waitlist head PROMOTED.
    """

    def _build_three_hop_scenario(self):
        marina = create_marina(liveaboard_cap=2)
        slip_a = create_slip(
            marina["id"],
            slip_number="G-A",
            length_ft=50, beam_ft=15, power_amp="A50",
            pumpout_available=True, liveaboard_allowed=True,
            base_daily_rate_cents=5000,
        )
        slip_b = create_slip(
            marina["id"],
            slip_number="G-B",
            length_ft=50, beam_ft=15, power_amp="A50",
            pumpout_available=True, liveaboard_allowed=False,
            base_daily_rate_cents=5000,
        )
        # T6 will hold the OCCUPIED liveaboard lease on Slip A.
        t6 = create_tenant(full_name="T Six")
        # T7 will hold an ACTIVE lease on Slip B and a waitlist entry to Slip A.
        t7 = create_tenant(full_name="T Seven")
        v6 = create_vessel(t6["id"], name="V6", loa_ft=40, beam_ft=12)
        v7 = create_vessel(t7["id"], name="V7", loa_ft=40, beam_ft=12)
        # T6 approved for liveaboard at marina.
        apply_liveaboard(t6["id"], marina["id"])
        approve_liveaboard(t6["id"], marina["id"])
        set_clock("2026-07-01T00:00:00Z")
        l1 = reserve_lease(
            marina["id"], slip_a["id"], t6["id"], v6["id"],
            "2026-07-10", "2026-07-15",
            slip_a["version"], is_liveaboard=True,
        )
        l2 = reserve_lease(
            marina["id"], slip_b["id"], t7["id"], v7["id"],
            "2026-07-10", "2026-07-20",
            slip_b["version"], is_liveaboard=False,
        )
        set_clock("2026-07-10T00:00:00Z")
        check_in_lease(l1["id"])  # Slip A -> OCCUPIED, marina count == 1
        check_in_lease(l2["id"])  # Slip B -> OCCUPIED
        # T7 queues a transfer to Slip A.
        w1 = create_transfer_waitlist_entry(
            marina_id=marina["id"],
            tenant_id=t7["id"],
            from_lease_id=l2["id"],
            target_slip_id=slip_a["id"],
        )
        return marina, slip_a, l1, w1

    def test_checkout_transitions_lease_to_ended(self, api):
        """PRD §3.8: "First, the lease transitions to `ENDED` and its `version` is bumped."

        Design: Difficulty/transitive_cascade/checkout_triggers_three_hop_cascade_to_waitlist
        """
        _, _, l1, _ = self._build_three_hop_scenario()
        res = api.check_out_lease(l1["id"], TEST_USERS["marina_staff_headers"])
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ENDED", f"hop 1: lease must be ENDED, got {data['status']}"

    def test_checkout_decrements_marina_liveaboard_count(self, api):
        """PRD §3.8: "Second, if the lease's `is_liveaboard` is true, the marina's `liveaboard_current_count` is decremented by 1 and the marina's `version` is bumped."

        Design: Difficulty/transitive_cascade/checkout_triggers_three_hop_cascade_to_waitlist
        """
        marina, _, l1, _ = self._build_three_hop_scenario()
        api.check_out_lease(l1["id"], TEST_USERS["marina_staff_headers"])
        res = api.get_marina(marina["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        # After check-out of the only liveaboard lease, count returns to 0.
        assert data["liveaboard_current_count"] == 0, \
            f"hop 2: liveaboard count decrement, got {data['liveaboard_current_count']}"

    def test_checkout_promotes_waitlist_head_and_reserves_slip(self, api):
        """PRD §3.8: "If the candidate set is non-empty, the head entry — the row with the earliest `requested_at` (and earliest `created_at` on ties) — transitions from `QUEUED` to `PROMOTED`, the slip transitions to `RESERVED` (re-using the same `AVAILABLE → RESERVED` move that a fresh reservation would make), the promoted entry's `version` is bumped, and the slip's `version` is bumped."

        Design: Difficulty/transitive_cascade/checkout_triggers_three_hop_cascade_to_waitlist
        """
        _, slip_a, l1, w1 = self._build_three_hop_scenario()
        api.check_out_lease(l1["id"], TEST_USERS["marina_staff_headers"])
        # Waitlist head PROMOTED.
        res_w = api.get_transfer_waitlist_entry(w1["id"], TEST_USERS["harbor_master_headers"])
        d_w = validate_success(res_w, expected_status=200)
        assert d_w["status"] == "PROMOTED", \
            f"hop 3: waitlist head must be PROMOTED, got {d_w['status']}"
        # Slip transitioned to RESERVED (not AVAILABLE) because head was promoted.
        res_s = api.get_slip(slip_a["id"], TEST_USERS["harbor_master_headers"])
        d_s = validate_success(res_s, expected_status=200)
        assert d_s["status"] == "RESERVED", \
            f"slip must be RESERVED after head promotion, got {d_s['status']}"


class TestLiveaboardRevokeCancelsReservedLeases:
    """Tenant T8 is APPROVED with a RESERVED liveaboard lease. Revocation:
    Tenant -> REVOKED (hop 1); marina counter decrement + RESERVED liveaboard
    leases -> CANCELLED (hop 2).
    """

    def _approved_tenant_with_reserved_liveaboard_lease(self):
        marina = create_marina(liveaboard_cap=3)
        slip = create_slip(
            marina["id"],
            slip_number="H-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            liveaboard_allowed=True,
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel(loa_ft=40, beam_ft=12)
        tenant = tv["tenant"]
        vessel = tv["vessel"]
        make_tenant_approved_for_liveaboard(tenant["id"], marina["id"])
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip["id"], tenant["id"], vessel["id"],
            "2026-08-01", "2026-08-05",
            slip["version"], is_liveaboard=True,
        )
        return marina, tenant, lease

    def test_revoke_transitions_tenant_to_revoked(self, api):
        """PRD §3.3: "Revocation runs from `APPROVED` to `REVOKED`."

        Design: Difficulty/transitive_cascade/liveaboard_revoke_cancels_reserved_leases
        """
        marina, tenant, _ = self._approved_tenant_with_reserved_liveaboard_lease()
        res = api.revoke_liveaboard(
            tenant["id"],
            {"marina_id": marina["id"]},
            TEST_USERS["harbor_master_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["liveaboard_status"] == "REVOKED", \
            f"tenant must be REVOKED, got {data['liveaboard_status']}"

    def test_revoke_decrements_marina_liveaboard_count(self, api):
        """PRD §3.3: "The harbor master supplies the `marina_id` whose count was previously incremented; the system decrements that marina's `liveaboard_current_count` by 1, advances the marina's `version`, and cascades a second mutation: every lease belonging to this tenant whose `is_liveaboard` is true and whose current `status` is `RESERVED` transitions to `CANCELLED`, with each cancelled lease incurring its own `version` bump."

        Design: Difficulty/transitive_cascade/liveaboard_revoke_cancels_reserved_leases
        """
        marina, tenant, _ = self._approved_tenant_with_reserved_liveaboard_lease()
        api.revoke_liveaboard(
            tenant["id"],
            {"marina_id": marina["id"]},
            TEST_USERS["harbor_master_headers"],
        )
        res_m = api.get_marina(marina["id"], TEST_USERS["harbor_master_headers"])
        d_m = validate_success(res_m, expected_status=200)
        assert d_m["liveaboard_current_count"] == 0, \
            f"counter must be 0 after revoke, got {d_m['liveaboard_current_count']}"

    def test_revoke_cascades_cancellation_of_reserved_liveaboard_lease(self, api):
        """PRD §3.3: "every lease belonging to this tenant whose `is_liveaboard` is true and whose current `status` is `RESERVED` transitions to `CANCELLED`, with each cancelled lease incurring its own `version` bump."

        Design: Difficulty/transitive_cascade/liveaboard_revoke_cancels_reserved_leases
        """
        marina, tenant, lease = self._approved_tenant_with_reserved_liveaboard_lease()
        api.revoke_liveaboard(
            tenant["id"],
            {"marina_id": marina["id"]},
            TEST_USERS["harbor_master_headers"],
        )
        res_l = api.get_lease(lease["id"], TEST_USERS["harbor_master_headers"])
        d_l = validate_success(res_l, expected_status=200)
        assert d_l["status"] == "CANCELLED", \
            f"RESERVED liveaboard lease must be CANCELLED, got {d_l['status']}"
