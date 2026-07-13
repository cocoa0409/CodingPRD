"""Difficulty: compensating_invariant — a conserved quantity returns to its baseline
after a reversing operation: raised_cents after a refund, and slot capacity after a
placement cancel.
"""
from test_helpers import (
    validate_success,
    setup_published_campaign,
    setup_actor_trio,
    create_draft_campaign,
    make_donation,
    book_placement,
    get_campaign,
    create_feature_placement_payload,
    make_donor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestRefundConservesRaisedCents:
    """Capturing a net-10000 donation then refunding it returns raised_cents to its
    pre-donation baseline of 0."""

    def test_refund_drives_donation_to_refunded(self, api, guest_headers):
        """PRD §3.6: "Refunding is valid only while the donation is CAPTURED, otherwise
        ERR_INVALID_STATE; it drives the donation from CAPTURED to the terminal REFUNDED,
        and recomputes the campaign's raised_cents, reserve_total_cents, and both
        availability figures."

        Design: Difficulty/compensating_invariant/donation_refund_conserves_raised_cents
        """
        b = setup_published_campaign(api)
        donor_id = b["donor"]["id"]
        don = make_donation(api, b["campaign"]["id"], donor_id, 10000)
        validate_success(api.refund_donation(don["id"], make_donor_headers(donor_id)), 201)
        refreshed = validate_success(api.get_donation(don["id"], guest_headers))
        assert refreshed["status"] == "REFUNDED", (
            f"refund drives donation to REFUNDED, got {refreshed['status']}"
        )

    def test_refund_restores_raised_to_baseline(self, api):
        """PRD §2.6: "raised_cents is the sum of net_to_campaign_cents over the campaign's
        CAPTURED donations."

        Design: Difficulty/compensating_invariant/donation_refund_conserves_raised_cents
        """
        b = setup_published_campaign(api)
        camp_id = b["campaign"]["id"]
        donor_id = b["donor"]["id"]
        don = make_donation(api, camp_id, donor_id, 10000)
        assert get_campaign(api, camp_id)["raised_cents"] == 10000
        validate_success(api.refund_donation(don["id"], make_donor_headers(donor_id)), 201)
        assert get_campaign(api, camp_id)["raised_cents"] == 0, (
            "raised_cents returns to its pre-donation baseline of 0 after the refund"
        )


class TestPlacementCancelConservesSlotCapacity:
    """Cancelling a BOOKED placement over [04-01,04-08) frees the slot so an
    identical-window placement then books successfully."""

    def test_cancel_moves_placement_to_cancelled(self, api):
        """PRD §3.8: "An administrator may cancel a BOOKED placement, moving it to CANCELLED
        (only valid from BOOKED, otherwise ERR_INVALID_STATE) and freeing that slot window
        for re-booking."

        Design: Difficulty/compensating_invariant/placement_cancel_conserves_slot_capacity
        """
        org, ben, _ = setup_actor_trio(api)
        camp = create_draft_campaign(api, org["id"], ben["id"])
        p1 = book_placement(api, camp["id"], category="HOMEPAGE", slot_index=1,
                            window_start="2026-04-01T00:00:00Z", window_end="2026-04-08T00:00:00Z")
        data = validate_success(api.cancel_feature_placement(p1["id"], ADMIN))
        assert data["status"] == "CANCELLED", (
            f"cancel moves the placement to CANCELLED, got {data['status']}"
        )

    def test_cancelled_slot_can_be_rebooked(self, api):
        """PRD §3.8: "An administrator may cancel a BOOKED placement, moving it to CANCELLED
        (only valid from BOOKED, otherwise ERR_INVALID_STATE) and freeing that slot window
        for re-booking."

        Design: Difficulty/compensating_invariant/placement_cancel_conserves_slot_capacity
        """
        org, ben, _ = setup_actor_trio(api)
        camp = create_draft_campaign(api, org["id"], ben["id"])
        p1 = book_placement(api, camp["id"], category="HOMEPAGE", slot_index=1,
                            window_start="2026-04-01T00:00:00Z", window_end="2026-04-08T00:00:00Z")
        validate_success(api.cancel_feature_placement(p1["id"], ADMIN))
        p2 = validate_success(
            api.create_feature_placement(
                create_feature_placement_payload(
                    camp["id"], category="HOMEPAGE", slot_index=1,
                    window_start="2026-04-01T00:00:00Z", window_end="2026-04-08T00:00:00Z"),
                ADMIN),
            201,
        )
        assert p2["status"] == "BOOKED", (
            f"the freed slot re-books successfully, got {p2['status']}"
        )
