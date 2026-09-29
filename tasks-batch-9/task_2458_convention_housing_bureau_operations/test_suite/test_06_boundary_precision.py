"""Two exact boundaries: a shortfall ratio landing on 0.25, and a transmission
batch whose computed set is exactly empty."""

from test_helpers import (
    COORDINATOR,
    cancel_reservation,
    rooming_list_payload,
    setup_closed_block,
    setup_open_block,
    setup_open_block_with_reservations,
    validate_error,
    validate_paginated,
    validate_success,
)

# 4 of the 8 adjusted room nights are picked up: shortfall 2, ratio exactly 0.25.
STAY_ON_THE_TIER_BOUNDARY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
]

# 3 of the 8: shortfall 3, ratio 0.375, one step past the boundary.
STAY_PAST_THE_TIER_BOUNDARY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-17", "occupants": 1},
]

ONE_STAY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
]


class TestAttritionTierBoundary:
    """The 0.25 tier edge is inclusive, so the ratio 0.25 stays at 70 percent."""

    def test_shortfall_ratio_of_exactly_025_stays_in_the_seventy_percent_tier(
        self, api
    ):
        """PRD §3.7: "The **shortfall** is the protected room nights minus the
        actual room nights, floored at zero — it is never negative. The
        **shortfall ratio** is that shortfall divided by the adjusted contracted
        room nights, and is taken to be zero when the adjusted contracted room
        nights are zero."
        PRD §3.7: "The **penalty rate** is selected by tier from the shortfall
        ratio: 50 percent when the ratio is less than or equal to 0.10; otherwise
        70 percent when the ratio is less than or equal to 0.25; otherwise 90
        percent."
        PRD §3.7: "The **penalty** is the shortfall room nights multiplied by the
        block's `negotiated_nightly_rate_cents` multiplied by the penalty rate,
        rounded half up to whole cents once, at this final step."

        Design: Difficulty/boundary_precision_check/attrition_tier_boundary_at_shortfall_ratio_exactly_025
        """
        ctx = setup_closed_block(
            STAY_ON_THE_TIER_BOUNDARY,
            general_rooms=2,
            contracted_rooms_per_night=2,
            confirmation_number="CN-SUM26-004",
        )

        # Adjusted 8 room nights, actual 4, protected 6, shortfall 2, ratio 0.25.
        assert ctx["block"]["status"] == "CLOSED"
        assert ctx["block"]["attrition_liability_cents"] == 30660, (
            "2 shortfall nights at 21900 cents and the 70 percent tier is 30660, "
            f"got {ctx['block']['attrition_liability_cents']}"
        )
        # Treating 0.25 as past the second tier would price it at 90 percent.
        assert ctx["block"]["attrition_liability_cents"] != 39420

        # The cutoff sweep is what left the block on the boundary: one unsold
        # room of the two went back to the hotel.
        assert ctx["block"]["released_rooms_per_night"] == 1
        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["allotted_rooms"] == 1
        assert sub_block["committed_rooms"] == 1
        assert sub_block["released_rooms"] == 1

    def test_one_night_less_pickup_crosses_into_the_ninety_percent_tier(self, api):
        """PRD §3.7: "The **protected room nights** are the adjusted contracted
        room nights multiplied by the allowed pickup ratio of 80 percent, rounded
        half up to a whole number of room nights."
        PRD §3.7: "The **penalty rate** is selected by tier from the shortfall
        ratio: 50 percent when the ratio is less than or equal to 0.10; otherwise
        70 percent when the ratio is less than or equal to 0.25; otherwise 90
        percent."

        Design: Difficulty/boundary_precision_check/attrition_tier_boundary_at_shortfall_ratio_exactly_025
        """
        ctx = setup_closed_block(
            STAY_PAST_THE_TIER_BOUNDARY,
            general_rooms=2,
            contracted_rooms_per_night=2,
            confirmation_number="CN-SUM26-004",
        )

        # Adjusted 8, actual 3, protected 6, shortfall 3, ratio 0.375.
        assert ctx["block"]["attrition_liability_cents"] == 59130, (
            "3 shortfall nights at 21900 cents and the 90 percent tier is 59130, "
            f"got {ctx['block']['attrition_liability_cents']}"
        )
        # The 70 percent tier would have priced the same shortfall at 45990.
        assert ctx["block"]["attrition_liability_cents"] != 45990

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 3


class TestEmptyTransmissionSet:
    """A batch is computed, so a block with nothing to say cannot transmit."""

    def test_first_transmission_of_a_block_with_no_reservations_is_refused(self, api):
        """PRD §3.6: "If the computed set is empty, nothing is transmitted and the
        request is rejected with `ERR_NO_TRANSMITTABLE_RESERVATIONS`."
        PRD §3.6: "Transmission history for a block is readable in `batch_seq`
        ascending order; because these batches are immutable records of fact, they
        carry only `id` and `created_at` and have neither `updated_at` nor
        `version`."

        Design: Difficulty/boundary_precision_check/rooming_list_with_empty_transmission_set_rejected
        """
        ctx = setup_open_block(general_rooms=6)

        response = api.transmit_rooming_list(
            ctx["block"]["id"], rooming_list_payload("INITIAL"), COORDINATOR
        )
        validate_error(response, "ERR_NO_TRANSMITTABLE_RESERVATIONS", 422)

        rows, meta = validate_paginated(
            api.list_rooming_lists(ctx["block"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_stay_cancelled_before_it_was_ever_transmitted_leaves_the_set_empty(
        self, api
    ):
        """PRD §3.6: "a reservation joins the batch when its `transmission_status`
        is `NOT_TRANSMITTED` or `CHANGE_PENDING`, **and** its `reservation_status`
        is `CONFIRMED`, `CANCELLED` or `NO_SHOW`, **and** it is not the case that
        the reservation is `CANCELLED` or `NO_SHOW` while still
        `NOT_TRANSMITTED` — a stay the hotel was never told about needs no
        retraction."
        PRD §3.6: "If the computed set is empty, nothing is transmitted and the
        request is rejected with `ERR_NO_TRANSMITTABLE_RESERVATIONS`."

        Design: Difficulty/boundary_precision_check/rooming_list_with_empty_transmission_set_rejected
        """
        ctx = setup_open_block_with_reservations(ONE_STAY, general_rooms=6)
        reservation = ctx["reservations"][0]
        cancelled = cancel_reservation(reservation["id"], ctx["attendees"][0]["id"])
        assert cancelled["reservation_status"] == "CANCELLED"
        assert cancelled["transmission_status"] == "NOT_TRANSMITTED"

        response = api.transmit_rooming_list(
            ctx["block"]["id"], rooming_list_payload("INITIAL"), COORDINATOR
        )
        validate_error(response, "ERR_NO_TRANSMITTABLE_RESERVATIONS", 422)

        rows, meta = validate_paginated(
            api.list_rooming_lists(ctx["block"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 0
