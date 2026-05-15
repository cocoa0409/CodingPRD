"""Transfer-order lifecycle: notify-agency, complete-handover (with
real-estate tenancy guard), confirm-completion, handover spacing
buffer (PRD §3.11)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    ASSET_PROFILE_TO_AGENCY,
    HANDOVER_BUFFER_HOURS,
    advance_clock_to,
    api_client,
    assert_transfer_order,
    complete_handover,
    complete_handover_payload,
    confirm_transfer_completion,
    create_transfer_order_payload,
    get_lot,
    initiate_transfer_order,
    iso_utc,
    notify_agency,
    setup_paid_payment,
    setup_transfer_completed,
    setup_transfer_notified,
    setup_transfer_order_initiated,
    utcnow,
    validate_error,
    validate_success,
)


def _parse(value):
    from datetime import datetime
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# ===========================================================================
# TransferOrder creation — PRD §3.11
# ===========================================================================
class TestTransferOrderInitiation:

    def test_counterpart_agency_derived_from_asset_profile_real_estate(
        self, api,
    ):
        """PRD §3.11: "The `counterpart_agency` is derived from the parent `Lot.asset_profile` on creation: `REAL_ESTATE` maps to `REAL_ESTATE_REGISTRY."

        Claim: REAL_ESTATE Lot → TransferOrder.counterpart_agency ==
        REAL_ESTATE_REGISTRY.
        """
        _lot, _auction, _confirmation, transfer = (
            setup_transfer_order_initiated(asset_profile="REAL_ESTATE")
        )
        assert transfer["counterpart_agency"] == "REAL_ESTATE_REGISTRY"

    def test_counterpart_agency_derived_from_asset_profile_vehicle(self, api):
        """PRD §3.11: "`VEHICLE` to `VEHICLE_AUTHORITY."

        Claim: VEHICLE Lot → counterpart_agency == VEHICLE_AUTHORITY.
        """
        _lot, _auction, _confirmation, transfer = (
            setup_transfer_order_initiated(asset_profile="VEHICLE")
        )
        assert transfer["counterpart_agency"] == "VEHICLE_AUTHORITY"

    def test_counterpart_agency_derived_from_asset_profile_movable(self, api):
        """PRD §3.11: "`MOVABLE_ASSET` to `COURT_BAILIFF."

        Claim: MOVABLE_ASSET Lot → counterpart_agency == COURT_BAILIFF.
        """
        _lot, _auction, _confirmation, transfer = (
            setup_transfer_order_initiated(asset_profile="MOVABLE_ASSET")
        )
        assert transfer["counterpart_agency"] == "COURT_BAILIFF"


# ===========================================================================
# Agency-notify transition — PRD §3.11
# ===========================================================================
class TestNotifyAgency:

    def test_notify_transitions_to_agency_notified(self, api):
        """PRD §3.11: "An `AuctionAdmin` notifies the counterpart registry, transitioning to `AGENCY_NOTIFIED`; this requires the parent `Confirmation.status` to be `ISSUED` or `SEALED`, the matched `Payment.status` to be `PAID`, and `transfer_instrument_uri` to be non-empty."

        Claim: notify → status=AGENCY_NOTIFIED.
        """
        _lot, _auction, _confirmation, transfer = setup_transfer_notified()
        assert transfer["status"] == "AGENCY_NOTIFIED"


# ===========================================================================
# Real-estate tenancy guard — PRD §3.11
# ===========================================================================
class TestRealEstateTenancyGuard:

    def test_real_estate_complete_handover_without_tenancy_rejected(
        self, api,
    ):
        """PRD §3.11: "For real-estate lots, it additionally requires `tenancy_cleared` to be true; a `REAL_ESTATE` order whose tenancy is not cleared is rejected with `ERR_TENANCY_NOT_CLEARED."

        Claim: REAL_ESTATE handover with tenancy_cleared=false →
        ERR_TENANCY_NOT_CLEARED.
        """
        handover_at = utcnow() + timedelta(hours=1)
        _lot, _auction, _confirmation, transfer = setup_transfer_notified(
            asset_profile="REAL_ESTATE",
            handover_at=handover_at,
            tenancy_cleared=False,
        )
        # Advance clock so handover_scheduled_at is reached.
        advance_clock_to(handover_at + timedelta(seconds=1))
        resp = api.complete_handover(
            transfer["id"],
            headers={
                "X-User-ID": "admin-001",
                "X-User-Role": "AuctionAdmin",
                "Content-Type": "application/json",
            },
            payload=complete_handover_payload(tenancy_cleared=False),
        )
        validate_error(resp, ApiErrorId.ERR_TENANCY_NOT_CLEARED.value)

    def test_vehicle_handover_without_tenancy_field_succeeds(self, api):
        """PRD §3.11: tenancy_cleared is required only for REAL_ESTATE.
        For other asset profiles the field is irrelevant.

        Claim: VEHICLE handover succeeds even when tenancy_cleared is
        not set.
        """
        handover_at = utcnow() + timedelta(hours=1)
        _lot, _auction, _confirmation, transfer = setup_transfer_notified(
            asset_profile="VEHICLE",
            handover_at=handover_at,
        )
        advance_clock_to(handover_at + timedelta(seconds=1))
        done = complete_handover(transfer["id"])
        assert done["status"] == "HANDOVER_DONE"


# ===========================================================================
# Handover-buffer spacing — PRD §3.11
# ===========================================================================
class TestHandoverBuffer:

    def test_handover_within_buffer_rejected(self, api):
        """PRD §3.11: "Two transfer orders on the same `counterpart_agency` whose `handover_scheduled_at` values fall on the same calendar day must be at least four hours apart (the agency-handover buffer); two handovers exactly four hours apart are allowed (half-open interval semantics — touching at the buffer boundary is permitted). Closer spacing is rejected with `ERR_HANDOVER_AGENCY_BUSY."

        Claim: second handover at gap 3h59m on same agency same day →
        ERR_HANDOVER_AGENCY_BUSY.
        """
        # Two REAL_ESTATE lots through paid payments.
        _lot1, _a1, _bidders1, _wb1, conf1, _payment1 = setup_paid_payment(
            asset_profile="REAL_ESTATE",
            num_bidders=1,
            assessment_value_cents=100_000_000,
            deposit_mode="FIXED",
            deposit_fixed_cents=5_000_000,
        )
        _lot2, _a2, _bidders2, _wb2, conf2, _payment2 = setup_paid_payment(
            asset_profile="REAL_ESTATE",
            num_bidders=1,
            assessment_value_cents=100_000_000,
            deposit_mode="FIXED",
            deposit_fixed_cents=5_000_000,
        )
        # Anchor T to a fixed mid-day UTC instant tomorrow so the
        # second handover at T+3h59m lands on the same calendar day
        # regardless of when the test happens to run.
        tomorrow = (utcnow() + timedelta(days=1)).date()
        from datetime import datetime as _dt, time as _time, timezone as _tz
        t = _dt.combine(tomorrow, _time(8, 0, 0), tzinfo=_tz.utc)
        # First transfer order: handover at T.
        initiate_transfer_order(
            confirmation_id=conf1["id"],
            handover_scheduled_at=iso_utc(t),
            tenancy_cleared=True,
        )
        # Second transfer order: handover at T + 3h59m → ERR_HANDOVER_AGENCY_BUSY.
        resp = api.create_transfer_order(
            create_transfer_order_payload(
                confirmation_id=conf2["id"],
                handover_scheduled_at=iso_utc(t + timedelta(hours=3,
                                                            minutes=59)),
                tenancy_cleared=True,
            ),
            {"X-User-ID": "admin-001",
             "X-User-Role": "AuctionAdmin",
             "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_HANDOVER_AGENCY_BUSY.value)


# ===========================================================================
# Confirm completion → Lot bubble to TRANSFERRED — PRD §3.11
# ===========================================================================
class TestTransferCompletion:

    def test_confirm_completion_transitions_lot_to_transferred(self, api):
        """PRD §3.11: "Finally, the `CourtClerk` confirms completion, moving the order from `HANDOVER_DONE` to `COMPLETED`. The transition bubbles the parent `Lot.status` to `TRANSFERRED."

        Claim: confirm-completion → TransferOrder.status=COMPLETED and
        Lot.status=TRANSFERRED.
        """
        lot, _auction, _confirmation, transfer = setup_transfer_completed(
            asset_profile="VEHICLE",
        )
        assert transfer["status"] == "COMPLETED"
        assert lot["status"] == "TRANSFERRED", (
            f"Expected Lot.status == TRANSFERRED, got {lot['status']}"
        )
