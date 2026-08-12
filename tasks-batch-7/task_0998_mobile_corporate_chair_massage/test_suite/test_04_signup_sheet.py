"""Sign-up sheet: computed ordinals, capacity boundary, per-booking email
uniqueness, and ordinal slicing semantics."""
from test_helpers import (
    add_claim,
    api_client,
    assign_therapist,
    create_therapist,
    create_therapist_license,
    get_booking,
    get_chair,
    list_booking_chairs,
    setup_scheduling_booking,
    validate_error,
)


class TestClaimComputedFields:
    def test_create_slot_claim_response_includes_computed_fields(self, api):
        """PRD §3.6: "Each new claim takes the next free `slot_ordinal`,
        defined as the current count of non-`CANCELLED` claims on that chair,
        and its `start_offset_minutes` — the point within the on-site window
        at which the session begins — is that ordinal multiplied by the
        booking's `slot_minutes`."

        Design: Corner/entities/create_slot_claim_response_includes_computed_fields
        """
        ctx = setup_scheduling_booking(assign=True)
        chair = ctx["chairs"][0]
        claim = add_claim(ctx, chair["id"], "Recipient", "r@x")
        assert claim["slot_ordinal"] == 0
        assert claim["start_offset_minutes"] == 0
        assert claim["status"] == "CLAIMED"
        assert claim["booking_id"] == ctx["booking"]["id"]


class TestOrdinalSlicing:
    def test_successive_claims_take_sequential_ordinals(self, api):
        """PRD §3.6: "Each new claim takes the next free `slot_ordinal`,
        defined as the current count of non-`CANCELLED` claims on that chair,
        and its `start_offset_minutes` — the point within the on-site window
        at which the session begins — is that ordinal multiplied by the
        booking's `slot_minutes`."

        Design: Difficulty/resource_temporal_overlap/chair_slot_ordinal_no_overlap_within_chair
        """
        ctx = setup_scheduling_booking(assign=True)
        chair = ctx["chairs"][0]
        c1 = add_claim(ctx, chair["id"], "R1", "r1@x")
        c2 = add_claim(ctx, chair["id"], "R2", "r2@x")
        c3 = add_claim(ctx, chair["id"], "R3", "r3@x")
        assert (c1["slot_ordinal"], c1["start_offset_minutes"]) == (0, 0)
        assert (c2["slot_ordinal"], c2["start_offset_minutes"]) == (1, 15)
        assert (c3["slot_ordinal"], c3["start_offset_minutes"]) == (2, 30)

    def test_cancelled_claims_do_not_count_toward_next_ordinal(self, api):
        """PRD §3.6: "Each new claim takes the next free `slot_ordinal`,
        defined as the current count of non-`CANCELLED` claims on that chair,
        and its `start_offset_minutes` — the point within the on-site window
        at which the session begins — is that ordinal multiplied by the
        booking's `slot_minutes`."

        Design: Difficulty/resource_temporal_overlap/chair_slot_ordinal_no_overlap_within_chair
        """
        ctx = setup_scheduling_booking(assign=True)
        chair = ctx["chairs"][0]
        add_claim(ctx, chair["id"], "R1", "r1@x")
        c2 = add_claim(ctx, chair["id"], "R2", "r2@x")
        api.cancel_slot_claim(c2["id"], ctx["organizer"])
        c3 = add_claim(ctx, chair["id"], "R3", "r3@x")
        # After the cancel, only one non-CANCELLED claim remains on the chair.
        assert c3["slot_ordinal"] == 1, (
            f"Cancelled claims must not count; expected ordinal 1, got {c3['slot_ordinal']}"
        )
        assert c3["start_offset_minutes"] == 15


class TestCapacityBoundary:
    def test_fourth_claim_fills_window_exactly(self, api):
        """PRD §3.6: "Two checks guard the sheet, evaluated capacity first:
        the new claim must fit the window, meaning one more than the new
        claim's `slot_ordinal`, multiplied by `slot_minutes`, must not exceed
        `window_duration_minutes` (otherwise `ERR_SIGNUP_SHEET_FULL`); and the
        `recipient_email` must not already hold a non-`CANCELLED` claim on the
        same booking (otherwise `ERR_DUPLICATE_SIGNUP`)."

        Design: Difficulty/boundary_precision_check/signup_sheet_capacity_exact_fit
        """
        ctx = setup_scheduling_booking(assign=True)
        chair = ctx["chairs"][0]  # window 60 / slot 15 -> capacity 4
        for i in range(3):
            add_claim(ctx, chair["id"], f"R{i}", f"r{i}@x")
        fourth = add_claim(ctx, chair["id"], "R3", "r3@x")
        assert fourth["slot_ordinal"] == 3, "Boundary is inclusive: (3+1)*15 <= 60 must pass"

    def test_fifth_claim_exceeds_capacity_rejected(self, api):
        """PRD §3.6: "Two checks guard the sheet, evaluated capacity first:
        the new claim must fit the window, meaning one more than the new
        claim's `slot_ordinal`, multiplied by `slot_minutes`, must not exceed
        `window_duration_minutes` (otherwise `ERR_SIGNUP_SHEET_FULL`); and the
        `recipient_email` must not already hold a non-`CANCELLED` claim on the
        same booking (otherwise `ERR_DUPLICATE_SIGNUP`)."

        Design: Difficulty/boundary_precision_check/signup_sheet_capacity_exact_fit
        """
        ctx = setup_scheduling_booking(assign=True)
        chair = ctx["chairs"][0]
        for i in range(4):
            add_claim(ctx, chair["id"], f"R{i}", f"r{i}@x")
        resp = api.create_slot_claim(
            chair["id"],
            {
                "recipient_name": "R5",
                "recipient_email": "r5@x",
                "expected_chair_slot_version": get_chair(ctx, chair["id"])["version"],
            },
            ctx["organizer"],
        )
        validate_error(resp, "ERR_SIGNUP_SHEET_FULL", expected_status=422)
        claims = api.list_chair_slot_claims(chair["id"], ctx["organizer"]).json()["data"]
        live = [c for c in claims if c["status"] != "CANCELLED"]
        assert len(live) == 4, f"Chair must still hold exactly 4 claims, got {len(live)}"


class TestDuplicateSignup:
    def test_claim_duplicate_email_on_same_booking_rejected(self, api):
        """PRD §3.6: "Two checks guard the sheet, evaluated capacity first:
        the new claim must fit the window, meaning one more than the new
        claim's `slot_ordinal`, multiplied by `slot_minutes`, must not exceed
        `window_duration_minutes` (otherwise `ERR_SIGNUP_SHEET_FULL`); and the
        `recipient_email` must not already hold a non-`CANCELLED` claim on the
        same booking (otherwise `ERR_DUPLICATE_SIGNUP`)."

        Design: Corner/validations/claim_duplicate_email_on_same_booking_rejected
        """
        ctx = setup_scheduling_booking(num_chairs=2, assign=False)
        chairs = ctx["chairs"]
        other = create_therapist(ctx["region"]["id"], email="t2@test")
        create_therapist_license(other["id"], ctx["region"]["id"], license_number="LIC-2")
        assign_therapist(ctx, chairs[0]["id"], ctx["therapist"]["id"])
        assign_therapist(ctx, chairs[1]["id"], other["id"])
        add_claim(ctx, chairs[0]["id"], "X", "x@x")
        resp = api.create_slot_claim(
            chairs[1]["id"],
            {
                "recipient_name": "X2",
                "recipient_email": "x@x",
                "expected_chair_slot_version": get_chair(ctx, chairs[1]["id"])["version"],
            },
            ctx["organizer"],
        )
        validate_error(resp, "ERR_DUPLICATE_SIGNUP", expected_status=422)
