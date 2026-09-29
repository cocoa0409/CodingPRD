"""Two shapes of non-linearity: the bounded terms-negotiation cycle on a block,
and the two independent status axes of a reservation."""

from test_helpers import (
    COORDINATOR,
    assemble_block,
    block_terms_payload,
    cancel_reservation,
    make_hotel_manager_headers,
    read_block,
    register_event,
    register_hotel,
    request_block_changes,
    setup_open_block_with_reservations,
    submit_terms,
    transmit_rooming_list,
    validate_error,
    validate_paginated,
    validate_success,
)

ONE_STAY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
]


def _block_in_negotiation():
    """Event, hotel and a DRAFT block ready for the first terms submission."""
    event = register_event()
    hotel = register_hotel()
    return event, hotel, assemble_block(event["id"], hotel["id"])


def _three_rounds(block, hotel_id):
    """Submit terms three times, the hotel bouncing each one back."""
    block = submit_terms(block)
    block = request_block_changes(block["id"], hotel_id)
    block = submit_terms(block, negotiated_nightly_rate_cents=22400)
    block = request_block_changes(block["id"], hotel_id)
    block = submit_terms(
        block, negotiated_nightly_rate_cents=22900, commission_pct=0.13
    )
    return request_block_changes(block["id"], hotel_id)


class TestNegotiationCycleBound:
    """The block loops between the two negotiation states, but only three times."""

    def test_fourth_terms_submission_is_refused_and_changes_nothing(self, api):
        """PRD §3.2: "The cycle is capped at three submissions in total: a
        submission is accepted only while `revision_round` is strictly less than
        3, so the fourth attempt on the same block is rejected with
        `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/hotel_block_terms_negotiation_cycle_caps_at_three_submissions
        """
        event, hotel, block = _block_in_negotiation()
        block = _three_rounds(block, hotel["id"])
        version_before = block["version"]

        response = api.submit_block_terms(
            block["id"],
            block_terms_payload(
                version_before,
                negotiated_nightly_rate_cents=23400,
                commission_pct=0.13,
            ),
            COORDINATOR,
        )
        validate_error(response, "ERR_NEGOTIATION_ROUNDS_EXHAUSTED", 409)

        after = read_block(block["id"])
        assert after["revision_round"] == 3
        assert after["status"] == "CHANGES_REQUESTED"
        assert after["negotiated_nightly_rate_cents"] == 22900, (
            "the refused submission must not have overwritten the third round's "
            f"rate, got {after['negotiated_nightly_rate_cents']}"
        )
        assert after["version"] == version_before

    def test_each_accepted_round_flips_the_state_and_overwrites_the_terms(self, api):
        """PRD §3.2: "Submitting terms advances the block `DRAFT →
        TERMS_SUBMITTED`, and resubmitting after the hotel pushes back advances
        it `CHANGES_REQUESTED → TERMS_SUBMITTED`; both are coordinator actions
        and both are protected by the stale-block check of §2.8."
        PRD §3.2: "A submission overwrites `negotiated_nightly_rate_cents`,
        `commission_pct`, `rebate_per_room_night_cents`, `cutoff_date` and
        `reduction_rights_pct` wholesale from the payload — there is no partial
        merge — increases `revision_round` by one, and bumps the block's
        `version`."

        Design: Difficulty/non_linear_state_machine/hotel_block_terms_negotiation_cycle_caps_at_three_submissions
        """
        event, hotel, block = _block_in_negotiation()
        assert block["status"] == "DRAFT"
        assert block["revision_round"] == 0

        first = submit_terms(block)
        assert first["status"] == "TERMS_SUBMITTED"
        assert first["revision_round"] == 1

        bounced = request_block_changes(block["id"], hotel["id"])
        assert bounced["status"] == "CHANGES_REQUESTED"
        assert bounced["revision_round"] == 1

        second = submit_terms(bounced, negotiated_nightly_rate_cents=22400)
        assert second["status"] == "TERMS_SUBMITTED"
        assert second["revision_round"] == 2
        assert second["negotiated_nightly_rate_cents"] == 22400

        third = submit_terms(
            request_block_changes(block["id"], hotel["id"]),
            negotiated_nightly_rate_cents=22900,
            commission_pct=0.13,
        )
        assert third["status"] == "TERMS_SUBMITTED"
        assert third["revision_round"] == 3
        assert third["negotiated_nightly_rate_cents"] == 22900
        assert third["commission_pct"] == 0.13
        assert third["version"] > second["version"]


class TestReservationStatusAxes:
    """A cancelled stay still has a rooming-list life of its own."""

    def test_cancelled_stay_is_retransmitted_in_the_next_batch(self, api):
        """PRD §3.5: "The two evolve independently, and the combination that
        surprises people is the legitimate one: a `CANCELLED` reservation can sit
        in `CHANGE_PENDING` and later become `TRANSMITTED` again, because the
        hotel still needs to be told the room went away."
        PRD §3.6: "The batch's `batch_seq` is one more than the number of
        transmissions the block already has, and `transmitted_at` records the
        logical clock at the moment of transmission as an ISO 8601 UTC instant
        with three fractional digits; the batch also records the
        `hotel_block_id` it belongs to."

        Design: Difficulty/non_linear_state_machine/reservation_occupancy_and_transmission_axes_evolve_independently
        """
        ctx = setup_open_block_with_reservations(ONE_STAY, general_rooms=6)
        reservation = ctx["reservations"][0]

        initial = transmit_rooming_list(ctx["block"]["id"], "INITIAL")
        assert initial["batch_seq"] == 1
        assert initial["reservation_count"] == 1

        cancel_reservation(reservation["id"], ctx["attendees"][0]["id"])
        change = transmit_rooming_list(ctx["block"]["id"], "CHANGE")
        assert change["batch_seq"] == 2
        assert change["reservation_count"] == 1
        assert change["included_reservation_ids"] == [reservation["id"]]

        after = validate_success(api.get_reservation(reservation["id"], COORDINATOR))
        assert after["reservation_status"] == "CANCELLED"
        assert after["transmission_status"] == "TRANSMITTED"

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 0
        assert sub_block["available_rooms"] == 6

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 0

    def test_cancellation_moves_only_the_transmission_axis_back_to_pending(self, api):
        """PRD §3.5: "If the reservation was `TRANSMITTED`, it moves
        `TRANSMITTED → CHANGE_PENDING`, because a retraction must still reach the
        hotel."
        PRD §3.4: "Reservations can be listed and filtered by `sub_block_id`,
        `attendee_id`, `reservation_status` and `transmission_status`, the last
        two being genuinely independent axes."

        Design: Difficulty/non_linear_state_machine/reservation_occupancy_and_transmission_axes_evolve_independently
        """
        ctx = setup_open_block_with_reservations(ONE_STAY, general_rooms=6)
        reservation = ctx["reservations"][0]
        assert reservation["transmission_status"] == "NOT_TRANSMITTED"

        transmit_rooming_list(ctx["block"]["id"], "INITIAL")
        transmitted = validate_success(
            api.get_reservation(reservation["id"], COORDINATOR)
        )
        assert transmitted["reservation_status"] == "CONFIRMED"
        assert transmitted["transmission_status"] == "TRANSMITTED"

        cancelled = cancel_reservation(reservation["id"], ctx["attendees"][0]["id"])
        assert cancelled["reservation_status"] == "CANCELLED"
        assert cancelled["transmission_status"] == "CHANGE_PENDING"

        rows, meta = validate_paginated(
            api.list_reservations(
                make_hotel_manager_headers(ctx["hotel"]["id"]),
                params={"transmission_status": "CHANGE_PENDING"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == reservation["id"]
        assert rows[0]["reservation_status"] == "CANCELLED"
