"""Difficulty Rule 7 — cross_entity_state_dependency.

Two cross-entity dependency scenarios:
  (A) Lease check-in requires Tenant.liveaboard_status == APPROVED; revoke
      mid-lifecycle cancels the reserved liveaboard lease (PRD §3.3 cascade),
      so the subsequent check-in finds the lease in CANCELLED → ERR_INVALID_STATE.
  (B) PumpOutRequest completion requires the parent Lease.status == ACTIVE;
      checking the lease out before completing the pump-out yields
      ERR_INVALID_STATE.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_marina,
    create_slip,
    revoke_liveaboard,
    reserve_lease,
    check_in_lease,
    check_out_lease,
    create_pump_out_request,
    setup_tenant_with_vessel,
    make_tenant_approved_for_liveaboard,
    ApiErrorId,
    TEST_USERS,
)


class TestLeaseCheckinAfterRevokeYieldsInvalidState:
    """Per PRD §3.3, revoking a tenant cascades CANCELLATION of their
    is_liveaboard==true RESERVED leases. The subsequent check-in then finds
    the lease in CANCELLED and returns ERR_INVALID_STATE (state check
    precedes business-safety per PRD §2.7).
    """

    def _setup_and_revoke(self):
        marina = create_marina(liveaboard_cap=3)
        slip = create_slip(
            marina["id"], slip_number="M-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            liveaboard_allowed=True,
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel(loa_ft=40, beam_ft=12)
        tenant, vessel = tv["tenant"], tv["vessel"]
        make_tenant_approved_for_liveaboard(tenant["id"], marina["id"])
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip["id"], tenant["id"], vessel["id"],
            "2026-07-10", "2026-07-15",
            slip["version"], is_liveaboard=True,
        )
        revoke_liveaboard(tenant["id"], marina["id"])
        set_clock("2026-07-10T00:00:00Z")
        return marina, tenant, lease

    def test_checkin_after_tenant_revoke_returns_invalid_state(self, api):
        """PRD §3.3: "every lease belonging to this tenant whose `is_liveaboard` is true and whose current `status` is `RESERVED` transitions to `CANCELLED`, with each cancelled lease incurring its own `version` bump."
        PRD §3.5: "Check-in is permitted only when the slip is currently `RESERVED` and the lease is currently `RESERVED`, and only when the current clock date is on or after the lease's `start_date`."

        Design: Difficulty/cross_entity_state_dependency/lease_checkin_requires_tenant_liveaboard_approved
        """
        _, _, lease = self._setup_and_revoke()
        res = api.check_in_lease(lease["id"], TEST_USERS["marina_staff_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_tenant_status_is_revoked_after_revoke(self, api):
        """PRD §3.3: "Revocation runs from `APPROVED` to `REVOKED`."

        Design: Difficulty/cross_entity_state_dependency/lease_checkin_requires_tenant_liveaboard_approved
        """
        _, tenant, _ = self._setup_and_revoke()
        res = api.get_tenant(tenant["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        assert data["liveaboard_status"] == "REVOKED", \
            f"tenant must be REVOKED, got {data['liveaboard_status']}"


class TestPumpoutCompleteRequiresLeaseActive:
    """Pump-out completion against an ENDED lease must return
    ERR_INVALID_STATE per PRD §3.6.
    """

    def _setup(self):
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="N-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            pumpout_available=True,
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel(loa_ft=40, beam_ft=12)
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip["id"], tenant["id"], vessel["id"],
            "2026-07-10", "2026-07-12", slip["version"],
        )
        set_clock("2026-07-10T00:00:00Z")
        check_in_lease(lease["id"])
        po = create_pump_out_request(lease["id"], tenant["id"])
        check_out_lease(lease["id"])
        return lease, po

    def test_pumpout_complete_after_lease_ended_returns_invalid_state(self, api):
        """PRD §3.6: "Completion requires the request to be in `PENDING` and the parent lease to be in `ACTIVE`; either violated yields `ERR_INVALID_STATE` HTTP 409."

        Design: Difficulty/cross_entity_state_dependency/pumpout_complete_requires_lease_active
        """
        _, po = self._setup()
        res = api.complete_pump_out_request(po["id"], TEST_USERS["marina_staff_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_lease_status_is_ended_after_checkout(self, api):
        """PRD §3.8: "A check-out by a `MarinaStaff` (or `HarborMaster`) operator transitions the lease from `ACTIVE` to `ENDED` and the slip from `OCCUPIED` to either `AVAILABLE` or back to `RESERVED`, depending on what the transfer waitlist holds for this slip."

        Design: Difficulty/cross_entity_state_dependency/pumpout_complete_requires_lease_active
        """
        lease, _ = self._setup()
        res = api.get_lease(lease["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ENDED", f"lease must be ENDED, got {data['status']}"
