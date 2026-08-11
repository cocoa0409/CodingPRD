"""Cross-entity state dependencies: license status gates booking confirm;
waiver status gates claim check-in."""
from test_helpers import (
    add_claim,
    api_client,
    confirm_booking,
    get_booking,
    get_slot_claim,
    setup_in_progress_booking,
    setup_scheduling_booking,
    sign_waiver_for_claim,
    validate_error,
    validate_success,
)


class TestConfirmRequiresActiveLicense:
    def test_confirm_blocked_when_assigned_therapists_license_suspended(self, api):
        """PRD §3.2: "Suspension never unassigns chairs retroactively, but it
        blocks any later booking confirmation that depends on the license
        (§3.4)."
        PRD §3.4: "Every chair must be `ASSIGNED`; the license check is
        re-evaluated for every therapist assigned on the booking
        (`ERR_LICENSE_INVALID` on failure); and the buffer-extended
        double-booking scan is re-run across all of the booking's assigned
        therapists (`ERR_THERAPIST_DOUBLE_BOOKED` on failure)."

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_therapist_license_active
        """
        ctx = setup_scheduling_booking(assign=True)
        booking_id = ctx["booking"]["id"]
        validate_success(
            api.suspend_therapist_license(
                ctx["license"]["id"], {"reason": "audit"}, ctx["admin"],
            )
        )
        version = get_booking(ctx, booking_id)["version"]
        resp = api.confirm_booking(
            booking_id, {"expected_booking_version": version}, ctx["organizer"],
        )
        validate_error(resp, "ERR_LICENSE_INVALID", expected_status=422)
        assert get_booking(ctx, booking_id)["status"] == "SCHEDULING"

    def test_confirm_succeeds_after_license_reinstated(self, api):
        """PRD §3.2: "Suspension never unassigns chairs retroactively, but it
        blocks any later booking confirmation that depends on the license
        (§3.4)."
        PRD §3.2: "Reinstatement (`SUSPENDED` → `ACTIVE`) requires the expiry
        date to be on or after the current logical date, and clears
        `suspension_reason`."

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_therapist_license_active
        """
        ctx = setup_scheduling_booking(assign=True)
        booking_id = ctx["booking"]["id"]
        license_id = ctx["license"]["id"]
        validate_success(
            api.suspend_therapist_license(license_id, {"reason": "audit"}, ctx["admin"])
        )
        validate_success(api.reinstate_therapist_license(license_id, ctx["admin"]))
        confirmed = confirm_booking(ctx, booking_id)
        assert confirmed["status"] == "CONFIRMED", (
            "With the license ACTIVE again, confirmation must succeed"
        )


class TestCheckInRequiresActiveWaiver:
    def test_checkin_rejected_when_waiver_revoked(self, api):
        """PRD §3.6: "Check-in transitions a claim `CLAIMED` → `CHECKED_IN`
        and is permitted only while the booking is `IN_PROGRESS` and the claim
        references a waiver that has not been revoked; attempting check-in
        without one is rejected with `ERR_WAIVER_MISSING`."
        PRD §3.6: "A `PlatformAdmin` may later revoke a waiver, which stamps
        its `revoked_at`."

        Design: Difficulty/cross_entity_state_dependency/claim_checkin_requires_active_waiver
        """
        ctx = setup_in_progress_booking(num_claims=1, sign_waivers=True)
        claim = ctx["claims"][0]
        waivers = api.list_slot_claim_waivers(claim["id"], ctx["admin"]).json()["data"]
        assert len(waivers) == 1
        validate_success(api.revoke_waiver(waivers[0]["id"], ctx["admin"]))
        resp = api.check_in_slot_claim(claim["id"], ctx["organizer"])
        validate_error(resp, "ERR_WAIVER_MISSING", expected_status=422)
        assert get_slot_claim(ctx, claim["id"])["status"] == "CLAIMED"

    def test_checkin_rejected_when_no_waiver_signed(self, api):
        """PRD §3.6: "Check-in transitions a claim `CLAIMED` → `CHECKED_IN`
        and is permitted only while the booking is `IN_PROGRESS` and the claim
        references a waiver that has not been revoked; attempting check-in
        without one is rejected with `ERR_WAIVER_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/claim_checkin_requires_active_waiver
        """
        ctx = setup_in_progress_booking(num_claims=1, sign_waivers=False)
        claim = ctx["claims"][0]
        assert claim["waiver_id"] is None
        resp = api.check_in_slot_claim(claim["id"], ctx["organizer"])
        validate_error(resp, "ERR_WAIVER_MISSING", expected_status=422)
        assert get_slot_claim(ctx, claim["id"])["status"] == "CLAIMED"
