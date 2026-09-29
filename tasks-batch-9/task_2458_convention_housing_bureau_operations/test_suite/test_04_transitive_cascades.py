"""The two deepest chains in the system: exercising a reduction, and confirming
a rogue housing vendor."""

from test_helpers import (
    COMPLIANCE,
    COORDINATOR,
    approve_reduction,
    assert_block_inventory_invariant,
    confirm_vendor,
    exercise_reduction,
    file_reduction,
    read_block,
    setup_open_block_with_reservations,
    setup_vendor_with_incidents,
    transmit_rooming_list,
    validate_paginated,
    validate_success,
)

THREE_FULL_STAYS = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
]

ONE_STAY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
]

FULLY_CARVED_BLOCK = {"reduction_rights_pct": 0.50}


def _block_with_three_transmitted_stays():
    """Three rooms, three confirmed stays, all already on the rooming list."""
    ctx = setup_open_block_with_reservations(
        THREE_FULL_STAYS,
        general_rooms=3,
        contracted_rooms_per_night=3,
        block_overrides=FULLY_CARVED_BLOCK,
        confirmation_number="CN-SUM26-003",
    )
    transmit_rooming_list(ctx["block"]["id"], "INITIAL")
    return ctx


def _exercised_reduction(ctx, rooms=1):
    reduction = file_reduction(ctx["block"]["id"], rooms)
    approve_reduction(reduction["id"])
    return exercise_reduction(reduction["id"])


class TestReductionExerciseCascade:
    """Shrinking the contract walks the waterfall into the reservation ledger."""

    def test_exercise_shrinks_the_contract_and_the_sub_block_allotment(self, api):
        """PRD §3.7: "The contract shrinks. The block's
        `contracted_rooms_per_night` falls by `requested_reduction_rooms`, its
        `contracted_room_nights` is re-derived from the new figure and the event's
        `night_count`, and the block's `version` is bumped."
        PRD §3.7: "The block's `unassigned_rooms_per_night` absorbs first: the
        smaller of the outstanding rooms and the unassigned pool is taken out of
        `unassigned_rooms_per_night` and recorded on the reduction as
        `rooms_absorbed_from_unassigned`."
        PRD §3.3: "`inventory_status` is the enum `FULL` when `available_rooms`
        is exactly zero and `OPEN` otherwise."

        Design: Difficulty/transitive_cascade/reduction_exercise_cascade_depth_four_waitlists_last_reservation
        """
        ctx = _block_with_three_transmitted_stays()
        reduction = _exercised_reduction(ctx)

        assert reduction["status"] == "EXERCISED"
        assert reduction["rooms_absorbed_from_unassigned"] == 0, (
            "the whole block was carved, so nothing can come out of unassigned "
            f"inventory, got {reduction['rooms_absorbed_from_unassigned']}"
        )
        assert reduction["rooms_absorbed_from_sub_blocks"] == 1

        block = read_block(ctx["block"]["id"])
        assert block["contracted_rooms_per_night"] == 2
        assert block["contracted_room_nights"] == 8

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["allotted_rooms"] == 2
        assert sub_block["committed_rooms"] == 2
        assert sub_block["available_rooms"] == 0
        assert sub_block["inventory_status"] == "FULL"
        assert_block_inventory_invariant(block, [sub_block])

    def test_exercise_waitlists_the_last_booked_stay_and_prices_the_option(self, api):
        """PRD §3.7: "Its reservations in `CONFIRMED` are moved `CONFIRMED →
        WAITLISTED` in **descending** `intake_seq` order — last booked, first bumped
        — and the process continues only until `committed_rooms` is once again
        less than or equal to `allotted_rooms`."
        PRD §3.7: "Because reservations left the `CONFIRMED` set, the sub-block's
        `committed_rooms`, `available_rooms` and `inventory_status` and the
        event's `total_confirmed_room_nights` are recomputed, and every affected
        reservation that was sitting in `TRANSMITTED` moves `TRANSMITTED →
        CHANGE_PENDING` so the hotel is told."
        PRD §3.7: "The difference between the two runs, pre-reduction minus
        post-reduction, is `penalty_avoided_cents`."

        Design: Difficulty/transitive_cascade/reduction_exercise_cascade_depth_four_waitlists_last_reservation
        """
        ctx = _block_with_three_transmitted_stays()
        first, second, third = ctx["reservations"]
        assert third["intake_seq"] > second["intake_seq"] > first["intake_seq"]

        reduction = _exercised_reduction(ctx)

        bumped = validate_success(api.get_reservation(third["id"], COORDINATOR))
        assert bumped["reservation_status"] == "WAITLISTED"
        assert bumped["transmission_status"] == "CHANGE_PENDING"
        for kept in (first, second):
            still_held = validate_success(api.get_reservation(kept["id"], COORDINATOR))
            assert still_held["reservation_status"] == "CONFIRMED"
            assert still_held["transmission_status"] == "TRANSMITTED"

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 8

        # Post-reduction: 8 adjusted room nights against 8 actual, no shortfall.
        # Pre-reduction: 12 adjusted, protected 10, shortfall 2 at 70 percent.
        assert read_block(ctx["block"]["id"])["attrition_liability_cents"] == 0
        assert reduction["penalty_avoided_cents"] == 30660, (
            "2 shortfall nights at 21900 cents and 70 percent is 30660, got "
            f"{reduction['penalty_avoided_cents']}"
        )


class TestPoacherConfirmationCascade:
    """Confirming a poacher warns delegates and reopens their rooming-list rows."""

    def test_confirmation_issues_both_warnings_in_the_pinned_order(self, api):
        """PRD §3.8: "Every incident of that vendor with `verified` true and
        `status` `RECORDED` moves `RECORDED → WARNING_ISSUED`, processed in
        `occurred_at` ascending and then `contact_channel` ascending order. Each
        such incident gets `warning_issued_at` set to the logical clock and a
        `warning_severity` of `ADVISORY` when the target delegate's
        `warning_count` is 0 at that moment and `URGENT` from the second warning
        onward — because the incidents are processed in that pinned order, two
        warnings to the same delegate in one confirmation come out `ADVISORY`
        then `URGENT`."
        PRD §3.8: "The score starts from a base of 10, adds 25 for each counted
        incident, adds 15 for each distinct `contact_channel` appearing among the
        counted incidents, and adds a further 20 if any counted incident has
        `solicited_payment` true — that bonus is awarded once, not per incident."

        Design: Difficulty/transitive_cascade/poacher_confirmation_cascade_depth_three_reopens_transmitted_reservation
        """
        ctx = setup_open_block_with_reservations(ONE_STAY, general_rooms=6)
        transmit_rooming_list(ctx["block"]["id"], "INITIAL")
        guest = ctx["attendees"][0]

        vendor_ctx = setup_vendor_with_incidents(
            ctx["event"]["id"],
            [
                {
                    "attendee_id": guest["id"],
                    "contact_channel": "EMAIL",
                    "occurred_at": "2026-07-20T10:00:00Z",
                },
                {
                    "attendee_id": guest["id"],
                    "contact_channel": "PHONE",
                    "occurred_at": "2026-07-22T09:00:00Z",
                },
            ],
        )
        confirmed = confirm_vendor(vendor_ctx["vendor"]["id"])

        assert confirmed["status"] == "CONFIRMED_POACHER"
        assert confirmed["risk_score"] == 90, (
            "base 10 plus 25 per incident plus 15 per channel is 90, got "
            f"{confirmed['risk_score']}"
        )
        assert confirmed["verified_incident_count"] == 2
        assert confirmed["warning_issued_count"] == 2

        incidents, meta = validate_paginated(
            api.list_vendor_incidents(vendor_ctx["vendor"]["id"], COMPLIANCE)
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in incidents] == [
            "WARNING_ISSUED",
            "WARNING_ISSUED",
        ]
        assert [row["warning_severity"] for row in incidents] == ["ADVISORY", "URGENT"]

    def test_second_warning_flags_the_guest_and_reopens_the_transmitted_row(self, api):
        """PRD §3.8: "Because a warning was issued, the target delegate's
        `warning_count` rises by one for each warning they receive, and when that
        counter reaches the housing-risk threshold of 2 the delegate's
        `housing_risk_flag` flips from false to true."
        PRD §3.8: "Because `housing_risk_flag` flipped from false to true, every
        reservation of that delegate whose `reservation_status` is `CONFIRMED`
        gets `eligibility_review_required` set to true, and any such reservation
        sitting in `TRANSMITTED` moves `TRANSMITTED → CHANGE_PENDING` so the
        hotel is warned in the next batch."

        Design: Difficulty/transitive_cascade/poacher_confirmation_cascade_depth_three_reopens_transmitted_reservation
        """
        ctx = setup_open_block_with_reservations(ONE_STAY, general_rooms=6)
        transmit_rooming_list(ctx["block"]["id"], "INITIAL")
        guest = ctx["attendees"][0]
        reservation = ctx["reservations"][0]
        assert guest["warning_count"] == 0
        assert guest["housing_risk_flag"] is False

        vendor_ctx = setup_vendor_with_incidents(
            ctx["event"]["id"],
            [
                {
                    "attendee_id": guest["id"],
                    "contact_channel": "EMAIL",
                    "occurred_at": "2026-07-20T10:00:00Z",
                },
                {
                    "attendee_id": guest["id"],
                    "contact_channel": "PHONE",
                    "occurred_at": "2026-07-22T09:00:00Z",
                },
            ],
        )
        confirm_vendor(vendor_ctx["vendor"]["id"])

        warned = validate_success(api.get_attendee(guest["id"], COORDINATOR))
        assert warned["warning_count"] == 2
        assert warned["housing_risk_flag"] is True

        after = validate_success(api.get_reservation(reservation["id"], COORDINATOR))
        assert after["eligibility_review_required"] is True
        assert after["transmission_status"] == "CHANGE_PENDING"
        assert after["reservation_status"] == "CONFIRMED"
