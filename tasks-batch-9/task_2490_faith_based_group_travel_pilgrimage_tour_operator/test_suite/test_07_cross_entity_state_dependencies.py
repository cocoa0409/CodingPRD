"""Operations that cannot proceed until a *different* row reaches a state:
senior protection before confirmation, a contracted block before ticketing,
and a closed roster before leader settlement."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    active_agreement,
    api_client,
    assign_room,
    close_sales,
    confirm_traveler,
    create_air_block,
    enrol_traveler,
    file_ticket_name,
    get_success_data,
    offer_fare,
    open_departure,
    pay,
    purchase_protection,
    quote_protection,
    read_agreement,
    read_air_block,
    read_departure,
    read_protection,
    read_traveler,
    validate_error,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
AIR_DESK = TEST_USERS["air_desk_agent"]
FINANCE = TEST_USERS["finance_controller"]


# ---------------------------------------------------------------------------
# Senior protection gates confirmation
# ---------------------------------------------------------------------------


def _senior_traveler_with_a_quoted_policy():
    """A traveler who turns exactly 70 by departure, holding a QUOTED policy."""
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    traveler = enrol_traveler(
        departure_id, full_name="Senior Traveler", date_of_birth="1956-10-31"
    )
    assign_room(traveler["id"], room_label="R-110")
    pay(traveler["id"], 50_000)
    protection = quote_protection(
        traveler["id"], plan_code="STANDARD", medical_limit_cents=3_000_000
    )
    return traveler, protection


def test_confirming_a_seventy_year_old_without_a_purchased_policy_is_rejected(api):
    """PRD §3.5: "A traveler whose `age_at_departure` is 70 or greater must
    already own a travel protection record in `PURCHASED`, failing which the
    answer is `ERR_SENIOR_PROTECTION_REQUIRED` (HTTP 422) — this is the one
    place where the protection dimension gates the booking dimension."

    Design: Difficulty/cross_entity_state_dependency/pilgrim_confirm_blocked_until_senior_protection_purchased
    """
    traveler, protection = _senior_traveler_with_a_quoted_policy()

    response = api_client.confirm_pilgrim(traveler["id"], PLANNER)
    validate_error(response, ApiErrorId.SENIOR_PROTECTION_REQUIRED.value)

    live = read_traveler(traveler["id"])
    assert live["age_at_departure"] == 70
    assert live["booking_status"] == "DEPOSITED"
    assert read_protection(protection["id"])["status"] == "QUOTED"


def test_confirming_the_same_traveler_succeeds_once_the_policy_is_purchased(api):
    """PRD §3.8: "Purchase moves the record to `PURCHASED`, mirrors
    `protection_status`, and copies `premium_cents` onto the traveler's
    `protection_premium_cents`, which raises that traveler's fiscal ceiling for
    receipts."

    Design: Difficulty/cross_entity_state_dependency/pilgrim_confirm_blocked_until_senior_protection_purchased
    """
    traveler, protection = _senior_traveler_with_a_quoted_policy()
    purchased = purchase_protection(protection["id"])

    confirmed = confirm_traveler(traveler["id"])

    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["protection_status"] == "PURCHASED"
    assert confirmed["invoice_total_cents"] == 577_168
    # Age 70 falls in band C at 910bp: 577168 * 910 / 10000 = 52522.288.
    assert purchased["premium_cents"] == 52_522
    assert confirmed["protection_premium_cents"] == 52_522


# ---------------------------------------------------------------------------
# A contracted air block gates ticketing
# ---------------------------------------------------------------------------


def _offered_block_and_confirmed_traveler():
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    block = create_air_block(
        departure_id,
        carrier_code="LY",
        seats_held=10,
        name_change_deadline_utc="2026-09-20T00:00:00Z",
    )
    offer_fare(block["id"], 810_000)
    traveler = enrol_traveler(departure_id, full_name="Traveler A")
    assign_room(traveler["id"])
    pay(traveler["id"], 50_000)
    confirm_traveler(traveler["id"])
    return block, traveler


def test_filing_a_ticketed_name_without_a_contracted_block_is_rejected(api):
    """PRD §3.6: "It requires the departure to have a block in `CONFIRMED`,
    failing which the answer is `ERR_AIR_BLOCK_NOT_CONFIRMED` (HTTP 422); it
    requires the logical clock to be at or before that block's
    `name_change_deadline_utc`, failing which the answer is
    `ERR_NAME_CHANGE_DEADLINE_PASSED` (HTTP 422); and it requires a free seat,
    meaning that when `seats_assigned` has already reached `seats_held` and this
    traveler does not already hold a seat, the answer is
    `ERR_AIR_BLOCK_SEATS_EXHAUSTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ticket_name_blocked_until_air_block_confirmed
    """
    block, traveler = _offered_block_and_confirmed_traveler()

    response = api_client.submit_ticket_name(
        traveler["id"], {"ticketed_name": "TRAVELER/A MR"}, AIR_DESK
    )
    validate_error(response, ApiErrorId.AIR_BLOCK_NOT_CONFIRMED.value)

    live_block = read_air_block(block["id"])
    assert live_block["status"] == "OFFERED"
    assert live_block["seats_assigned"] == 0
    assert read_traveler(traveler["id"])["ticketed_name"] is None


def test_filing_the_same_name_succeeds_once_the_block_is_contracted(api):
    """PRD §3.6: "Confirmation freezes `contracted_fare_cents` at the standing
    `offered_fare_cents` and recomputes `seats_assigned`."

    Design: Difficulty/cross_entity_state_dependency/ticket_name_blocked_until_air_block_confirmed
    """
    block, traveler = _offered_block_and_confirmed_traveler()
    contracted = get_success_data(api_client.confirm_air_block(block["id"], AIR_DESK))

    filed = file_ticket_name(traveler["id"], "TRAVELER/A MR")

    assert contracted["status"] == "CONFIRMED"
    assert contracted["contracted_fare_cents"] == 810_000
    assert filed["ticketed_name"] == "TRAVELER/A MR"
    assert read_air_block(block["id"])["seats_assigned"] == 1


# ---------------------------------------------------------------------------
# A closed roster gates leader settlement
# ---------------------------------------------------------------------------


def _active_agreement_with_two_fully_paid_recruits():
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    agreement = active_agreement(
        departure_id,
        free_travel_threshold=2,
        commission_mode="PER_PAX_CASH",
        commission_rate_cents_per_pax=6000,
        accrual_basis="TRAVELED",
    )
    for full_name in ("Recruit One", "Recruit Two"):
        traveler = enrol_traveler(
            departure_id,
            full_name=full_name,
            recruited_by_agreement_id=agreement["id"],
        )
        assign_room(traveler["id"])
        pay(traveler["id"], 50_000)
        confirm_traveler(traveler["id"])
        pay(traveler["id"], 527_168)
    return departure_id, agreement


def test_settling_a_leader_while_sales_are_still_open_is_rejected(api):
    """PRD §3.4: "It requires the agreement to be `ACTIVE`, failing which the
    answer is `ERR_AGREEMENT_INVALID_STATE`, and it requires the parent
    departure's status to be `SALES_CLOSED` or `OPERATED`, failing which the
    answer is `ERR_DEPARTURE_INVALID_STATE` — there is no traveled basis to
    settle against until the roster has closed."

    Design: Difficulty/cross_entity_state_dependency/leader_settle_blocked_until_departure_sales_closed
    """
    departure_id, agreement = _active_agreement_with_two_fully_paid_recruits()

    response = api_client.settle_agreement(agreement["id"], FINANCE)
    validate_error(response, ApiErrorId.DEPARTURE_INVALID_STATE.value)

    assert read_departure(departure_id)["status"] == "OPEN_FOR_SALE"
    live = read_agreement(agreement["id"])
    assert live["status"] == "ACTIVE"
    assert live["recruited_paying_count"] == 2
    assert live["commission_payable_cents"] == 12_000
    assert live["settled_commission_cents"] == 0


def test_settling_the_same_leader_succeeds_once_the_roster_closes(api):
    """PRD §3.4: "Settlement is a `FinanceController` action that moves an
    `ACTIVE` agreement to `SETTLED`."

    Design: Difficulty/cross_entity_state_dependency/leader_settle_blocked_until_departure_sales_closed
    """
    departure_id, agreement = _active_agreement_with_two_fully_paid_recruits()
    closed = close_sales(departure_id)

    settled = get_success_data(api_client.settle_agreement(agreement["id"], FINANCE))

    assert closed["status"] == "SALES_CLOSED"
    assert closed["final_tier_code"] == "T1"
    assert closed["final_per_pax_price_cents"] == 587_000
    assert settled["status"] == "SETTLED"
    assert settled["settled_recruited_count"] == 2
    assert settled["settled_earned_free_seats"] == 1
    assert settled["settled_commission_cents"] == 12_000
