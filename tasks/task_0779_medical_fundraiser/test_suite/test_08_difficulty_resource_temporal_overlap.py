"""Difficulty: resource_temporal_overlap — half-open interval geometry on feature
slots, and the minimum-gap buffer semantics of the beneficiary payout cooldown.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_actor_trio,
    create_draft_campaign,
    book_placement,
    create_feature_placement_payload,
    setup_settled_payout_scenario,
    campaign_version,
    create_payout_payload,
    make_organizer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestFeatureSlotHalfOpenOverlap:
    """On HOMEPAGE slot 1 an existing BOOKED window [04-01,04-08): an overlapping
    [04-05,04-10) is rejected; an abutting [04-08,04-10) is allowed."""

    def test_overlapping_window_rejected(self, api):
        """PRD §3.8: "A given surface-and-slot pair — the combination of category and
        slot_index — is exclusive: a new placement whose window overlaps that of an existing
        BOOKED placement on the same category and slot_index is rejected with
        ERR_SLOT_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/feature_slot_halfopen_overlap
        """
        org, ben, _ = setup_actor_trio(api)
        camp = create_draft_campaign(api, org["id"], ben["id"])
        book_placement(api, camp["id"], category="HOMEPAGE", slot_index=1,
                       window_start="2026-04-01T00:00:00Z", window_end="2026-04-08T00:00:00Z")
        resp = api.create_feature_placement(
            create_feature_placement_payload(
                camp["id"], category="HOMEPAGE", slot_index=1,
                window_start="2026-04-05T00:00:00Z", window_end="2026-04-10T00:00:00Z"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_CONFLICT, 409)

    def test_abutting_window_allowed(self, api):
        """PRD §3.8: "Because the windows are half-open, two placements that merely abut —
        one ending exactly when the next begins — do not conflict."

        Design: Difficulty/resource_temporal_overlap/feature_slot_halfopen_overlap
        """
        org, ben, _ = setup_actor_trio(api)
        camp = create_draft_campaign(api, org["id"], ben["id"])
        book_placement(api, camp["id"], category="HOMEPAGE", slot_index=1,
                       window_start="2026-04-01T00:00:00Z", window_end="2026-04-08T00:00:00Z")
        data = validate_success(
            api.create_feature_placement(
                create_feature_placement_payload(
                    camp["id"], category="HOMEPAGE", slot_index=1,
                    window_start="2026-04-08T00:00:00Z", window_end="2026-04-10T00:00:00Z"),
                ADMIN),
            201,
        )
        assert data["status"] == "BOOKED", (
            f"an abutting placement books successfully, got {data['status']}"
        )


class TestPayoutCooldownMinGapBuffer:
    """After a payout settles at 2026-05-01T00:00:00Z, a second payout scheduled 12h
    later is rejected, but one scheduled exactly 24h later (the boundary) is allowed."""

    def test_schedule_within_cooldown_rejected(self, api):
        """PRD §3.7: "And a cooldown applies between successive withdrawals to the same
        beneficiary: if the beneficiary's last_payout_settled_at is not null, the earliest
        permissible schedule is that timestamp plus a full day — 24 hours — and a scheduled_at
        strictly earlier than that boundary is refused with ERR_PAYOUT_COOLDOWN; a scheduled_at
        exactly at the boundary is allowed."

        Design: Difficulty/resource_temporal_overlap/payout_cooldown_min_gap_buffer
        """
        s = setup_settled_payout_scenario(api, clock_iso="2026-05-01T00:00:00Z")
        camp_id = s["camp_id"]
        resp = api.create_payout(
            create_payout_payload(camp_id, 1000, campaign_version(api, camp_id),
                                  scheduled_at="2026-05-01T12:00:00Z"),
            make_organizer_headers(s["organizer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYOUT_COOLDOWN, 409)

    def test_schedule_at_boundary_allowed(self, api):
        """PRD §3.7: "a scheduled_at strictly earlier than that boundary is refused with
        ERR_PAYOUT_COOLDOWN; a scheduled_at exactly at the boundary is allowed."

        Design: Difficulty/resource_temporal_overlap/payout_cooldown_min_gap_buffer
        """
        s = setup_settled_payout_scenario(api, clock_iso="2026-05-01T00:00:00Z")
        camp_id = s["camp_id"]
        data = validate_success(
            api.create_payout(
                create_payout_payload(camp_id, 1000, campaign_version(api, camp_id),
                                      scheduled_at="2026-05-02T00:00:00Z"),
                make_organizer_headers(s["organizer"]["id"])),
            201,
        )
        assert data["status"] == "REQUESTED", (
            f"a payout at exactly the 24h boundary is accepted, got {data['status']}"
        )
