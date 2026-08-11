"""Booking / chair-slot / license / claim state-machine rules."""
from test_helpers import (
    add_claim,
    api_client,
    assign_therapist,
    confirm_booking,
    create_event_booking,
    create_therapist,
    create_therapist_license,
    drive_booking_in_progress,
    get_booking,
    get_chair,
    make_organizer_headers,
    open_booking,
    setup_in_progress_booking,
    setup_region_account_therapist,
    setup_scheduling_booking,
    sign_waiver_for_claim,
    validate_error,
    validate_success,
)


class TestBookingCreationAndInitialState:
    def test_booking_initial_state_is_draft(self, api):
        """PRD §3.3: "A new booking is stamped with `booking_kind` `EVENT`, an
        operational `status` of `DRAFT`, and a parallel `billing_status` of
        `UNBILLED`."

        Design: Corner/state_machines/booking_initial_state_is_draft
        """
        ctx = setup_region_account_therapist()
        booking = create_event_booking(ctx)
        assert booking["status"] == "DRAFT", f"Expected DRAFT, got {booking['status']}"
        assert booking["billing_status"] == "UNBILLED"
        assert booking["booking_kind"] == "EVENT"

    def test_create_booking_window_not_divisible_returns_422(self, api):
        """PRD §3.3: "The on-site window must divide evenly into whole
        sessions — `window_duration_minutes` must be an exact multiple of
        `slot_minutes` — or creation fails with `ERR_WINDOW_NOT_DIVISIBLE`;
        other malformed values, such as an out-of-range integer or a badly
        formatted date, fail with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_booking_window_not_divisible_returns_422
        """
        ctx = setup_region_account_therapist()
        resp = api.create_booking(
            {
                "corporate_account_id": ctx["account"]["id"],
                "region_id": ctx["region"]["id"],
                "site_address": "B",
                "event_date": "2026-06-10",
                "window_start_minutes": 600,
                "window_duration_minutes": 70,
                "chair_count": 1,
                "slot_minutes": 15,
                "per_minute_rate_cents": 200,
            },
            ctx["organizer"],
        )
        validate_error(resp, "ERR_WINDOW_NOT_DIVISIBLE", expected_status=422)


class TestInvalidTransitions:
    def test_cancel_booking_from_completed_returns_invalid_state(self, api):
        """PRD §3.7: "Cancellation follows a tiered policy. Cancelling from
        `DRAFT` is free and records a `cancellation_fee_cents` of 0.
        Cancelling from `SCHEDULING` is likewise free, and every `ASSIGNED`
        chair is set to `RELEASED`."
        PRD §2.8: "Fourth, for action endpoints, the target resource must be
        in a state from which the requested transition is permitted
        (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/cancel_booking_from_completed_returns_invalid_state
        """
        ctx = setup_in_progress_booking()
        validate_success(api.complete_booking(ctx["booking"]["id"], ctx["organizer"]))
        resp = api.cancel_booking(ctx["booking"]["id"], ctx["organizer"])
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    def test_license_terminal_revoked_cannot_be_reinstated(self, api):
        """PRD §3.2: "Revocation (`ACTIVE` → `REVOKED`) is terminal and
        cascades: every `ASSIGNED` chair slot staffed by that therapist whose
        booking is delivered in the license's region and whose `event_date`
        falls on or after the current logical date transitions to `RELEASED`,
        and each such release decrements the therapist's booked-minutes tally
        for that date."
        PRD §3.2: "Reinstatement (`SUSPENDED` → `ACTIVE`) requires the expiry
        date to be on or after the current logical date, and clears
        `suspension_reason`."

        Design: Corner/state_machines/license_terminal_revoked_cannot_be_reinstated
        """
        ctx = setup_region_account_therapist()
        license_id = ctx["license"]["id"]
        validate_success(api.revoke_therapist_license(license_id, ctx["admin"]))
        resp = api.reinstate_therapist_license(license_id, ctx["admin"])
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    def test_chair_slot_assign_from_assigned_returns_invalid_state(self, api):
        """PRD §3.4: "An `Organizer` assigns a therapist by naming a
        `therapist_id` for a chair that is `UNASSIGNED`, while the booking is
        `SCHEDULING`, and the candidate therapist is `ACTIVE`."
        PRD §2.8: "Fourth, for action endpoints, the target resource must be
        in a state from which the requested transition is permitted
        (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/chair_slot_assign_from_assigned_returns_invalid_state
        """
        ctx = setup_scheduling_booking(assign=True)
        chair = ctx["chairs"][0]
        other = create_therapist(ctx["region"]["id"], email="t2@test")
        create_therapist_license(other["id"], ctx["region"]["id"], license_number="LIC-2")
        resp = api.assign_chair_slot(
            chair["id"], {"therapist_id": other["id"]}, ctx["organizer"],
        )
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
        chair_after = get_chair(ctx, chair["id"])
        assert chair_after["therapist_id"] == ctx["therapist"]["id"], (
            "Rejected re-assignment must leave therapist_id unchanged"
        )

    def test_slot_claim_check_in_requires_booking_in_progress(self, api):
        """PRD §3.6: "Check-in transitions a claim `CLAIMED` → `CHECKED_IN`
        and is permitted only while the booking is `IN_PROGRESS` and the claim
        references a waiver that has not been revoked; attempting check-in
        without one is rejected with `ERR_WAIVER_MISSING`."
        PRD §2.8: "Fourth, for action endpoints, the target resource must be
        in a state from which the requested transition is permitted
        (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/slot_claim_check_in_requires_booking_in_progress
        """
        ctx = setup_scheduling_booking(assign=True)
        booking = ctx["booking"]
        chair = ctx["chairs"][0]
        claim = add_claim(ctx, chair["id"], "Recipient", "r@x")
        sign_waiver_for_claim(ctx, claim["id"], booking["id"], "r@x")
        confirm_booking(ctx, booking["id"])
        # Booking is CONFIRMED, not IN_PROGRESS: check-in must be rejected.
        resp = api.check_in_slot_claim(claim["id"], ctx["organizer"])
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    def test_booking_complete_with_outstanding_claims_rejected(self, api):
        """PRD §3.7: "Closing out the service, the `Organizer` completes the
        booking (`IN_PROGRESS` → `COMPLETED`); the transition is refused with
        `ERR_CLAIMS_OUTSTANDING` while any claim remains in `CLAIMED` or
        `CHECKED_IN`, since every claim must first reach `COMPLETED`,
        `NO_SHOW`, or `CANCELLED`."

        Design: Corner/state_machines/booking_complete_with_outstanding_claims_rejected
        """
        ctx = setup_in_progress_booking(num_claims=1, sign_waivers=False)
        resp = api.complete_booking(ctx["booking"]["id"], ctx["organizer"])
        validate_error(resp, "ERR_CLAIMS_OUTSTANDING", expected_status=422)
        booking = get_booking(ctx, ctx["booking"]["id"])
        assert booking["status"] == "IN_PROGRESS", (
            f"Rejected completion must leave status IN_PROGRESS, got {booking['status']}"
        )
