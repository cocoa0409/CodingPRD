"""Bookings that violate two rules at once, where §2.10 decides which error the
caller is told about."""

from test_helpers import (
    COORDINATOR,
    create_reservation_payload,
    make_attendee_headers,
    read_block,
    reject_sub_block,
    setup_flagged_attendee,
    setup_housing_program,
    validate_error,
    validate_paginated,
    validate_success,
)

VIP_GUEST = {
    "email": "vip1@example.com",
    "full_name": "Vip One",
    "registration_id": "REG-V1",
    "attendee_type": "VIP",
    "eligibility_codes": ["VIP-GOLD"],
}
SECOND_VIP_GUEST = {
    "email": "vip2@example.com",
    "full_name": "Vip Two",
    "registration_id": "REG-V2",
    "attendee_type": "VIP",
    "eligibility_codes": ["VIP-GOLD"],
}
FULL_WINDOW = {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18"}


def _book(api, sub_block_id, attendee, **overrides):
    payload = create_reservation_payload(
        sub_block_id, attendee["id"], **{**FULL_WINDOW, **overrides}
    )
    return api.create_reservation(payload, make_attendee_headers(attendee["id"]))


class TestSubBlockStateOutranksNightCapacity:
    """A rejected sub-block has no rooms, but its state is the reported failure."""

    def test_booking_a_rejected_sub_block_reports_the_state_error(self, api):
        """PRD §2.10: "**Own-state transition legality** — the target resource is in
        a state from which the requested transition exists."
        PRD §3.4: "the target sub-block itself must be in `APPROVED`, and a
        booking into a `PENDING_APPROVAL`, `REJECTED` or `RELEASED` sub-block is
        rejected with `ERR_INVALID_SUB_BLOCK_STATE`."
        PRD §3.3: "Controller rejection moves it `PENDING_APPROVAL → REJECTED`, a
        terminal state, and unwinds the carve completely: the rooms go back where
        they came from — added to the block's `unassigned_rooms_per_night` when
        `parent_sub_block_id` is null, or added back to the parent sub-block's
        `allotted_rooms` when it is not — and the rejected sub-block's own
        `allotted_rooms` is set to 0."

        Design: Difficulty/priority_pair_validation_conflict/rejected_sub_block_state_beats_night_capacity_exceeded
        """
        ctx = setup_housing_program(
            contracted_rooms_per_night=10,
            carves=[
                {"segment": "GENERAL", "allotted_rooms": 6},
                {
                    "segment": "VIP",
                    "allotted_rooms": 2,
                    "eligibility_code": "VIP-GOLD",
                },
            ],
            open_portal=True,
            attendees=[VIP_GUEST],
        )
        vip_sub_block = reject_sub_block(ctx["sub_blocks"][1]["id"])

        response = _book(api, vip_sub_block["id"], ctx["attendees"][0])
        # allotted_rooms is 0, so the night-capacity rule at step 18 is violated
        # too; step 8 is the one that must answer.
        validate_error(response, "ERR_INVALID_SUB_BLOCK_STATE", 409)

        after = validate_success(api.get_sub_block(vip_sub_block["id"], COORDINATOR))
        assert after["approval_status"] == "REJECTED"
        assert after["allotted_rooms"] == 0
        assert after["committed_rooms"] == 0
        assert read_block(ctx["block"]["id"])["unassigned_rooms_per_night"] == 4

        rows, meta = validate_paginated(
            api.list_reservations(
                COORDINATOR, params={"sub_block_id": vip_sub_block["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_night_capacity_answers_once_the_sub_block_state_is_legal(self, api):
        """PRD §3.4: "Third, the **night capacity admission test**, which uses the
        half-open geometry of §3.3 instead: for every night the candidate stay
        would occupy, the count of `CONFIRMED` reservations already covering that
        night, plus one for the candidate, must be less than or equal to the
        sub-block's `allotted_rooms`."
        PRD §3.4: "A single night that fails rejects the whole booking with
        `ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/rejected_sub_block_state_beats_night_capacity_exceeded
        """
        ctx = setup_housing_program(
            contracted_rooms_per_night=10,
            carves=[
                {"segment": "GENERAL", "allotted_rooms": 6},
                {
                    "segment": "VIP",
                    "allotted_rooms": 1,
                    "eligibility_code": "VIP-GOLD",
                    "approve": True,
                },
            ],
            open_portal=True,
            attendees=[VIP_GUEST, SECOND_VIP_GUEST],
            reservations=[{"attendee": 0, "sub_block": 1, **FULL_WINDOW}],
        )
        vip_sub_block = ctx["sub_blocks"][1]

        response = _book(api, vip_sub_block["id"], ctx["attendees"][1])
        validate_error(response, "ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED", 409)

        after = validate_success(api.get_sub_block(vip_sub_block["id"], COORDINATOR))
        assert after["approval_status"] == "APPROVED"
        assert after["committed_rooms"] == 1
        assert after["available_rooms"] == 0


class TestHousingRiskHoldOutranksEligibility:
    """A flagged delegate is stopped before the segregation check is consulted."""

    def test_flagged_guest_booking_a_closed_segment_reports_the_risk_hold(self, api):
        """PRD §2.10: "**Housing-risk hold.** `ERR_ATTENDEE_HOUSING_RISK_HOLD` (409)
        on a reservation booking or a reservation change whose guest has
        `housing_risk_flag` set to true."
        PRD §3.4: "Bookings are also blocked on the guest's standing. If the
        delegate's `housing_risk_flag` is true, no reservation may be opened or
        changed for them until a controller clears the flag, and the attempt is
        rejected with `ERR_ATTENDEE_HOUSING_RISK_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/housing_risk_hold_beats_sub_block_eligibility_mismatch
        """
        ctx = setup_housing_program(
            contracted_rooms_per_night=10,
            carves=[
                {"segment": "GENERAL", "allotted_rooms": 6},
                {
                    "segment": "VIP",
                    "allotted_rooms": 2,
                    "eligibility_code": "VIP-GOLD",
                    "approve": True,
                },
            ],
            open_portal=True,
            attendees=[{}],
        )
        ctx = setup_flagged_attendee(ctx)
        guest = ctx["attendees"][0]
        vip_sub_block = ctx["sub_blocks"][1]

        # The guest is GENERAL with no eligibility codes, so the VIP carve is
        # also referentially closed to them; the hold must answer first.
        response = _book(api, vip_sub_block["id"], guest)
        validate_error(response, "ERR_ATTENDEE_HOUSING_RISK_HOLD", 409)

        assert guest["housing_risk_flag"] is True
        assert guest["warning_count"] == 2
        after = validate_success(api.get_sub_block(vip_sub_block["id"], COORDINATOR))
        assert after["approval_status"] == "APPROVED"
        assert after["committed_rooms"] == 0

        rows, meta = validate_paginated(
            api.list_reservations(COORDINATOR, params={"attendee_id": guest["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_eligibility_answers_for_an_unflagged_guest_on_the_same_carve(self, api):
        """PRD §3.4: "For a sub-block whose `segment` is anything other than
        `GENERAL`, the guest's `attendee_type` must equal that `segment` and the
        sub-block's `eligibility_code` must appear among the guest's
        `eligibility_codes`; independently of segment, the guest's `event_id` must
        equal the `event_id` of the block the sub-block hangs from."
        PRD §3.4: "Any of those three conditions failing rejects the booking with
        `ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/housing_risk_hold_beats_sub_block_eligibility_mismatch
        """
        ctx = setup_housing_program(
            contracted_rooms_per_night=10,
            carves=[
                {"segment": "GENERAL", "allotted_rooms": 6},
                {
                    "segment": "VIP",
                    "allotted_rooms": 2,
                    "eligibility_code": "VIP-GOLD",
                    "approve": True,
                },
            ],
            open_portal=True,
            attendees=[{}],
        )
        guest = ctx["attendees"][0]
        assert guest["housing_risk_flag"] is False
        assert guest["attendee_type"] == "GENERAL"

        response = _book(api, ctx["sub_blocks"][1]["id"], guest)
        validate_error(response, "ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH", 422)
