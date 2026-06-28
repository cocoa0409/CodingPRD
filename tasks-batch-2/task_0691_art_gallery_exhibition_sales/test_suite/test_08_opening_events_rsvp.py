"""Opening receptions and seat allocation: party-size-weighted waitlisting, the
promotion-on-cancel cascade, and the RSVP deadline guard."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_gallery, create_exhibition, create_opening_event, create_rsvp, set_clock,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
SALES = TEST_USERS["sales_associate_headers"]


class TestSeatAllocation:
    def test_waitlisted_when_full_then_promoted_on_cancel(self, api):
        """PRD §3.9: "A new RSVP is persisted directly as `CONFIRMED` when the
        confirmed seat count plus this RSVP's `party_size` is less than or equal to
        `capacity`; otherwise it is persisted directly as `WAITLISTED`".
        PRD §3.9: "it walks the `WAITLISTED` RSVPs in `created_at` ascending order,
        and for each one promotes it to `PROMOTED` only if its `party_size` fits
        within the seats now free, stopping at the first RSVP that does not fit".

        Design: Corner/state_machines/rsvp_waitlisted_when_capacity_full_then_promoted_on_cancel
        """
        gallery = create_gallery()
        exhibition = create_exhibition(gallery["id"], wall_capacity=3,
                                       opens_utc="2026-05-01T00:00:00Z",
                                       closes_utc="2026-06-01T00:00:00Z")
        event = create_opening_event(exhibition["id"], capacity=10,
                                     starts_utc="2026-05-01T18:00:00Z",
                                     rsvp_deadline_utc="2026-04-30T00:00:00Z")
        a = create_rsvp(event["id"], "A", party_size=4)   # 4 confirmed
        b = create_rsvp(event["id"], "B", party_size=5)   # 9 confirmed
        c = create_rsvp(event["id"], "C", party_size=3)   # 9+3=12>10 -> WAITLISTED
        assert a["status"] == "CONFIRMED"
        assert b["status"] == "CONFIRMED"
        assert c["status"] == "WAITLISTED", "C exceeds capacity, so it waitlists"
        # Cancel A frees 4 seats; seats_free becomes 10-5=5 >= C's 3 -> C promoted.
        validate_success(api.cancel_rsvp(a["id"], SALES))
        c_after = get_success_data(api.get_rsvp(c["id"], SALES))
        assert c_after["status"] == "PROMOTED", \
            "freeing 4 seats lets the fitting waitlisted RSVP promote"


class TestRsvpDeadline:
    def test_rsvp_after_deadline_rejected(self, api):
        """PRD §3.9: "An RSVP may only be created while the clock is at or before
        the event's `rsvp_deadline_utc`; a create after the deadline, or on a
        `CLOSED` or `CANCELLED` event, is rejected with `ERR_RSVP_CLOSED`."

        Design: Corner/validations/rsvp_after_deadline_rejected
        """
        gallery = create_gallery()
        exhibition = create_exhibition(gallery["id"], wall_capacity=2,
                                       opens_utc="2026-05-01T00:00:00Z",
                                       closes_utc="2026-06-01T00:00:00Z")
        event = create_opening_event(exhibition["id"], capacity=10,
                                     starts_utc="2026-05-01T18:00:00Z",
                                     rsvp_deadline_utc="2026-04-30T00:00:00Z")
        set_clock("2026-05-01T00:00:00Z")  # past the 04-30 deadline.
        resp = api.create_rsvp(
            f.create_rsvp_payload(event["id"], guest_name="Late", party_size=1), SALES)
        validate_error(resp, ApiErrorId.ERR_RSVP_CLOSED.value)
