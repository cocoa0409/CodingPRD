"""The three counter-intuitive inversions of the validation ladder, each
paired with the control that shows the lower-ranked rule really was armed."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    api_client,
    assign_room,
    confirm_traveler,
    confirmed_air_block,
    create_departure,
    create_program,
    deposited_traveler,
    enrol_traveler,
    file_ticket_name,
    active_agreement,
    open_departure,
    read_air_block,
    read_departure,
    read_traveler,
    set_clock,
    validate_error,
    TEST_USERS,
    get_success_data,
)

PLANNER = TEST_USERS["program_manager"]
FINANCE = TEST_USERS["finance_controller"]
AIR_DESK = TEST_USERS["air_desk_agent"]


# ---------------------------------------------------------------------------
# Traveler state above the fiscal ceiling
# ---------------------------------------------------------------------------


def _deposited_pair():
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    first = deposited_traveler(departure_id, full_name="Traveler A")
    second = deposited_traveler(departure_id, full_name="Traveler B")
    return departure_id, first, second


def test_receipt_against_a_cancelled_traveler_reports_state_not_overpayment(api):
    """PRD §2.9: "A cash receipt against a cancelled traveler that would also
    overshoot the invoice answers `ERR_PILGRIM_NOT_ACTIVE`, because traveler
    state sits far above the fiscal ceiling."

    Design: Difficulty/priority_pair_validation_conflict/payment_on_cancelled_pilgrim_state_beats_fiscal_ceiling
    """
    _departure_id, first, _second = _deposited_pair()
    get_success_data(
        api_client.cancel_pilgrim(first["id"], {"cancellation_reason": "MEDICAL"}, PLANNER)
    )

    response = api_client.record_payment(
        first["id"], {"amount_cents": 900_000, "method": "CARD"}, FINANCE
    )
    validate_error(response, ApiErrorId.PILGRIM_NOT_ACTIVE.value)

    assert read_traveler(first["id"])["booking_status"] == "CANCELLED"


def test_the_same_oversized_receipt_on_a_live_traveler_reports_overpayment(api):
    """PRD §3.7: "The receipt is also subject to a fiscal ceiling:
    `cash_applied_cents` plus the new `amount_cents` must not exceed
    `invoice_total_cents` plus `protection_premium_cents`."

    Design: Difficulty/priority_pair_validation_conflict/payment_on_cancelled_pilgrim_state_beats_fiscal_ceiling
    """
    _departure_id, _first, second = _deposited_pair()

    response = api_client.record_payment(
        second["id"], {"amount_cents": 900_000, "method": "CARD"}, FINANCE
    )
    validate_error(response, ApiErrorId.OVERPAYMENT_NOT_ALLOWED.value)

    assert read_traveler(second["id"])["cash_applied_cents"] == 50_000


# ---------------------------------------------------------------------------
# Mobility safety above the agreement-mismatch rule
# ---------------------------------------------------------------------------


def _two_departures_with_a_foreign_agreement():
    """Departure X has no accessible coach; the agreement belongs to departure Y."""
    program = create_program()
    departure_x = create_departure(
        program["id"], departure_date="2026-11-01", mobility_accessible_coach=False
    )
    departure_y = create_departure(
        program["id"],
        departure_date="2026-12-01",
        return_date="2026-12-11",
        mobility_accessible_coach=True,
    )
    agreement = active_agreement(
        departure_y["id"],
        leader_name="Dcn. Ruth Nakamura",
        leader_user_id="u-leader-ruth",
        free_travel_threshold=6,
        commission_mode="PER_PAX_CASH",
        commission_rate_cents_per_pax=5000,
    )
    return departure_x, departure_y, agreement


def test_wheelchair_enrolment_reports_mobility_before_agreement_mismatch(api):
    """PRD §2.9: "A wheelchair traveler enrolled with another leader's agreement
    onto a departure with no accessible coach answers
    `ERR_MOBILITY_UNSUPPORTED`, because the mobility rule outranks the
    agreement-mismatch rule."

    Design: Difficulty/priority_pair_validation_conflict/mobility_safety_beats_agreement_referential_mismatch
    """
    departure_x, _departure_y, agreement = _two_departures_with_a_foreign_agreement()

    response = api_client.create_pilgrim(
        {
            "departure_id": departure_x["id"],
            "full_name": "Wheelchair Traveler",
            "date_of_birth": "1952-04-04",
            "room_type_requested": "SINGLE",
            "recruited_by_agreement_id": agreement["id"],
            "mobility_code": "WHEELCHAIR",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.MOBILITY_UNSUPPORTED.value)

    assert read_departure(departure_x["id"])["paying_pax_count"] == 0


def test_the_same_foreign_agreement_without_wheelchair_reports_the_mismatch(api):
    """PRD §3.5: "When a `recruited_by_agreement_id` is supplied, that
    agreement's `departure_id` must equal the supplied `departure_id` and its
    `status` must be `PENDING_COUNTERSIGN` or `ACTIVE`, failing which the answer
    is `ERR_AGREEMENT_DEPARTURE_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/mobility_safety_beats_agreement_referential_mismatch
    """
    departure_x, _departure_y, agreement = _two_departures_with_a_foreign_agreement()

    response = api_client.create_pilgrim(
        {
            "departure_id": departure_x["id"],
            "full_name": "Ambulant Traveler",
            "date_of_birth": "1952-04-04",
            "room_type_requested": "SINGLE",
            "recruited_by_agreement_id": agreement["id"],
            "mobility_code": "NONE",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.AGREEMENT_DEPARTURE_MISMATCH.value)

    assert read_departure(departure_x["id"])["paying_pax_count"] == 0


# ---------------------------------------------------------------------------
# The name-change deadline above seat exhaustion
# ---------------------------------------------------------------------------


def _single_seat_block_with_two_confirmed_travelers():
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    block = confirmed_air_block(
        departure_id,
        offered_fare_cents=810_000,
        carrier_code="LY",
        seats_held=1,
        name_change_deadline_utc="2026-09-20T00:00:00Z",
    )
    travelers = []
    for full_name in ("Traveler A", "Traveler B"):
        traveler = enrol_traveler(departure_id, full_name=full_name)
        assign_room(traveler["id"])
        get_success_data(
            api_client.record_payment(
                traveler["id"], {"amount_cents": 50_000, "method": "ACH"}, FINANCE
            )
        )
        confirm_traveler(traveler["id"])
        travelers.append(traveler)
    file_ticket_name(travelers[0]["id"], "TRAVELER/A MR")
    return block, travelers


def test_late_ticketed_name_on_a_full_block_reports_the_deadline(api):
    """PRD §2.9: "And a late ticketed-name submission against a seat block that
    is already full answers `ERR_NAME_CHANGE_DEADLINE_PASSED`, because the
    deadline rule outranks the seat-exhaustion rule."

    Design: Difficulty/priority_pair_validation_conflict/ticket_name_temporal_deadline_beats_seat_exhaustion
    """
    block, travelers = _single_seat_block_with_two_confirmed_travelers()
    set_clock("2026-09-21T00:00:00Z")

    response = api_client.submit_ticket_name(
        travelers[1]["id"], {"ticketed_name": "TRAVELER/B MRS"}, AIR_DESK
    )
    validate_error(response, ApiErrorId.NAME_CHANGE_DEADLINE_PASSED.value)

    assert read_air_block(block["id"])["seats_assigned"] == 1
    assert read_traveler(travelers[1]["id"])["ticketed_name"] is None


def test_the_same_submission_inside_the_deadline_reports_seat_exhaustion(api):
    """PRD §3.6: "and it requires a free seat, meaning that when
    `seats_assigned` has already reached `seats_held` and this traveler does not
    already hold a seat, the answer is `ERR_AIR_BLOCK_SEATS_EXHAUSTED` (HTTP
    409)."

    Design: Difficulty/priority_pair_validation_conflict/ticket_name_temporal_deadline_beats_seat_exhaustion
    """
    block, travelers = _single_seat_block_with_two_confirmed_travelers()
    set_clock("2026-08-10T00:00:00Z")

    response = api_client.submit_ticket_name(
        travelers[1]["id"], {"ticketed_name": "TRAVELER/B MRS"}, AIR_DESK
    )
    validate_error(response, ApiErrorId.AIR_BLOCK_SEATS_EXHAUSTED.value)

    assert read_air_block(block["id"])["seats_assigned"] == 1
