"""Booking audit windows against two different contended resources: the auditor's diary and
the holder's site."""

from test_helpers import (
    AUDITOR_1_ID,
    AUDITOR_2_ID,
    OFFICER,
    api_errors as E,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)


def _book(api, holder_id, window_start, window_end, auditor_user_id, audit_type="SURVEILLANCE"):
    return api.create_audit(
        f.audit_payload(
            holder_id, window_start, window_end,
            auditor_user_id=auditor_user_id, audit_type=audit_type,
        ),
        OFFICER,
    )


def _two_producers_with_one_booked_auditor(api):
    """Auditor one already booked on the first producer over 2026-08-01 to 2026-08-05."""
    first = f.build_certified_producer(api)
    second = f.build_certified_producer(
        api, legal_name="Cocoa Union", country_code="GH", product_code="COCOA"
    )
    booked = f.schedule_audit(
        api, first["holder_id"], "2026-08-01", "2026-08-05",
        auditor_user_id=AUDITOR_1_ID, audit_type="SURVEILLANCE",
    )
    return {
        "first_holder_id": first["holder_id"],
        "second_holder_id": second["holder_id"],
        "booked_audit_id": booked["id"],
    }


def _two_producers_with_a_later_booked_auditor(api):
    """Auditor one already booked on the first producer over 2026-09-01 to 2026-09-05.

    The booking sits a month ahead of the clock so that a candidate window placed *before* it
    is still forward-dated, which is what isolates the travel buffer from the window-sanity
    rule that §3.6 puts ahead of it.
    """
    first = f.build_certified_producer(api)
    second = f.build_certified_producer(
        api, legal_name="Cocoa Union", country_code="GH", product_code="COCOA"
    )
    booked = f.schedule_audit(
        api, first["holder_id"], "2026-09-01", "2026-09-05",
        auditor_user_id=AUDITOR_1_ID, audit_type="SURVEILLANCE",
    )
    return {
        "first_holder_id": first["holder_id"],
        "second_holder_id": second["holder_id"],
        "booked_audit_id": booked["id"],
    }


class TestAuditorTravelBuffer:
    """The auditor's diary is guarded by a travel buffer on both sides of every booking."""

    def test_a_window_starting_exactly_three_days_after_the_last_one_still_conflicts(
        self, api, clock
    ):
        """The auditor's previous window ends 2026-08-05, so a new window starting 2026-08-08 is
        still inside the travel buffer and is refused.

        Design: Difficulty/resource_temporal_overlap/auditor_travel_buffer_blocks_a_window_that_merely_touches_the_buffer_edge
        """
        world = _two_producers_with_one_booked_auditor(api)

        response = _book(
            api, world["second_holder_id"], "2026-08-08", "2026-08-12", AUDITOR_1_ID
        )

        validate_error(response, E.ERR_AUDITOR_WINDOW_CONFLICT, 409)

    def test_the_first_day_past_the_buffer_is_bookable_and_the_refusal_wrote_nothing(
        self, api, clock
    ):
        """One day later the booking is accepted as SCHEDULED, and the second holder ends up with
        exactly that one audit while the original booking is untouched.

        Design: Difficulty/resource_temporal_overlap/auditor_travel_buffer_blocks_a_window_that_merely_touches_the_buffer_edge
        """
        world = _two_producers_with_one_booked_auditor(api)
        _book(api, world["second_holder_id"], "2026-08-08", "2026-08-12", AUDITOR_1_ID)

        accepted = validate_success(
            _book(api, world["second_holder_id"], "2026-08-09", "2026-08-13", AUDITOR_1_ID), 201
        )

        assert accepted["status"] == "SCHEDULED"
        rows, meta = validate_paginated(
            api.list_holder_audits(world["second_holder_id"], OFFICER)
        )
        assert meta["total_count"] == 1, f"expected 1 audit on this holder, got {meta}"
        assert len(rows) == 1
        original = f.read_audit(api, world["booked_audit_id"])
        assert original["status"] == "SCHEDULED"
        assert original["window_start"] == "2026-08-01"
        assert original["window_end"] == "2026-08-05"

    def test_the_buffer_guards_the_days_before_a_booking_as_well(self, api, clock):
        """Against a booking that runs 2026-09-01 to 2026-09-05, a window ending 2026-08-29 —
        three days before that booked window starts — is refused too.

        The candidate window is still forward of the clock, so §2.10's window-sanity rule at
        priority 23 is satisfied and the travel-buffer rule at priority 24 is what bites.

        Design: Difficulty/resource_temporal_overlap/auditor_travel_buffer_blocks_a_window_that_merely_touches_the_buffer_edge
        """
        world = _two_producers_with_a_later_booked_auditor(api)

        response = _book(
            api, world["second_holder_id"], "2026-08-25", "2026-08-29", AUDITOR_1_ID
        )

        validate_error(response, E.ERR_AUDITOR_WINDOW_CONFLICT, 409)


def _one_producer_with_one_booked_window(api):
    """A single producer already hosting auditor one over 2026-08-01 to 2026-08-05."""
    producer = f.build_certified_producer(api)
    booked = f.schedule_audit(
        api, producer["holder_id"], "2026-08-01", "2026-08-05",
        auditor_user_id=AUDITOR_1_ID, audit_type="SURVEILLANCE",
    )
    producer["booked_audit_id"] = booked["id"]
    return producer


class TestHolderSiteContention:
    """The holder's own site takes the opposite semantics: no buffer, and touching is allowed."""

    def test_a_single_day_of_overlap_on_the_same_holder_is_refused(self, api, clock):
        """A second auditor's window starting 2026-08-04 overlaps the hosted window by one day and
        is refused on the holder axis.

        Design: Difficulty/resource_temporal_overlap/holder_audit_windows_may_touch_but_not_overlap_by_a_single_day
        """
        producer = _one_producer_with_one_booked_window(api)

        response = _book(
            api, producer["holder_id"], "2026-08-04", "2026-08-08", AUDITOR_2_ID, "FOLLOW_UP"
        )

        validate_error(response, E.ERR_HOLDER_AUDIT_WINDOW_CONFLICT, 409)

    def test_a_window_that_merely_touches_the_hosted_one_is_accepted(self, api, clock):
        """Starting on the very day the hosted window ends is not an overlap, so the follow-up is
        SCHEDULED and the holder now lists both audits oldest first.

        Design: Difficulty/resource_temporal_overlap/holder_audit_windows_may_touch_but_not_overlap_by_a_single_day
        """
        producer = _one_producer_with_one_booked_window(api)
        _book(api, producer["holder_id"], "2026-08-04", "2026-08-08", AUDITOR_2_ID, "FOLLOW_UP")

        accepted = validate_success(
            _book(
                api, producer["holder_id"], "2026-08-05", "2026-08-09", AUDITOR_2_ID, "FOLLOW_UP"
            ),
            201,
        )

        assert accepted["status"] == "SCHEDULED"
        rows, meta = validate_paginated(api.list_holder_audits(producer["holder_id"], OFFICER))
        assert meta["total_count"] == 2, f"expected 2 audits on this holder, got {meta}"
        assert rows[0]["id"] == producer["booked_audit_id"], (
            "the holder's audits are listed oldest first"
        )
        assert rows[1]["id"] == accepted["id"]

    def test_the_second_auditor_now_carries_a_buffer_of_their_own(self, api, clock):
        """Having taken 2026-08-05 to 2026-08-09, the second auditor is refused a window starting
        2026-08-08 on the auditor axis rather than the holder axis.

        Design: Difficulty/resource_temporal_overlap/holder_audit_windows_may_touch_but_not_overlap_by_a_single_day
        """
        producer = _one_producer_with_one_booked_window(api)
        validate_success(
            _book(
                api, producer["holder_id"], "2026-08-05", "2026-08-09", AUDITOR_2_ID, "FOLLOW_UP"
            ),
            201,
        )

        response = _book(
            api, producer["holder_id"], "2026-08-08", "2026-08-12", AUDITOR_2_ID, "FOLLOW_UP"
        )

        validate_error(response, E.ERR_AUDITOR_WINDOW_CONFLICT, 409)
