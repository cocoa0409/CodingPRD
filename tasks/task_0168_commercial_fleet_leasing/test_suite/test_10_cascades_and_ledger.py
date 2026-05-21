"""Cross-aggregate cascades and ledger integrity — PRD §2.8, §2.9, §3.8.

Covers: lessee suspend → lease DEFAULTED → fuel card BLOCKED cascade,
balance ledger conservation across approve+mark-paid, vehicle-lease
link conservation across activate+finalize-return.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to_iso,
    api_client,
    DEFAULT_THRESHOLD_CENTS,
    create_draft_settlement,
    finalize_settlement,
    get_fuel_card,
    get_lease_agreement,
    get_lessee,
    get_vehicle,
    mark_paid_settlement,
    push_outstanding_balance_via_collision,
    setup_active_lease_with_card,
    suspend_lessee,
    TEST_USERS,
    validate_success,
)


# ===========================================================================
# Suspend → DEFAULTED → BLOCKED cascade — PRD §3.8
# ===========================================================================
class TestSuspendCascade:

    def test_suspend_above_default_threshold_cascades_lease_and_card(
        self, api,
    ):
        """PRD §3.8: "the system then walks every `ACTIVE` lease the
        lessee owns and, for each one where `outstanding_balance_cents`
        has reached or crossed the (strictly higher) default
        threshold, flips that lease's `lease_state` to `DEFAULTED`,
        moves the underlying vehicle to `GROUNDED`, and blocks every
        `FuelCard` under that lease (`card_status` flips to
        `BLOCKED`)."

        Claim: suspending a lessee whose balance is at/above the
        default threshold cascades to lease.DEFAULTED, vehicle.GROUNDED,
        and card.BLOCKED.
        """
        advance_clock_to_iso("2026-03-01T00:00:00.000Z")
        lessee, vehicle, lease, card = setup_active_lease_with_card()
        # Push balance above default threshold.
        push_outstanding_balance_via_collision(
            lessee=lessee, vehicle=vehicle, lease=lease,
            deductible_cents=DEFAULT_THRESHOLD_CENTS,
        )
        # Suspend.
        suspend_lessee(lessee_id=lessee["id"])
        # Verify cascade.
        l = get_lessee(lessee["id"])
        assert l["account_status"] == "SUSPENDED", (
            f"Hop 1: lessee.account_status must be SUSPENDED, "
            f"got {l['account_status']!r}"
        )
        la = get_lease_agreement(lease["id"])
        assert la["lease_state"] == "DEFAULTED", (
            f"Hop 2: lease.lease_state must be DEFAULTED, "
            f"got {la['lease_state']!r}"
        )
        v = get_vehicle(vehicle["id"])
        assert v["vehicle_status"] == "GROUNDED", (
            f"Hop 3a: vehicle.vehicle_status must be GROUNDED, "
            f"got {v['vehicle_status']!r}"
        )
        c = get_fuel_card(card["id"])
        assert c["card_status"] == "BLOCKED", (
            f"Hop 3b: fuel card.card_status must be BLOCKED, "
            f"got {c['card_status']!r}"
        )


# ===========================================================================
# Outstanding balance conservation — PRD §2.9
# ===========================================================================
class TestBalanceConservation:

    def test_approve_then_mark_paid_returns_balance_to_origin(self, api):
        """PRD §2.9: "every approval of a `CollisionClaim` adds the
        computed `lessee_deductible_cents` to the balance, and every
        `OverageSettlement` that transitions into the paid state
        subtracts that settlement's `balance_cents` from the balance."

        Claim: approve(D) followed by a finalize+mark-paid(D) returns
        outstanding_balance_cents to its pre-approve value.
        """
        advance_clock_to_iso("2026-03-01T00:00:00.000Z")
        # Use a CLASS_5 lease so IFTA isn't involved; allowance=1000,
        # rate=25. We want a settlement balance exactly equal to the
        # deductible. Provision telematics to drive overage_miles to
        # 1200 → flat-rate balance 1200 * 25 = 30000.
        from test_helpers import setup_lease_with_period_telematics
        lessee, vehicle, lease = setup_lease_with_period_telematics(
            period_year=2026, period_month=3,
            start_odometer=0, end_odometer=2200,
            monthly_mileage_allowance=1000,
            overage_rate_cents_per_mile=25,
            tiered_overage_enabled=False,
            vehicle_class="CLASS_5",
        )
        D = 30_000  # cents
        # First push outstanding by exactly D via a collision approve.
        pre = get_lessee(lessee["id"])
        push_outstanding_balance_via_collision(
            lessee=lessee, vehicle=vehicle, lease=lease,
            deductible_cents=D,
            incident_ts="2026-03-10T12:00:00.000Z",
        )
        post_approve = get_lessee(lessee["id"])
        assert post_approve["outstanding_balance_cents"] == (
            pre["outstanding_balance_cents"] + D
        ), (
            f"approve must increment balance by {D}: pre "
            f"{pre['outstanding_balance_cents']}, post "
            f"{post_approve['outstanding_balance_cents']}"
        )
        # Now build a settlement whose balance equals D = 30000.
        advance_clock_to_iso("2026-04-01T01:00:00.000Z")
        s = create_draft_settlement(
            lease_id=lease["id"], period_year=2026, period_month=3,
        )
        s = finalize_settlement(s["id"])
        # Sanity: confirm s.balance_cents == 30000 before mark-paid.
        assert s["balance_cents"] == 30_000, (
            f"settlement balance must be 30000 to exercise the "
            f"conservation invariant; got {s['balance_cents']!r}"
        )
        mark_paid_settlement(s["id"])
        post_paid = get_lessee(lessee["id"])
        # Per PRD §2.9 mark-paid subtracts s.balance_cents (30000), so
        # outstanding returns to pre value.
        assert post_paid["outstanding_balance_cents"] == (
            pre["outstanding_balance_cents"]
        ), (
            f"approve(D) + mark-paid(D) must conserve balance: "
            f"pre {pre['outstanding_balance_cents']}, "
            f"post {post_paid['outstanding_balance_cents']}"
        )


# ===========================================================================
# Vehicle-lease link conservation — PRD §3.2, §3.8
# ===========================================================================
class TestVehicleLeaseLink:

    def test_activate_sets_link_and_initial_state_is_clean(self, api):
        """PRD §3.1: "A newly added vehicle's `vehicle_status` is
        `AVAILABLE`, its `current_lease_id` is null."
        PRD §3.2: "On success, the vehicle moves to `ALLOCATED`, its
        `current_lease_id` is set to the lease's `id`."

        Claim: a fresh vehicle starts at (null, AVAILABLE), and
        activation flips it to (lease.id, ALLOCATED).
        """
        from test_helpers import create_lessee, create_vehicle
        from test_helpers import create_lease_agreement, activate_lease
        vehicle = create_vehicle(odometer_baseline_miles=0)
        # Pre-state.
        v_pre = get_vehicle(vehicle["id"])
        assert v_pre.get("current_lease_id") is None
        assert v_pre["vehicle_status"] == "AVAILABLE"
        # Build + activate lease.
        lessee = create_lessee()
        lease = create_lease_agreement(
            lessee_id=lessee["id"], vehicle_id=vehicle["id"],
        )
        activate_lease(lease["id"])
        v_post = get_vehicle(vehicle["id"])
        assert v_post["current_lease_id"] == lease["id"]
        assert v_post["vehicle_status"] == "ALLOCATED"
