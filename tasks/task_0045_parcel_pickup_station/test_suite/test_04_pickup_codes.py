"""Pickup code lifecycle: minting, reissuance, and voiding.

PRD §3.3 (Pickup Codes).
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_pickup_code,
    drive_parcel_to_awaiting_return,
    drive_parcel_to_overtime,
    fetch_active_pickup_code,
    find_system_events,
    list_all_pickup_codes,
    list_system_events,
    pickup_with_code,
    reissue_pickup_code,
    reissue_pickup_code_payload,
    register_shelved_parcel,
    request_return_shipment,
    setup_station_with_staff,
    ship_return,
    courier_responds,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestPickupCodeReissue:
    def test_reissue_marks_old_code_reissued_with_superseded_by(self, api):
        """PRD §3.3: "On success, the old code transitions from ACTIVE
        to REISSUED, its superseded_by is set to the new code's id, and
        a fresh code is minted under the same six-digit collision rules
        with issue_reason REISSUED_LOST."

        Claim: after one reissue request, the original code has
        status=REISSUED and superseded_by=<new code id>, and a new
        ACTIVE code exists with issue_reason=REISSUED_LOST.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        original = fetch_active_pickup_code(parcel["id"], ctx["clerk_headers"])
        new_code = reissue_pickup_code(parcel["id"])
        # The new code response: status ACTIVE, issue_reason REISSUED_LOST.
        assert new_code["status"] == "ACTIVE"
        assert new_code["issue_reason"] == "REISSUED_LOST"
        # The original code should now be REISSUED with superseded_by==new.id.
        codes = list_all_pickup_codes(parcel["id"], ctx["clerk_headers"])
        old = next(c for c in codes if c["id"] == original["id"])
        assert old["status"] == "REISSUED"
        assert old["superseded_by"] == new_code["id"]

    def test_only_one_active_code_after_reissue(self, api):
        """PRD §3.3: "at most one ACTIVE code exists per parcel at any
        moment."

        Claim: after a reissue, exactly one PickupCode for the parcel
        has status=ACTIVE.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        reissue_pickup_code(parcel["id"])
        codes = list_all_pickup_codes(parcel["id"], ctx["clerk_headers"])
        actives = [c for c in codes if c["status"] == "ACTIVE"]
        assert len(actives) == 1

    def test_reissue_emits_im_pickup_code_reissued_event(self, api):
        """PRD §3.3: "On success, the old code transitions from ACTIVE to REISSUED, its superseded_by is set to the new code's id, and a fresh code is minted under the same six-digit collision rules with issue_reason REISSUED_LOST; an IM-targeted PICKUP_CODE_REISSUED event is queued."

        Claim: GET /system-events shows one PICKUP_CODE_REISSUED row
        on IM after the reissue.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        reissue_pickup_code(parcel["id"])
        events = list_system_events()
        match = find_system_events(
            events, event_name="PICKUP_CODE_REISSUED", target_system="IM",
        )
        assert len(match) >= 1


class TestPickupCodeVoiding:
    def test_active_code_voids_on_parcel_disposed(self, api):
        """PRD §3.3: "When the parent parcel reaches the terminal
        states RETURNED or DISPOSED, any still-ACTIVE code transitions
        to VOIDED (with consumed_at explicitly set to null) and any
        still-REISSUED (older) code also transitions to VOIDED."

        Claim: after a parcel transitions to DISPOSED, the previously
        ACTIVE PickupCode row has status=VOIDED.
        """
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        parcel = drive_parcel_to_awaiting_return(ctx, parcel)
        assert parcel["status"] == "AWAITING_RETURN"
        # Advance the disposal grace window and dispose.
        from test_helpers import advance_clock_hours
        advance_clock_hours(241)  # > DISPOSAL_GRACE_HOURS=240
        disposed_resp = api.dispose_parcel(
            parcel["id"], ctx["manager_headers"],
        )
        disposed = validate_success(disposed_resp)
        assert disposed["status"] == "DISPOSED"
        codes = list_all_pickup_codes(parcel["id"], ctx["clerk_headers"])
        # Every previously ACTIVE/REISSUED code is now VOIDED.
        # (No CONSUMED row because we never picked up.)
        for c in codes:
            assert c["status"] in ("VOIDED",)

    def test_code_consumed_on_pickup(self, api):
        """PRD §3.3: "When a parcel is successfully picked up using the
        code, that code transitions from ACTIVE to CONSUMED and its
        consumed_at is stamped."

        Claim: after pickup with the code, the code is CONSUMED and
        carries an ISO 8601 consumed_at.
        """
        from test_helpers import is_iso8601_timestamp
        ctx = setup_station_with_staff()
        parcel = register_shelved_parcel(ctx)
        active = fetch_active_pickup_code(parcel["id"], ctx["clerk_headers"])
        pickup_with_code(ctx, parcel)
        codes = list_all_pickup_codes(parcel["id"], ctx["clerk_headers"])
        consumed = next(c for c in codes if c["id"] == active["id"])
        assert consumed["status"] == "CONSUMED"
        assert is_iso8601_timestamp(consumed["consumed_at"])
