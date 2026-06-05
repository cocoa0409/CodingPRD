"""Corner — state_machines section.

Invalid transitions and terminal-state lockdowns.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_marina,
    create_slip,
    create_tenant,
    create_vessel,
    setup_tenant_with_vessel,
    reserve_lease,
    check_in_lease,
    check_out_lease,
    create_transfer_waitlist_entry,
    ApiErrorId,
    TEST_USERS,
)


class TestLeaseCancelFromActiveReturnsInvalidState:

    def test_cancel_active_lease_returns_invalid_state(self, api):
        """PRD §3.8: "Cancellation requires the lease to be in `RESERVED` and the slip in `RESERVED`; either violated yields `ERR_INVALID_STATE` HTTP 409."

        Design: Corner/state_machines/lease_cancel_from_active_returns_invalid_state
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="X-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel()
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip["id"], tenant["id"], vessel["id"],
            "2026-07-10", "2026-07-15", slip["version"],
        )
        set_clock("2026-07-10T00:00:00Z")
        check_in_lease(lease["id"])  # lease ACTIVE
        from test_helpers import make_tenant_headers
        res = api.cancel_lease(lease["id"], make_tenant_headers(tenant["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestTerminalStateEndedLocksLease:

    def test_check_in_on_ended_lease_returns_invalid_state(self, api):
        """PRD §3.5: "Check-in is permitted only when the slip is currently `RESERVED` and the lease is currently `RESERVED`, and only when the current clock date is on or after the lease's `start_date`."

        Design: Corner/state_machines/terminal_state_ended_locks_lease
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="T-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel()
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip["id"], tenant["id"], vessel["id"],
            "2026-07-10", "2026-07-12", slip["version"],
        )
        set_clock("2026-07-10T00:00:00Z")
        check_in_lease(lease["id"])
        check_out_lease(lease["id"])  # lease now ENDED
        res = api.check_in_lease(lease["id"], TEST_USERS["marina_staff_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestSlipDecommissionBlockedWhenReservedLeaseExists:

    def test_decommission_with_reserved_lease_returns_invalid_state(self, api):
        """PRD §3.1: "Decommissioning is a harbor-master-only capability and requires that the slip currently be `AVAILABLE` and that no lease referencing it is in `RESERVED` or `ACTIVE`; either condition violated yields `ERR_INVALID_STATE` HTTP 409."

        Design: Corner/state_machines/slip_decommission_blocked_when_reserved_or_active_lease_exists
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="D-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel()
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-07-01T00:00:00Z")
        reserve_lease(
            marina["id"], slip["id"], tenant["id"], vessel["id"],
            "2026-07-10", "2026-07-12", slip["version"],
        )
        # Slip now RESERVED.
        res = api.decommission_slip(slip["id"], TEST_USERS["harbor_master_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestWaitlistExpireStaleMovesOldEntriesToExpired:

    def test_old_queued_waitlist_entry_transitions_to_expired_on_sweep(self, api):
        """PRD §3.9: "A harbor master may run a sweep that expires every `QUEUED` entry whose age — the difference between the current UTC instant and the entry's `requested_at` — is greater than or equal to `WAITLIST_TTL_DAYS` days, advancing each matching entry to `EXPIRED` and recomputing positions for the remaining `QUEUED` entries."

        Design: Corner/state_machines/waitlist_expire_stale_moves_old_entries_to_expired
        """
        marina = create_marina(liveaboard_cap=1)
        slip_a = create_slip(
            marina["id"], slip_number="E-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        slip_b = create_slip(
            marina["id"], slip_number="E-2",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tv = setup_tenant_with_vessel()
        tenant, vessel = tv["tenant"], tv["vessel"]
        set_clock("2026-07-01T00:00:00Z")
        lease = reserve_lease(
            marina["id"], slip_a["id"], tenant["id"], vessel["id"],
            "2026-07-10", "2026-12-31", slip_a["version"],
        )
        set_clock("2026-07-10T00:00:00Z")
        check_in_lease(lease["id"])
        entry = create_transfer_waitlist_entry(
            marina_id=marina["id"],
            tenant_id=tenant["id"],
            from_lease_id=lease["id"],
            target_slip_id=slip_b["id"],
        )
        # Advance the clock far enough that any reasonable TTL has passed
        # (well past 60 days; PRD does not pin the constant but the design
        # advances 153 days to make the sweep deterministic).
        set_clock("2026-12-01T00:00:00Z")
        api.expire_stale_transfer_waitlist(TEST_USERS["harbor_master_headers"])
        res = api.get_transfer_waitlist_entry(
            entry["id"], TEST_USERS["harbor_master_headers"]
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "EXPIRED", \
            f"stale entry must move to EXPIRED, got {data['status']}"
