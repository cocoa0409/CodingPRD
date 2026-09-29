"""Consistency model: a booking's derived figures are readable by every role on the
very next request, and a repeated read returns the same numbers.
"""

from test_helpers import (
    COORDINATOR,
    book_reservation,
    setup_open_block,
    validate_success,
)


class TestImmediateVisibilityOfABooking:
    def test_the_booking_is_already_reflected_in_every_derived_figure(self, api):
        """PRD §3.4: "The reservation is created with `reservation_status` `CONFIRMED`,
        `transmission_status` `NOT_TRANSMITTED`, `eligibility_review_required` false
        and `no_show_billed_cents` 0; the sub-block's occupancy figures, the event's
        `total_confirmed_room_nights` and the event's `housing_posture` are all
        recomputed."
        PRD §3.3: "These three derived values are re-evaluated on every reservation
        creation, date change, cancellation, waitlisting and no-show, and whenever
        `allotted_rooms` itself moves."
        PRD §3.3: "`available_rooms` is `allotted_rooms` minus `committed_rooms`.
        `inventory_status` is the enum `FULL` when `available_rooms` is exactly zero
        and `OPEN` otherwise."
        PRD §2.11: "Otherwise, if the open group is non-empty and the available room
        count is greater than zero, the posture is `OPEN`."

        Design: Corner/consistency model/reservation_write_is_immediately_visible_to_every_reader
        """
        ctx = setup_open_block(general_rooms=6, num_attendees=1)
        guest = ctx["attendees"][0]

        reservation = book_reservation(
            ctx["sub_block"]["id"],
            guest,
            check_in_date="2026-09-14",
            check_out_date="2026-09-18",
        )
        assert reservation["reservation_status"] == "CONFIRMED"
        assert reservation["total_room_charge_cents"] == 100520

        # The hotel side sees the occupancy on its very next read.
        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], ctx["hotel_headers"])
        )
        assert sub_block["allotted_rooms"] == 6
        assert sub_block["committed_rooms"] == 1
        assert sub_block["available_rooms"] == 5
        assert sub_block["inventory_status"] == "OPEN"

        # So does the organizer on the event ledger, twice over.
        first_read = validate_success(
            api.get_event(ctx["event"]["id"], ctx["organizer_headers"])
        )
        second_read = validate_success(
            api.get_event(ctx["event"]["id"], ctx["organizer_headers"])
        )
        assert first_read["total_confirmed_room_nights"] == 4
        assert first_read["housing_posture"] == "OPEN"
        assert second_read == first_read, "a repeated read must settle on nothing new"

        # And the bureau's own read of the reservation agrees with the write echo.
        readback = validate_success(
            api.get_reservation(reservation["id"], COORDINATOR)
        )
        assert readback == reservation
