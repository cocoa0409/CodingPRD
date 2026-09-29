"""Boundaries measured one unit either side: the cancellation grid at 90 and
89 days, the seat block at its last seat and one past it, and the medical
uplift threshold at exactly and one cent above 5,000,000."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    api_client,
    assign_room,
    confirm_traveler,
    confirmed_air_block,
    create_departure,
    create_program,
    decide_waiver,
    enrol_traveler,
    file_ticket_name,
    get_success_data,
    open_departure,
    pay,
    quote_protection,
    read_air_block,
    read_traveler,
    review_protection,
    rome_jubilee_program_payload,
    set_clock,
    validate_error,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
AIR_DESK = TEST_USERS["air_desk_agent"]
NURSE = TEST_USERS["protection_nurse"]
UNDERWRITER = TEST_USERS["protection_underwriter"]


# ---------------------------------------------------------------------------
# The cancellation grid at 90 days and at 89
# ---------------------------------------------------------------------------


def _two_travelers_with_cash():
    """Two roomed travelers on a 2026-11-01 departure, 250,000 cents paid each."""
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    travelers = []
    for full_name, label in (("Traveler A", "R-101"), ("Traveler B", "R-102")):
        traveler = enrol_traveler(departure_id, full_name=full_name)
        assign_room(traveler["id"], room_label=label)
        pay(traveler["id"], 250_000)
        travelers.append(traveler)
    return travelers


def _cancel(pilgrim_id: str, reason: str) -> dict:
    return get_success_data(
        api_client.cancel_pilgrim(pilgrim_id, {"cancellation_reason": reason}, PLANNER)
    )


def test_cancellation_exactly_ninety_days_out_sits_in_the_more_generous_bucket(api):
    """PRD §3.5: "It then selects the bucket of the program's
    `cancellation_grid` with the **greatest** `min_days_before` that the
    days-before figure still reaches, comparing **inclusively**: a days-before
    figure exactly equal to a breakpoint sits in the more generous bucket, not
    the harsher one."

    Design: Difficulty/boundary_precision_check/cancellation_grid_day_boundary_90_vs_89
    """
    travelers = _two_travelers_with_cash()
    set_clock("2026-08-03T00:00:00Z")

    cancelled = _cancel(travelers[0]["id"], "SCHEDULE_CONFLICT")

    assert cancelled["invoice_total_cents"] == 577_168
    # Exactly 90 days out: the 1000bp bucket, 577168 * 1000 / 10000 -> 57717.
    assert cancelled["penalty_retained_cents"] == 57_717
    assert cancelled["refund_cents"] == 192_283
    assert cancelled["payment_status"] == "REFUNDED"


def test_cancellation_one_day_later_falls_into_the_harsher_bucket(api):
    """PRD §3.5: "It then selects the bucket of the program's
    `cancellation_grid` with the **greatest** `min_days_before` that the
    days-before figure still reaches, comparing **inclusively**: a days-before
    figure exactly equal to a breakpoint sits in the more generous bucket, not
    the harsher one."

    Design: Difficulty/boundary_precision_check/cancellation_grid_day_boundary_90_vs_89
    """
    travelers = _two_travelers_with_cash()
    set_clock("2026-08-04T00:00:00Z")

    cancelled = _cancel(travelers[1]["id"], "SCHEDULE_CONFLICT")

    # 89 days out no longer reaches the 90-day breakpoint: 3500bp applies,
    # 577168 * 3500 / 10000 = 202008.8 -> 202009.
    assert cancelled["penalty_retained_cents"] == 202_009
    assert cancelled["refund_cents"] == 47_991


# ---------------------------------------------------------------------------
# The seat block at its last seat and one past it
# ---------------------------------------------------------------------------


def _two_seat_block_with_three_confirmed_travelers():
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    block = confirmed_air_block(
        departure_id,
        offered_fare_cents=810_000,
        carrier_code="LY",
        seats_held=2,
        name_change_deadline_utc="2026-09-20T00:00:00Z",
    )
    travelers = []
    for full_name in ("Traveler A", "Traveler B", "Traveler C"):
        traveler = enrol_traveler(departure_id, full_name=full_name)
        assign_room(traveler["id"])
        pay(traveler["id"], 50_000)
        confirm_traveler(traveler["id"])
        travelers.append(traveler)
    file_ticket_name(travelers[0]["id"], "TRAVELER/A MR")
    return block, travelers


def test_the_last_free_seat_of_the_block_accepts_a_ticketed_name(api):
    """PRD §3.6: "`seats_assigned` is not an incrementing counter but a derived
    count: the number of travelers on the same departure who carry a non-null
    `ticketed_name` and whose `booking_status` is `DEPOSITED` or `CONFIRMED`."

    Design: Difficulty/boundary_precision_check/air_block_seat_count_boundary_last_seat_vs_exhausted
    """
    block, travelers = _two_seat_block_with_three_confirmed_travelers()

    filed = file_ticket_name(travelers[1]["id"], "TRAVELER/B MRS")
    assert filed["ticketed_name"] == "TRAVELER/B MRS"
    assert read_air_block(block["id"])["seats_assigned"] == 2


def test_one_seat_past_the_block_capacity_is_rejected(api):
    """PRD §3.6: "and it requires a free seat, meaning that when
    `seats_assigned` has already reached `seats_held` and this traveler does not
    already hold a seat, the answer is `ERR_AIR_BLOCK_SEATS_EXHAUSTED` (HTTP
    409)."

    Design: Difficulty/boundary_precision_check/air_block_seat_count_boundary_last_seat_vs_exhausted
    """
    block, travelers = _two_seat_block_with_three_confirmed_travelers()
    file_ticket_name(travelers[1]["id"], "TRAVELER/B MRS")

    response = api_client.submit_ticket_name(
        travelers[2]["id"], {"ticketed_name": "TRAVELER/C MR"}, AIR_DESK
    )
    validate_error(response, ApiErrorId.AIR_BLOCK_SEATS_EXHAUSTED.value)

    assert read_air_block(block["id"])["seats_assigned"] == 2
    assert read_traveler(travelers[2]["id"])["ticketed_name"] is None


# ---------------------------------------------------------------------------
# The medical uplift threshold, exactly at and one cent above
# ---------------------------------------------------------------------------


def _approved_waiver_at_medical_limit(medical_limit_cents: int, room_label: str):
    """A band-D traveler whose waiver is approved inside the deposit window."""
    program = create_program(payload=rome_jubilee_program_payload())
    departure = create_departure(
        program["id"],
        departure_date="2027-03-14",
        return_date="2027-03-22",
        min_pax=1,
        max_pax=12,
        deposit_due_date="2026-09-01",
        final_payment_due_date="2027-01-15",
    )
    traveler = enrol_traveler(
        departure["id"], full_name="Senior Insured", date_of_birth="1948-06-20"
    )
    assign_room(traveler["id"], room_label=room_label)
    # Quoted before the deposit so the crossing receipt can anchor the window.
    protection = quote_protection(
        traveler["id"],
        plan_code="PREMIER",
        medical_limit_cents=medical_limit_cents,
        pre_existing_waiver_requested=True,
    )
    pay(traveler["id"], 200_000)
    review_protection(protection["id"], NURSE, stable_period_days=400)
    decided = decide_waiver(protection["id"], "APPROVE", UNDERWRITER)
    # Re-read: the enrolment response predates rooming, which is the call that
    # first recomputes the invoice (§3.5), so the enrolment row still shows 0.
    return read_traveler(traveler["id"]), decided


def test_a_medical_limit_exactly_at_the_threshold_attracts_no_uplift(api):
    """PRD §3.8: "The medical uplift then applies only when
    `medical_limit_cents` is **strictly greater** than $50,000.00 (5,000,000
    cents): a limit exactly at the threshold attracts no uplift, and above it
    `medical_uplift_cents` is `base_premium_cents` multiplied by 1,500 basis
    points (15%), divided by 10,000, rounded half up; otherwise it is 0."

    Design: Difficulty/boundary_precision_check/medical_uplift_threshold_strictly_greater_than_money_edge
    """
    traveler, decided = _approved_waiver_at_medical_limit(5_000_000, "IT-201")

    assert traveler["invoice_total_cents"] == 1_966_500
    assert decided["insured_trip_cost_cents"] == 1_966_500
    assert decided["age_band"] == "D"
    assert decided["base_premium_cents"] == 251_712
    assert decided["medical_uplift_cents"] == 0
    assert decided["waiver_surcharge_cents"] == 45_000
    assert decided["premium_cents"] == 296_712
    assert decided["status"] == "WAIVER_APPROVED"


def test_a_medical_limit_one_cent_above_the_threshold_attracts_the_uplift(api):
    """PRD §3.8: "The medical uplift then applies only when
    `medical_limit_cents` is **strictly greater** than $50,000.00 (5,000,000
    cents): a limit exactly at the threshold attracts no uplift, and above it
    `medical_uplift_cents` is `base_premium_cents` multiplied by 1,500 basis
    points (15%), divided by 10,000, rounded half up; otherwise it is 0."

    Design: Difficulty/boundary_precision_check/medical_uplift_threshold_strictly_greater_than_money_edge
    """
    _traveler, decided = _approved_waiver_at_medical_limit(5_000_001, "IT-202")

    assert decided["base_premium_cents"] == 251_712
    # 251712 * 1500 / 10000 = 37756.8 -> 37757.
    assert decided["medical_uplift_cents"] == 37_757
    assert decided["waiver_surcharge_cents"] == 45_000
    assert decided["premium_cents"] == 334_469
