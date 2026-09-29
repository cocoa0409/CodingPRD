"""Endpoint surface: the hotel CRUD triple with its distance ordering, the two
hotel-side and coordinator-side actions, the computed pace read, and the carve graph
answered by one collection endpoint.
"""

from test_helpers import (
    COORDINATOR,
    assemble_block,
    assert_no_version_field,
    cancel_reservation,
    carve_sub_block,
    make_attendee_headers,
    make_hotel_manager_headers,
    read_block,
    register_event,
    register_hotel,
    rooming_list_payload,
    set_clock,
    setup_block_at_cutoff,
    setup_contracted_block,
    setup_open_block_with_reservations,
    setup_pickup_history,
    submit_terms,
    validate_error,
    validate_paginated,
    validate_success,
)

AIRPORT_INN = {
    "name": "Airport Inn",
    "distance_to_venue_miles": 4.5,
    "room_tax_pct": 0.12,
    "total_rooms": 120,
}

THREE_STAYS = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
    {"check_in_date": "2026-09-15", "check_out_date": "2026-09-17", "occupants": 2},
    {"check_in_date": "2026-09-16", "check_out_date": "2026-09-17", "occupants": 1},
]

ONE_REPORT = [
    {
        "as_of_date": "2026-08-05",
        "reported_rooms_picked_up": 3,
        "reported_room_nights": 6,
        "reported_gross_revenue_cents": 131400,
    }
]


class TestHotelPortalSurface:
    def test_the_property_list_is_ranked_by_distance_not_by_insertion_order(self, api):
        """PRD §3.1: "Each `Hotel` records a `name`, a `distance_to_venue_miles` of at
        least zero — this is the ranking key of the attendee-facing property list,
        which is returned ordered by that distance ascending and then by `name`
        ascending"
        PRD §3.1: "A `BureauCoordinator` may later suspend or reinstate a property by
        submitting a new `standing`, which bumps the hotel's `version`; the property
        list can be filtered by `standing`."
        PRD §2.3: "`total_count` is the number of items matching the filters before
        pagination is applied, and `has_more` is true exactly when items remain beyond
        the current window."

        Design: Corner/endpoints/hotel_create_read_and_distance_ordered_listing
        """
        far = register_hotel(**AIRPORT_INN)
        near = register_hotel()
        guest_headers = make_attendee_headers("att-anon")

        suspended = validate_success(
            api.update_hotel_standing(far["id"], {"standing": "SUSPENDED"}, COORDINATOR)
        )
        assert suspended["standing"] == "SUSPENDED"
        assert suspended["version"] == far["version"] + 1

        one = validate_success(api.get_hotel(near["id"], guest_headers))
        assert one["id"] == near["id"]
        assert one["room_tax_pct"] == 0.1475

        rows, meta = validate_paginated(
            api.list_hotels(guest_headers, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [near["id"], far["id"]], (
            "the 0.3-mile property registered second must lead the list"
        )

        active_rows, active_meta = validate_paginated(
            api.list_hotels(guest_headers, params={"standing": "ACTIVE"})
        )
        assert active_meta["total_count"] == 1
        assert active_rows[0]["id"] == near["id"]


class TestRequestChangesAction:
    def test_bouncing_the_terms_back_moves_the_block_without_spending_a_round(
        self, api
    ):
        """PRD §3.2: "Bouncing the terms back moves the block `TERMS_SUBMITTED →
        CHANGES_REQUESTED` and bumps its `version`; a manager acting on a block whose
        `hotel_id` is not their own `X-User-ID` is rejected with
        `ERR_NOT_RESOURCE_OWNER`."
        PRD §3.2: "A submission overwrites `negotiated_nightly_rate_cents`,
        `commission_pct`, `rebate_per_room_night_cents`, `cutoff_date` and
        `reduction_rights_pct` wholesale from the payload — there is no partial merge
        — increases `revision_round` by one, and bumps the block's `version`."
        PRD §4: "Every operation that mutates an existing resource, including all
        state transitions, all cash movements and the logical-clock repositioning,
        returns `200 OK`."

        Design: Corner/endpoints/request_changes_action_returns_block_to_the_bureau
        """
        event = register_event()
        hotel = register_hotel()
        block = submit_terms(assemble_block(event["id"], hotel["id"]))
        assert block["status"] == "TERMS_SUBMITTED"
        assert block["revision_round"] == 1

        bounced = validate_success(
            api.request_block_changes(
                block["id"], make_hotel_manager_headers(hotel["id"])
            )
        )
        assert bounced["status"] == "CHANGES_REQUESTED"
        assert bounced["revision_round"] == 1, (
            "only a terms submission advances the negotiation counter, got "
            f"{bounced['revision_round']}"
        )
        assert bounced["version"] == block["version"] + 1

        resubmitted = submit_terms(bounced, negotiated_nightly_rate_cents=20900)
        assert resubmitted["status"] == "TERMS_SUBMITTED"
        assert resubmitted["revision_round"] == 2
        assert resubmitted["negotiated_nightly_rate_cents"] == 20900


class TestRoomingListBatchAction:
    def test_one_initial_call_transmits_every_eligible_stay_of_the_block(self, api):
        """PRD §3.6: "Across every sub-block of the block regardless of that
        sub-block's `approval_status`, a reservation joins the batch when its
        `transmission_status` is `NOT_TRANSMITTED` or `CHANGE_PENDING`, **and** its
        `reservation_status` is `CONFIRMED`, `CANCELLED` or `NO_SHOW`, **and** it is
        not the case that the reservation is `CANCELLED` or `NO_SHOW` while still
        `NOT_TRANSMITTED` — a stay the hotel was never told about needs no
        retraction."
        PRD §3.6: "The resulting set is ordered by `created_at` ascending and then by
        `intake_seq` ascending, which is a total order because `intake_seq` is unique,
        and those identifiers are recorded on the batch as `included_reservation_ids`
        with their count in `reservation_count`."
        PRD §3.6: "The batch's `batch_seq` is one more than the number of
        transmissions the block already has"
        PRD §3.6: "Every included reservation moves to `transmission_status`
        `TRANSMITTED` — `NOT_TRANSMITTED → TRANSMITTED` for a first-time stay,
        `CHANGE_PENDING → TRANSMITTED` for a delta re-entering a `CHANGE` or `FINAL`
        batch — and each such reservation's `version` is bumped."

        Design: Corner/endpoints/rooming_list_transmission_covers_the_whole_batch
        """
        ctx = setup_open_block_with_reservations(THREE_STAYS, general_rooms=6)
        first, second, third = ctx["reservations"]
        cancel_reservation(third["id"], ctx["attendees"][2]["id"])

        batch = validate_success(
            api.transmit_rooming_list(
                ctx["block"]["id"], rooming_list_payload("INITIAL"), COORDINATOR
            ),
            201,
        )
        assert batch["batch_seq"] == 1
        assert batch["reservation_count"] == 2
        assert batch["included_reservation_ids"] == [first["id"], second["id"]]
        assert batch["hotel_block_id"] == ctx["block"]["id"]
        assert_no_version_field(batch)

        for reservation in (first, second):
            row = validate_success(api.get_reservation(reservation["id"], COORDINATOR))
            assert row["transmission_status"] == "TRANSMITTED"
            assert row["version"] > reservation["version"]

        cancelled = validate_success(api.get_reservation(third["id"], COORDINATOR))
        assert cancelled["reservation_status"] == "CANCELLED"
        assert cancelled["transmission_status"] == "NOT_TRANSMITTED", (
            "a stay cancelled before any transmission needs no retraction, got "
            f"{cancelled['transmission_status']}"
        )


class TestSubBlockCollectionLinks:
    def test_the_same_collection_answers_the_block_and_the_parent_question(self, api):
        """PRD §3.3: "Sub-blocks can be listed and filtered by `hotel_block_id`,
        `parent_sub_block_id`, `segment` and `approval_status`."
        PRD §3.3: "A **nested carve**, with a parent named — the mechanism by which a
        VIP allotment is cut out of the staff allotment — draws from the parent
        sub-block's own allotment and succeeds only when `allotted_rooms` is less than
        or equal to the parent's `available_rooms`."

        Design: Corner/endpoints/sub_block_listing_links_children_to_their_parent_carve
        """
        ctx = setup_contracted_block(contracted_rooms_per_night=10)
        general = carve_sub_block(ctx["block"]["id"], "GENERAL", 6)
        nested = carve_sub_block(
            ctx["block"]["id"],
            "EXHIBITOR",
            2,
            eligibility_code="EXH-2026",
            parent_sub_block_id=general["id"],
        )
        organizer = ctx["organizer_headers"]

        block_rows, block_meta = validate_paginated(
            api.list_sub_blocks(
                organizer, params={"hotel_block_id": ctx["block"]["id"]}
            )
        )
        assert block_meta["total_count"] == 2
        assert {row["id"] for row in block_rows} == {general["id"], nested["id"]}

        child_rows, child_meta = validate_paginated(
            api.list_sub_blocks(organizer, params={"parent_sub_block_id": general["id"]})
        )
        assert child_meta["total_count"] == 1
        assert child_rows[0]["id"] == nested["id"]
        assert child_rows[0]["parent_sub_block_id"] == general["id"]

        parent_after = validate_success(api.get_sub_block(general["id"], organizer))
        assert parent_after["allotted_rooms"] == 4


class TestPickupPaceComputedRead:
    def test_two_identical_reads_agree_and_move_nothing(self, api):
        """PRD §3.6: "The analysis response also echoes the `hotel_block_id`, the
        `report_count`, and the `latest_reported_room_nights` it worked from."
        PRD §3.6: "Separately, `pace_target_room_nights` is the block's
        `contracted_room_nights` multiplied by the pace target ratio of 80 percent,
        rounded half up to whole room nights."
        PRD §3.6: "Filing a report changes nothing else — no block status moves, no
        vendor is touched"
        PRD §2.4: "`version` — an integer that starts at 1 on creation and increases
        by exactly 1 on every mutation of the resource, including mutations the server
        performs on its own initiative as part of a cascade."

        Design: Corner/endpoints/pickup_pace_computed_read_leaves_no_trace
        """
        ctx = setup_pickup_history(ONE_REPORT, contracted_rooms_per_night=10)
        block_id = ctx["block"]["id"]

        organizer_read = validate_success(
            api.get_pickup_pace(block_id, ctx["organizer_headers"])
        )
        hotel_read = validate_success(
            api.get_pickup_pace(block_id, ctx["hotel_headers"])
        )

        assert organizer_read == hotel_read
        assert organizer_read["hotel_block_id"] == block_id
        assert organizer_read["report_count"] == 1
        assert organizer_read["latest_reported_room_nights"] == 6
        assert organizer_read["pace_target_room_nights"] == 32
        assert organizer_read["on_pace"] is False

        after = read_block(block_id)
        assert after["version"] == ctx["block"]["version"], (
            "a computed read must not bump the block version, got "
            f"{after['version']} against {ctx['block']['version']}"
        )
        assert after["status"] == "CONTRACTED"

        rows, meta = validate_paginated(api.list_pickup_reports(block_id, COORDINATOR))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["pickup_reports"][0]["id"]


class TestConditionalCloseAction:
    def test_the_same_close_call_is_refused_then_accepted_as_the_clock_moves(
        self, api
    ):
        """PRD §3.9: "A `BureauCoordinator` moves the block `CUTOFF_PASSED → CLOSED`
        — the block's terminal state — and this is admissible only once the logical
        clock has reached the event's `event_end_date` at midnight UTC; earlier
        attempts are rejected with `ERR_EVENT_NOT_ENDED`, and attempts from any other
        block status with `ERR_INVALID_BLOCK_STATE`."
        PRD §3.9: "Closure freezes the attrition exposure:
        `attrition_liability_cents` is set to the post-reduction attrition penalty
        exposure defined in §3.7, computed against the block as it finally stands."
        PRD §2.10: "`ERR_EVENT_NOT_ENDED` (409) when a block close is attempted
        before the clock reaches `event_end_date` at midnight UTC."
        PRD §3.2: "The new block starts with `revision_round` at 0,
        `unassigned_rooms_per_night` and `released_rooms_per_night` at 0,
        `attrition_liability_cents` at 0, and `confirmation_number` null"
        PRD §2.11: "Otherwise — that is, when the open group is empty but the ended
        group is not — the posture is `CLOSED`."

        Design: Corner/endpoints/block_close_action_is_conditional_on_the_event_having_ended
        """
        ctx = setup_block_at_cutoff([], general_rooms=1, contracted_rooms_per_night=1)
        assert ctx["block"]["status"] == "CUTOFF_PASSED"

        set_clock("2026-09-17T00:00:00Z")
        too_early = api.close_hotel_block(ctx["block"]["id"], COORDINATOR)
        validate_error(too_early, "ERR_EVENT_NOT_ENDED", 409)

        mid_flight = read_block(ctx["block"]["id"])
        assert mid_flight["status"] == "CUTOFF_PASSED"
        assert mid_flight["attrition_liability_cents"] == 0
        assert mid_flight["version"] == ctx["block"]["version"]

        set_clock("2026-09-18T00:00:00Z")
        closed = validate_success(
            api.close_hotel_block(ctx["block"]["id"], COORDINATOR)
        )
        assert closed["status"] == "CLOSED"
        # Adjusted 4 room nights, actual 0, protected 3, shortfall ratio 0.75.
        assert closed["attrition_liability_cents"] == 59130
        assert closed["version"] > mid_flight["version"]

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["housing_posture"] == "CLOSED"
