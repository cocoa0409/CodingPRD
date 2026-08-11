"""Travel-leg variant lifecycle at confirm/complete, and payout-ledger
earnings with per-line rounding."""
from test_helpers import (
    add_claim,
    assign_therapist,
    check_in_claim,
    complete_booking,
    complete_claim,
    create_therapist,
    create_therapist_license,
    drive_booking_in_progress,
    get_booking,
    list_booking_chairs,
    setup_completed_booking,
    setup_scheduling_booking,
    sign_waiver_for_claim,
    validate_success,
)


class TestTravelLegVariantLifecycle:
    def test_confirm_creates_quoted_planned_leg_per_assigned_therapist(self, api):
        """PRD §3.4: "A successful confirmation creates the travel plan: for
        each assigned therapist, a travel leg is created in `PLANNED` status
        with `travel_fee_variant` `QUOTED`, provided none already exists for
        that booking-and-therapist pair."

        Design: Difficulty/dual_variant_calc/travel_fee_quoted_vs_settled_volume_discount
        """
        ctx = setup_scheduling_booking(assign=True)
        booking_id = ctx["booking"]["id"]
        version = get_booking(ctx, booking_id)["version"]
        validate_success(api.confirm_booking(
            booking_id, {"expected_booking_version": version}, ctx["organizer"],
        ))
        legs = api.list_booking_travel_legs(booking_id, ctx["admin"]).json()["data"]
        assert len(legs) == 1, f"One leg per assigned therapist, got {len(legs)}"
        leg = legs[0]
        assert leg["therapist_id"] == ctx["therapist"]["id"]
        assert leg["status"] == "PLANNED"
        assert leg["travel_fee_variant"] == "QUOTED"

    def test_complete_flips_leg_to_settled_and_reimbursed(self, api):
        """PRD §3.7: "Completion settles the money. Each travel leg still
        `PLANNED` is recomputed under the `SETTLED` variant: the billable
        distance is again the `distance_miles` reduced by the region's
        `travel_included_miles`, floored at zero, multiplied by the
        `base_mileage_rate_cents` — but when the therapist completed twenty
        or more sessions on this booking, a high-volume discount of twenty
        percent of that base amount, floored to whole cents, is subtracted.
        The leg's `travel_fee_variant` flips to `SETTLED` and its status to
        `REIMBURSED`."
        PRD §3.7: "Completion also posts the payout ledger: one `EARNING`
        entry per therapist with at least one `COMPLETED` claim on the
        booking, and one `TRAVEL_REIMBURSEMENT` entry per leg moving to
        `REIMBURSED`."

        Design: Difficulty/dual_variant_calc/travel_fee_quoted_vs_settled_volume_discount
        """
        ctx = setup_completed_booking(num_claims_completed=1)
        booking_id = ctx["booking"]["id"]
        legs = api.list_booking_travel_legs(booking_id, ctx["admin"]).json()["data"]
        assert len(legs) == 1
        leg = legs[0]
        assert leg["travel_fee_variant"] == "SETTLED", (
            f"Completion recomputes legs under the SETTLED variant, "
            f"got {leg['travel_fee_variant']}"
        )
        assert leg["status"] == "REIMBURSED"
        # One TRAVEL_REIMBURSEMENT ledger entry per leg moving to REIMBURSED.
        entries = api.list_therapist_payout_ledger_entries(
            ctx["therapist"]["id"], ctx["admin"],
            params={"entry_kind": "TRAVEL_REIMBURSEMENT", "booking_id": booking_id},
        ).json()["data"]
        assert len(entries) == 1
        assert entries[0]["therapist_id"] == ctx["therapist"]["id"]
        assert entries[0]["booking_id"] == booking_id


class TestPayoutEarningsPerLineRounding:
    def test_earning_amount_sums_per_line_rounded_values(self, api):
        """PRD §3.7: "The earning amount pins per-line rounding: for each of
        the therapist's completed claims on the booking, the line is the
        booking's `slot_minutes` multiplied by the therapist's
        `per_hour_rate_cents` divided by sixty minutes per hour, rounded
        half-up to whole cents; the entry's amount is the integer sum of
        those per-line amounts."

        Design: Difficulty/combinatorial_formula/payout_earnings_per_line_rounding_mode_b
        """
        # rate 5001c/hr, slot 15 min: line = round_half_up(15*5001/60)
        # = round_half_up(1250.125) = 1250; seven lines sum to 8750.
        # (Sum-then-round would give round(8750.875) = 8751.)
        ctx = setup_completed_booking(
            num_claims_completed=7,
            booking_overrides={"window_duration_minutes": 120},
            therapist_overrides={
                "per_hour_rate_cents": 5001,
                "max_minutes_per_day": 2000,
            },
        )
        entries = api.list_therapist_payout_ledger_entries(
            ctx["therapist"]["id"], ctx["admin"],
            params={"entry_kind": "EARNING", "booking_id": ctx["booking"]["id"]},
        ).json()["data"]
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 8750, (
            f"Per-line rounding: 7 * 1250 = 8750 expected, "
            f"got {entries[0]['amount_cents']} (8751 indicates sum-then-round)"
        )

    def test_one_earning_entry_per_therapist_with_completed_claims(self, api):
        """PRD §3.7: "Completion also posts the payout ledger: one `EARNING`
        entry per therapist with at least one `COMPLETED` claim on the
        booking, and one `TRAVEL_REIMBURSEMENT` entry per leg moving to
        `REIMBURSED`."
        PRD §3.7: "The earning amount pins per-line rounding: for each of the
        therapist's completed claims on the booking, the line is the
        booking's `slot_minutes` multiplied by the therapist's
        `per_hour_rate_cents` divided by sixty minutes per hour, rounded
        half-up to whole cents; the entry's amount is the integer sum of
        those per-line amounts."

        Design: Difficulty/combinatorial_formula/payout_earnings_per_line_rounding_mode_b
        """
        # Two chairs, two therapists, one completed claim each.
        ctx = setup_scheduling_booking(num_chairs=2, assign=False)
        t2 = create_therapist(ctx["region"]["id"], email="t2@test")
        create_therapist_license(t2["id"], ctx["region"]["id"], license_number="LIC-2")
        chair_a, chair_b = ctx["chairs"][0], ctx["chairs"][1]
        assign_therapist(ctx, chair_a["id"], ctx["therapist"]["id"])
        assign_therapist(ctx, chair_b["id"], t2["id"])
        booking_id = ctx["booking"]["id"]
        chairs = list_booking_chairs(ctx, booking_id)
        drive_booking_in_progress(ctx, booking_id, chairs)
        for chair, therapist_id in (
            (chair_a, ctx["therapist"]["id"]), (chair_b, t2["id"]),
        ):
            claim = add_claim(ctx, chair["id"], f"R-{chair['chair_index']}", f"r{chair['chair_index']}@x")
            sign_waiver_for_claim(ctx, claim["id"], booking_id, claim["recipient_email"])
            check_in_claim(ctx, claim["id"])
            complete_claim(ctx, claim["id"], therapist_id=therapist_id)
        complete_booking(ctx, booking_id)
        for therapist_id in (ctx["therapist"]["id"], t2["id"]):
            entries = api.list_therapist_payout_ledger_entries(
                therapist_id, ctx["admin"],
                params={"entry_kind": "EARNING", "booking_id": booking_id},
            ).json()["data"]
            assert len(entries) == 1, (
                f"Exactly one EARNING entry per therapist with COMPLETED claims; "
                f"therapist {therapist_id} has {len(entries)}"
            )
            assert entries[0]["therapist_id"] == therapist_id
            assert entries[0]["booking_id"] == booking_id
            assert entries[0]["amount_cents"] > 0
