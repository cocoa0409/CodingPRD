"""Optimistic concurrency: stale-version rejections and their precedence
against state-machine checks."""
from test_helpers import (
    add_claim,
    assign_therapist,
    confirm_booking,
    get_booking,
    get_chair,
    setup_scheduling_booking,
    validate_error,
    validate_success,
)


class TestStaleBookingVersionOnConfirm:
    def test_optimistic_concurrency_stale_booking_version_on_confirm(self, api):
        """PRD §2.7: "Confirming a booking
        (`POST /chair-massage/bookings/{id}/confirm`) takes a non-optional
        `expected_booking_version` field carrying the booking's `version` as
        the client last read it. If the booking's current `version` has
        advanced since that read — for example because a chair was assigned
        or released in the meantime — the confirmation is rejected with
        `ERR_STALE_BOOKING_VERSION` (HTTP 412), since the client's picture of
        which chairs are staffed is stale."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_booking_version_on_confirm
        """
        ctx = setup_scheduling_booking(assign=False)
        booking_id = ctx["booking"]["id"]
        stale_version = get_booking(ctx, booking_id)["version"]
        # Assigning a chair advances the booking's version (PRD §2.7).
        assign_therapist(ctx, ctx["chairs"][0]["id"], ctx["therapist"]["id"])
        resp = api.confirm_booking(
            booking_id, {"expected_booking_version": stale_version}, ctx["organizer"],
        )
        validate_error(resp, "ERR_STALE_BOOKING_VERSION", expected_status=412)
        assert get_booking(ctx, booking_id)["status"] == "SCHEDULING"

    def test_fresh_booking_version_confirms_successfully(self, api):
        """PRD §2.7: "Confirming a booking
        (`POST /chair-massage/bookings/{id}/confirm`) takes a non-optional
        `expected_booking_version` field carrying the booking's `version` as
        the client last read it."
        PRD §3.4: "Confirmation moves the booking `SCHEDULING` → `CONFIRMED`."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_booking_version_on_confirm
        """
        ctx = setup_scheduling_booking(assign=True)
        booking_id = ctx["booking"]["id"]
        version = get_booking(ctx, booking_id)["version"]
        resp = api.confirm_booking(
            booking_id, {"expected_booking_version": version}, ctx["organizer"],
        )
        confirmed = validate_success(resp, expected_status=200)
        assert confirmed["status"] == "CONFIRMED"


class TestStaleChairSlotVersionOnClaim:
    def test_optimistic_concurrency_stale_chair_slot_version_on_claim(self, api):
        """PRD §2.7: "Creating a sign-up-sheet claim
        (`POST /chair-massage/chair-slots/{id}/claims`) likewise takes a
        non-optional `expected_chair_slot_version` matching the chair slot's
        current `version`; a mismatch is rejected with
        `ERR_STALE_CHAIR_SLOT_VERSION` (HTTP 412), because another claim,
        cancellation, or no-show marking on the same chair has advanced the
        chair's version and rendered the writer's view of the next free slot
        stale."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_chair_slot_version_on_claim
        """
        ctx = setup_scheduling_booking(assign=True)
        chair_id = ctx["chairs"][0]["id"]
        stale_version = get_chair(ctx, chair_id)["version"]
        # A successful claim advances the chair's version.
        add_claim(ctx, chair_id, "R1", "r1@x")
        resp = api.create_slot_claim(
            chair_id,
            {
                "recipient_name": "R2",
                "recipient_email": "r2@x",
                "expected_chair_slot_version": stale_version,
            },
            ctx["organizer"],
        )
        validate_error(resp, "ERR_STALE_CHAIR_SLOT_VERSION", expected_status=412)


class TestStateCheckPrecedesVersionCheck:
    def test_invalid_state_reported_over_stale_version_on_confirm(self, api):
        """PRD §2.8: "Fourth, for action endpoints, the target resource must
        be in a state from which the requested transition is permitted
        (`ERR_INVALID_STATE`, HTTP 409). Fifth, where an endpoint requires an
        expected-version field, the version must match
        (`ERR_STALE_BOOKING_VERSION` or `ERR_STALE_CHAIR_SLOT_VERSION`, HTTP
        412)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_stale_version_on_confirm
        """
        ctx = setup_scheduling_booking(assign=True)
        booking_id = ctx["booking"]["id"]
        stale_version = get_booking(ctx, booking_id)["version"]
        confirm_booking(ctx, booking_id)  # now CONFIRMED, version advanced again
        # Both checks would fail (wrong state AND stale version); the state
        # check is earlier in the pipeline and must surface.
        resp = api.confirm_booking(
            booking_id, {"expected_booking_version": stale_version}, ctx["organizer"],
        )
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
        assert get_booking(ctx, booking_id)["status"] == "CONFIRMED"

    def test_invalid_state_reported_even_with_current_version_on_confirm(self, api):
        """PRD §2.8: "Fourth, for action endpoints, the target resource must
        be in a state from which the requested transition is permitted
        (`ERR_INVALID_STATE`, HTTP 409). Fifth, where an endpoint requires an
        expected-version field, the version must match
        (`ERR_STALE_BOOKING_VERSION` or `ERR_STALE_CHAIR_SLOT_VERSION`, HTTP
        412)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_stale_version_on_confirm
        """
        ctx = setup_scheduling_booking(assign=True)
        booking_id = ctx["booking"]["id"]
        confirm_booking(ctx, booking_id)
        current_version = get_booking(ctx, booking_id)["version"]
        # Even with a fresh version, a CONFIRMED booking cannot be confirmed
        # again: the state check fires regardless of the OCC match.
        resp = api.confirm_booking(
            booking_id, {"expected_booking_version": current_version}, ctx["organizer"],
        )
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
        assert get_booking(ctx, booking_id)["status"] == "CONFIRMED"
