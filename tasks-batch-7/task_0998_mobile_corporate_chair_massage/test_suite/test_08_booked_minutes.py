"""Booked-chair-minutes as a conserved quantity: claim/cancel pairs and
no-show reconciliation."""
from test_helpers import (
    add_claim,
    get_booking,
    set_clock,
    setup_in_progress_booking,
    setup_scheduling_booking,
    validate_success,
)


class TestBookedMinutesClaimCancelInvariant:
    def test_booked_minutes_invariant_under_claim_and_cancel(self, api):
        """PRD §3.6: "A created claim begins `CLAIMED`, carries its
        `chair_slot_id` plus a denormalized `booking_id` for direct
        filtered-list reads, has a null `waiver_id`, and its arrival adds the
        booking's `slot_minutes` to `booked_chair_minutes`, incrementing both
        the chair's and the booking's `version` — the latter being a
        derived-field mutation."
        PRD §3.7: "An `Organizer` may cancel a `CLAIMED` claim while the
        booking is `SCHEDULING`, `CONFIRMED`, or `IN_PROGRESS`, moving it to
        `CANCELLED`, or mark it `NO_SHOW`; either way the claim leaves the
        booked-minutes tally, which is recomputed, and both versions
        increment again."

        Design: Difficulty/compensating_invariant/booked_minutes_invariant_under_claim_and_cancel
        """
        ctx = setup_scheduling_booking(assign=True)
        booking_id = ctx["booking"]["id"]
        chair_id = ctx["chairs"][0]["id"]
        add_claim(ctx, chair_id, "R1", "r1@x")
        pre = get_booking(ctx, booking_id)["booked_chair_minutes"]
        assert pre == 15, f"One claim on a 15-minute slot -> 15 booked minutes, got {pre}"
        c2 = add_claim(ctx, chair_id, "R2", "r2@x")
        mid = get_booking(ctx, booking_id)["booked_chair_minutes"]
        assert mid == 30, f"Second claim -> 30 booked minutes, got {mid}"
        validate_success(api.cancel_slot_claim(c2["id"], ctx["organizer"]))
        post = get_booking(ctx, booking_id)["booked_chair_minutes"]
        assert post == pre, (
            f"Invariant violated: after claim+cancel pair, booked minutes "
            f"must return to {pre}, got {post}"
        )

    def test_claim_and_cancel_each_increment_booking_version(self, api):
        """PRD §3.6: "A created claim begins `CLAIMED`, carries its
        `chair_slot_id` plus a denormalized `booking_id` for direct
        filtered-list reads, has a null `waiver_id`, and its arrival adds the
        booking's `slot_minutes` to `booked_chair_minutes`, incrementing both
        the chair's and the booking's `version` — the latter being a
        derived-field mutation."
        PRD §3.7: "An `Organizer` may cancel a `CLAIMED` claim while the
        booking is `SCHEDULING`, `CONFIRMED`, or `IN_PROGRESS`, moving it to
        `CANCELLED`, or mark it `NO_SHOW`; either way the claim leaves the
        booked-minutes tally, which is recomputed, and both versions
        increment again."

        Design: Difficulty/compensating_invariant/booked_minutes_invariant_under_claim_and_cancel
        """
        ctx = setup_scheduling_booking(assign=True)
        booking_id = ctx["booking"]["id"]
        chair_id = ctx["chairs"][0]["id"]
        v0 = get_booking(ctx, booking_id)["version"]
        claim = add_claim(ctx, chair_id, "R1", "r1@x")
        v1 = get_booking(ctx, booking_id)["version"]
        assert v1 == v0 + 1, (
            f"Claim creation is a derived-field mutation: version {v0} -> {v1}"
        )
        validate_success(api.cancel_slot_claim(claim["id"], ctx["organizer"]))
        v2 = get_booking(ctx, booking_id)["version"]
        assert v2 == v1 + 1, (
            f"Claim cancellation recomputes the tally and bumps version: {v1} -> {v2}"
        )


class TestBookedMinutesNoShowReconciliation:
    def test_derived_field_booked_minutes_reconciled_on_mark_no_show(self, api):
        """PRD §3.7: "An `Organizer` may cancel a `CLAIMED` claim while the
        booking is `SCHEDULING`, `CONFIRMED`, or `IN_PROGRESS`, moving it to
        `CANCELLED`, or mark it `NO_SHOW`; either way the claim leaves the
        booked-minutes tally, which is recomputed, and both versions
        increment again."
        PRD §3.7: "The `booked_chair_minutes` tally, by contrast, sums
        `slot_minutes` over claims in `CLAIMED`, `CHECKED_IN`, or `COMPLETED`
        status and does not change at completion."

        Design: Corner/cross_cutting_layers/derived_field_booked_minutes_reconciled_on_mark_no_show
        """
        ctx = setup_in_progress_booking(num_claims=1, sign_waivers=False)
        booking_id = ctx["booking"]["id"]
        claim = ctx["claims"][0]
        pre = get_booking(ctx, booking_id)["booked_chair_minutes"]
        assert pre == 15
        # Move the logical clock past the event date: claim-level no-show
        # marking is a post-event operation.
        set_clock("2026-06-11T00:00:00Z")
        validate_success(api.mark_slot_claim_no_show(claim["id"], ctx["organizer"]))
        post = get_booking(ctx, booking_id)["booked_chair_minutes"]
        assert post == 0, (
            f"NO_SHOW claims leave the booked-minutes tally: expected 0, got {post}"
        )
