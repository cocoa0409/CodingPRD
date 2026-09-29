"""The two date geometries side by side: half-open nights for sub-block capacity,
closed and buffered intervals for one delegate's own stays."""

from test_helpers import (
    COORDINATOR,
    book_reservation,
    create_reservation_payload,
    import_attendee,
    make_attendee_headers,
    setup_open_block,
    setup_open_block_with_reservations,
    validate_error,
    validate_paginated,
    validate_success,
)

# A departure and an arrival on 2026-09-16, into a sub-block holding one room.
SAME_DAY_TURNOVER = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-16", "occupants": 1},
    {"check_in_date": "2026-09-16", "check_out_date": "2026-09-18", "occupants": 1},
]


class TestSubBlockNightCapacityIsHalfOpen:
    """One room can be sold twice in a window if the nights do not overlap."""

    def test_same_day_turnover_fits_a_single_room_but_a_straddling_stay_does_not(
        self, api
    ):
        """PRD §2.6: "A stay from a check-in date to a check-out date occupies the
        **half-open** interval of nights beginning on the check-in date and ending
        on the night before the check-out date; the number of nights it occupies is
        the number of whole days between the two dates. A departure on a given date
        and an arrival on that same date therefore do not compete for the same
        night."
        PRD §3.4: "Note the asymmetry that follows from the two geometries: a
        departure and an arrival on the same date do not compete for a night in the
        capacity test, but they do collide in the same-attendee overlap test."
        PRD §3.4: "A single night that fails rejects the whole booking with
        `ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/sub_block_half_open_night_capacity_admits_same_day_turnover
        """
        ctx = setup_open_block_with_reservations(
            SAME_DAY_TURNOVER, general_rooms=1, contracted_rooms_per_night=1
        )
        arriving = ctx["reservations"][1]
        assert arriving["reservation_status"] == "CONFIRMED"
        assert arriving["room_nights"] == 2
        assert arriving["total_room_charge_cents"] == 50260

        # A third delegate straddling the turnover date needs 2026-09-16, which
        # the arriving stay already holds, and 2026-09-15, which the departing
        # stay holds.
        third = import_attendee(ctx["event"]["id"], 3)
        response = api.create_reservation(
            create_reservation_payload(
                ctx["sub_block"]["id"],
                third["id"],
                check_in_date="2026-09-15",
                check_out_date="2026-09-17",
            ),
            make_attendee_headers(third["id"]),
        )
        validate_error(response, "ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED", 409)

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 1, (
            "committed_rooms is a peak-night figure, so two non-overlapping stays "
            f"in one room peak at 1, got {sub_block['committed_rooms']}"
        )
        assert sub_block["available_rooms"] == 0
        assert sub_block["inventory_status"] == "FULL"

        rows, meta = validate_paginated(
            api.list_reservations(
                COORDINATOR, params={"sub_block_id": ctx["sub_block"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert [row["reservation_status"] for row in rows] == ["CONFIRMED", "CONFIRMED"]

    def test_the_turnover_night_is_the_only_one_the_two_stays_share_a_date_on(
        self, api
    ):
        """PRD §3.3: "For each night in the event's housing window — every night
        from `event_start_date` up to but not including `event_end_date` — the
        server counts the reservations of that sub-block whose
        `reservation_status` is `CONFIRMED` and whose stay covers that night,
        meaning the night falls on or after the reservation's `check_in_date` and
        strictly before its `check_out_date`. `committed_rooms` is the largest of
        those per-night counts."
        PRD §3.4: "Third, the **night capacity admission test**, which uses the
        half-open geometry of §3.3 instead: for every night the candidate stay
        would occupy, the count of `CONFIRMED` reservations already covering that
        night, plus one for the candidate, must be less than or equal to the
        sub-block's `allotted_rooms`."

        Design: Difficulty/resource_temporal_overlap/sub_block_half_open_night_capacity_admits_same_day_turnover
        """
        ctx = setup_open_block(
            general_rooms=1, contracted_rooms_per_night=1, num_attendees=3
        )
        first, second, third = ctx["attendees"]

        departing = book_reservation(
            ctx["sub_block"]["id"], first, "2026-09-14", "2026-09-16"
        )
        assert departing["room_nights"] == 2

        # 2026-09-16 is free the moment the first guest leaves.
        arriving = book_reservation(
            ctx["sub_block"]["id"], second, "2026-09-16", "2026-09-18"
        )
        assert arriving["reservation_status"] == "CONFIRMED"

        # But 2026-09-14 is not free while the first guest is in the room.
        response = api.create_reservation(
            create_reservation_payload(
                ctx["sub_block"]["id"],
                third["id"],
                check_in_date="2026-09-14",
                check_out_date="2026-09-15",
            ),
            make_attendee_headers(third["id"]),
        )
        validate_error(response, "ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED", 409)


class TestAttendeeOverlapIsClosedAndBuffered:
    """One delegate cannot hold two rooms across the same trip, gap or no gap."""

    def test_a_one_day_gap_between_two_stays_still_collides(self, api):
        """PRD §3.4: "Each of that attendee's other reservations whose
        `reservation_status` is `CONFIRMED` or `WAITLISTED` is inflated by a
        one-day shoulder buffer at each end, producing a low bound one day before
        its `check_in_date` and a high bound one day after its `check_out_date`,
        and both bounds are treated as **inclusive**."
        PRD §3.4: "The candidate stay is accepted against that existing stay only
        when the candidate's `check_out_date` falls strictly before the low bound,
        or the candidate's `check_in_date` falls strictly after the high bound; in
        every other case the two collide and the booking is rejected with
        `ERR_ATTENDEE_STAY_OVERLAP`."
        PRD §3.4: "Because the interval is closed and buffered, a same-day hotel
        switch — checking out of one property and into another on the same date —
        collides, and so does a one-day gap."

        Design: Difficulty/resource_temporal_overlap/attendee_closed_buffered_stay_overlap_rejects_one_day_gap
        """
        ctx = setup_open_block(general_rooms=2, num_attendees=1)
        guest = ctx["attendees"][0]
        held = book_reservation(
            ctx["sub_block"]["id"], guest, "2026-09-14", "2026-09-16"
        )
        assert held["reservation_status"] == "CONFIRMED"

        # The held stay buffers out to the inclusive window 2026-09-13 through
        # 2026-09-17, and a check-in on 2026-09-17 is not strictly after it.
        response = api.create_reservation(
            create_reservation_payload(
                ctx["sub_block"]["id"],
                guest["id"],
                check_in_date="2026-09-17",
                check_out_date="2026-09-18",
            ),
            make_attendee_headers(guest["id"]),
        )
        validate_error(response, "ERR_ATTENDEE_STAY_OVERLAP", 409)

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 1
        assert sub_block["available_rooms"] == 1

        rows, meta = validate_paginated(
            api.list_reservations(COORDINATOR, params={"attendee_id": guest["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == held["id"]

    def test_a_same_day_switch_collides_while_a_two_day_gap_is_admitted(self, api):
        """PRD §3.4: "Because the interval is closed and buffered, a same-day hotel
        switch — checking out of one property and into another on the same date —
        collides, and so does a one-day gap."
        PRD §3.4: "The candidate stay is accepted against that existing stay only
        when the candidate's `check_out_date` falls strictly before the low bound,
        or the candidate's `check_in_date` falls strictly after the high bound; in
        every other case the two collide and the booking is rejected with
        `ERR_ATTENDEE_STAY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/attendee_closed_buffered_stay_overlap_rejects_one_day_gap
        """
        ctx = setup_open_block(general_rooms=2, num_attendees=1)
        guest = ctx["attendees"][0]
        book_reservation(ctx["sub_block"]["id"], guest, "2026-09-14", "2026-09-16")

        switching = api.create_reservation(
            create_reservation_payload(
                ctx["sub_block"]["id"],
                guest["id"],
                check_in_date="2026-09-16",
                check_out_date="2026-09-18",
            ),
            make_attendee_headers(guest["id"]),
        )
        validate_error(switching, "ERR_ATTENDEE_STAY_OVERLAP", 409)

        # 2026-09-18 is strictly after the high bound of 2026-09-17, so the same
        # delegate may hold a second room from there.
        clear_of_the_buffer = book_reservation(
            ctx["sub_block"]["id"], guest, "2026-09-18", "2026-09-19"
        )
        assert clear_of_the_buffer["reservation_status"] == "CONFIRMED"
        assert clear_of_the_buffer["room_nights"] == 1

        rows, meta = validate_paginated(
            api.list_reservations(COORDINATOR, params={"attendee_id": guest["id"]})
        )
        assert meta["total_count"] == 2
