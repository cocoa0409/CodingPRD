"""Courier reputation, blacklisting, restriction gates — PRD §3.10, §3.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BLACKLIST_THRESHOLD_RATE,
    CapacityWarningLevel,
    CourierBlacklistStatus,
    advance_clock,
    advance_hours,
    blacklist_courier_payload,
    confirm_deposit,
    create_courier,
    create_machine,
    create_parcel_payload,
    deposit_parcel,
    get_courier,
    make_courier_headers,
    restrict_courier_payload,
    setup_basic_scenario,
    setup_courier_with_window_wrong_rate,
    setup_machine_at_capacity_ratio,
    setup_machine_with_compartments,
    validate_error,
    validate_success,
)


class TestCourierStartsActive:
    """PRD §3.10: 'new couriers start in blacklist_status = ACTIVE with
    blacklist_reason of null.'"""

    def test_new_courier_starts_active(self, api, operations_admin_headers):
        """PRD §3.10: 'new couriers start in blacklist_status = ACTIVE
        with blacklist_reason of null.'

        Claim: a freshly created Courier has blacklist_status=ACTIVE and
        blacklist_reason null.
        """
        c = create_courier()
        assert c["blacklist_status"] == CourierBlacklistStatus.ACTIVE.value
        assert c.get("blacklist_reason") in (None, "")


class TestManualRestrictAndBlacklist:
    """PRD §3.10: 'Operations may also manually move a courier into
    RESTRICTED with a supplied reason (recorded in blacklist_reason).' /
    'Operations may also force the transition with a manual blacklist
    call carrying a reason.'"""

    def test_manual_restrict_records_reason(
        self, api, operations_admin_headers,
    ):
        """PRD §3.10: 'Operations may also manually move a courier into
        RESTRICTED with a supplied reason (recorded in blacklist_reason).'

        Claim: POST /couriers/{id}/restrict sets status=RESTRICTED and
        records blacklist_reason from the request.
        """
        c = create_courier()
        resp = api.restrict_courier(
            c["id"],
            restrict_courier_payload(reason="manual review"),
            operations_admin_headers,
        )
        data = validate_success(resp)
        assert data["blacklist_status"] == (
            CourierBlacklistStatus.RESTRICTED.value
        )
        assert data["blacklist_reason"] == "manual review"

    def test_manual_blacklist_records_reason(
        self, api, operations_admin_headers,
    ):
        """PRD §3.10: 'Operations may also force the transition with a
        manual blacklist call carrying a reason.'

        Claim: POST /couriers/{id}/blacklist sets status=BLACKLISTED and
        records blacklist_reason.
        """
        c = create_courier()
        resp = api.blacklist_courier(
            c["id"],
            blacklist_courier_payload(reason="ban"),
            operations_admin_headers,
        )
        data = validate_success(resp)
        assert data["blacklist_status"] == (
            CourierBlacklistStatus.BLACKLISTED.value
        )
        assert data["blacklist_reason"] == "ban"


class TestBlacklistedCannotDeposit:
    """PRD §3.3: 'a courier whose blacklist_status is BLACKLISTED is
    rejected outright with ERR_COURIER_BLACKLISTED.'"""

    def test_blacklisted_courier_cannot_deposit(
        self, api, operations_admin_headers,
    ):
        """PRD §3.3: 'a courier whose blacklist_status is BLACKLISTED is
        rejected outright with ERR_COURIER_BLACKLISTED.'

        Claim: a BLACKLISTED courier's POST /parcels returns
        ERR_COURIER_BLACKLISTED regardless of machine state.
        """
        machine, _, courier = setup_basic_scenario()
        api.blacklist_courier(
            courier["id"], blacklist_courier_payload(reason="ban"),
            operations_admin_headers,
        )
        resp = api.create_parcel(
            create_parcel_payload(locker_machine_id=machine["id"]),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COURIER_BLACKLISTED.value)


class TestRestrictedSmallSizeBlocked:
    """PRD §3.3: 'a courier whose blacklist_status is RESTRICTED is also
    rejected with ERR_COURIER_BLACKLISTED whenever the requested deposit
    is at a non-NORMAL machine **or** the required_size is SMALL.'"""

    def test_restricted_small_size_returns_courier_blacklisted(
        self, api, operations_admin_headers,
    ):
        """PRD §3.3: 'a courier whose blacklist_status is RESTRICTED is
        also rejected with ERR_COURIER_BLACKLISTED whenever … the
        required_size is SMALL.'

        Claim: a RESTRICTED courier depositing required_size=SMALL at a
        NORMAL machine returns ERR_COURIER_BLACKLISTED.
        """
        machine, _, courier = setup_basic_scenario(sizes=["SMALL"])
        api.restrict_courier(
            courier["id"], restrict_courier_payload(reason="restrict"),
            operations_admin_headers,
        )
        resp = api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], required_size="SMALL",
            ),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COURIER_BLACKLISTED.value)


class TestRestrictedAtNonNormalMachineReturnsRestricted:
    """PRD §3.3: 'the dedicated identifier ERR_COURIER_RESTRICTED is
    reserved for the case where the courier is RESTRICTED and the
    machine is non-NORMAL.'"""

    def test_restricted_at_near_full_machine_returns_courier_restricted(
        self, api, operations_admin_headers,
    ):
        """PRD §3.3: 'the dedicated identifier ERR_COURIER_RESTRICTED is
        reserved for the case where the courier is RESTRICTED and the
        machine is non-NORMAL.'

        Claim: a RESTRICTED courier depositing required_size=MEDIUM at a
        machine whose capacity_warning_level is NEAR_FULL returns
        ERR_COURIER_RESTRICTED.
        """
        # Build a machine with 5 MEDIUM compartments, 4 occupied → 0.80
        # ratio → NEAR_FULL.
        machine, _, _ = setup_machine_at_capacity_ratio(
            size="MEDIUM", total=5, occupied=4,
        )
        # Restricted courier
        courier = create_courier()
        api.restrict_courier(
            courier["id"],
            restrict_courier_payload(reason="restrict"),
            operations_admin_headers,
        )
        resp = api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], required_size="MEDIUM",
            ),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COURIER_RESTRICTED.value)


class TestReinstateBackToActive:
    """PRD §3.10: 'Reinstatement returns a RESTRICTED or BLACKLISTED
    courier to ACTIVE, but only if both reputational signals have already
    cooled.'"""

    def test_reinstate_clears_reason_and_returns_active(
        self, api, operations_admin_headers,
    ):
        """PRD §3.10: 'A successful reinstatement clears blacklist_reason
        to null and appends a BLACKLIST_CHANGE AuditLog.'

        Claim: after manual restrict + reinstate (signals already cool —
        no wrong deposits, no complaints), the courier returns to ACTIVE
        and blacklist_reason is null.
        """
        c = create_courier()
        api.restrict_courier(
            c["id"], restrict_courier_payload(reason="restrict"),
            operations_admin_headers,
        )
        resp = api.reinstate_courier(c["id"], operations_admin_headers)
        data = validate_success(resp)
        assert data["blacklist_status"] == CourierBlacklistStatus.ACTIVE.value
        assert data.get("blacklist_reason") in (None, "")
