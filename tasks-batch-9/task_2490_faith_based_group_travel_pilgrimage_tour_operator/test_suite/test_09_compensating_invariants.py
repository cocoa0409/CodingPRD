"""Compensating actions and the quantities they must restore exactly: cash
across a receipt reversal, and sacred-site pax slots across a service
cancellation."""

from __future__ import annotations

from test_helpers import (
    assert_instant_equals,
    ApiErrorId,
    api_client,
    assign_room,
    cancel_service_booking,
    confirm_traveler,
    create_departure,
    create_plan,
    create_program,
    create_sacred_site,
    create_service_booking,
    enrol_traveler,
    open_departure,
    pay,
    read_plan,
    read_receipt,
    read_service_booking,
    read_traveler,
    validate_error,
    validate_success,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
FINANCE = TEST_USERS["finance_controller"]


# ---------------------------------------------------------------------------
# Money: a reversal walks its own allocation array backwards
# ---------------------------------------------------------------------------


def _plan_funded_by_a_second_receipt():
    """A confirmed traveler on a MONTHLY_3 plan, then a 200,000-cent receipt.

    The plan is created after the deposit, so the 50,000 credit drains into
    installment 1 and leaves it PARTIALLY_PAID; the second receipt then fills
    installment 1 (142,390) and spills 57,610 into installment 2.
    """
    stage = open_departure()
    traveler = enrol_traveler(stage["departure"]["id"], full_name="Traveler A")
    assign_room(traveler["id"])
    pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
    confirm_traveler(traveler["id"])
    plan = create_plan(traveler["id"], "MONTHLY_3", "2026-08-15")
    receipt = pay(traveler["id"], 200_000, method="CARD")
    return traveler, plan, receipt


def _reverse(payment_id: str, reason: str):
    return api_client.reverse_payment(
        payment_id, {"reversal_reason": reason}, FINANCE
    )


def test_reversing_a_receipt_unwinds_its_allocation_with_no_drift(api):
    """PRD §3.7: "The reversal walks the receipt's `allocation` array in
    **reverse list order**, so the `CREDIT` entries appended last are removed
    from `credit_balance_cents` first, and the `INSTALLMENT` entries are then
    unwound in descending `sequence_no`, each subtracting its `amount_cents`
    from that installment's `amount_paid_cents` and re-deriving that
    installment's `status`."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_cash_allocation_conservation
    """
    traveler, plan, receipt = _plan_funded_by_a_second_receipt()

    reversed_receipt = validate_success(_reverse(receipt["id"], "CARD_CHARGEBACK"))
    assert reversed_receipt["status"] == "REVERSED"

    installments = read_plan(plan["id"])["installments"]
    # 577168 over three installments: 192390 / 192389 / 192389.
    assert installments[0]["amount_due_cents"] == 192_390
    # Back to exactly the 50,000 the plan drained out of credit.
    assert installments[0]["amount_paid_cents"] == 50_000
    assert installments[0]["status"] == "PARTIALLY_PAID"
    assert installments[1]["amount_paid_cents"] == 0
    assert installments[1]["status"] == "SCHEDULED"
    assert installments[2]["amount_paid_cents"] == 0
    assert read_plan(plan["id"])["status"] == "ACTIVE"

    live = read_traveler(traveler["id"])
    assert live["cash_applied_cents"] == 50_000
    assert live["credit_balance_cents"] == 0
    assert live["payment_status"] == "PLAN_ACTIVE"
    assert live["booking_status"] == "CONFIRMED"


def test_reversing_the_same_receipt_twice_compensates_only_once(api):
    """PRD §3.7: "The receipt's `status` must be `APPLIED`, and reversing twice
    is `ERR_PAYMENT_ALREADY_REVERSED` (HTTP 409); the traveler must not be
    `CANCELLED`, failing which the answer is `ERR_PILGRIM_NOT_ACTIVE`."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_cash_allocation_conservation
    """
    traveler, plan, receipt = _plan_funded_by_a_second_receipt()
    validate_success(_reverse(receipt["id"], "CARD_CHARGEBACK"))

    response = _reverse(receipt["id"], "CARD_CHARGEBACK")
    validate_error(response, ApiErrorId.PAYMENT_ALREADY_REVERSED.value)

    assert read_receipt(receipt["id"])["status"] == "REVERSED"
    assert read_plan(plan["id"])["installments"][0]["amount_paid_cents"] == 50_000
    assert read_traveler(traveler["id"])["cash_applied_cents"] == 50_000


# ---------------------------------------------------------------------------
# Pax slots: a cancellation returns exactly what the hold took
# ---------------------------------------------------------------------------


def _grotto_holding_twenty_five_pax():
    """A 40-pax-per-day site whose 25-pax liturgy blocks a 20-pax request."""
    program = create_program()
    first = create_departure(program["id"], departure_date="2026-11-01")
    second = create_departure(program["id"], departure_date="2026-11-01")
    site = create_sacred_site(
        name="Grotto of the Annunciation",
        country="IL",
        access_regime="TICKETED_SLOT",
        daily_capacity_pax=40,
        turnaround_buffer_minutes=15,
        requires_local_clergy=False,
    )
    held = create_service_booking(
        first["id"],
        site["id"],
        service_type="LITURGY",
        scheduled_start_utc="2026-11-03T09:00:00Z",
        duration_minutes=60,
        pax_count=25,
        permit_reference="SLOT-9911",
    )
    return site, second, held


def _request_twenty_pax(site_id: str, departure_id: str):
    return api_client.create_service_booking(
        {
            "departure_id": departure_id,
            "sacred_site_id": site_id,
            "service_type": "GUIDED_VISIT",
            "scheduled_start_utc": "2026-11-03T11:00:00Z",
            "duration_minutes": 45,
            "pax_count": 20,
            "permit_reference": "SLOT-9912",
        },
        PLANNER,
    )


def test_cancelling_a_service_returns_its_pax_to_the_day_free_capacity(api):
    """PRD §3.2: "Cancellation vacates the buffered interval and returns
    exactly `pax_count` to the site's free capacity for that date, leaving
    `cancelled_by_risk` false and prompting a recomputation of the departure's
    `service_coverage_ok`."

    Design: Difficulty/compensating_invariant/service_cancel_restores_sacred_site_pax_capacity
    """
    site, second, held = _grotto_holding_twenty_five_pax()

    cancelled = cancel_service_booking(held["id"], "SITE_CLOSED_FOR_RESTORATION")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_by_risk"] is False

    created = validate_success(_request_twenty_pax(site["id"], second["id"]), 201)
    assert created["status"] == "SITE_HELD"
    assert created["pax_count"] == 20
    # 11:00 plus 45 minutes of service plus a 15-minute buffer.
    assert_instant_equals(created["buffered_end_utc"], "2026-11-03T12:00:00Z")


def test_the_same_request_before_the_cancellation_exceeds_the_day_capacity(api):
    """PRD §3.2: "The sum of `pax_count` over the site's bookings whose `status`
    is not `CANCELLED` and whose `scheduled_start_utc` falls on the same UTC
    calendar date, taken together with the requested `pax_count`, must not
    exceed the site's `daily_capacity_pax`; exceeding it is
    `ERR_SITE_DAILY_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/compensating_invariant/service_cancel_restores_sacred_site_pax_capacity
    """
    site, second, held = _grotto_holding_twenty_five_pax()

    response = _request_twenty_pax(site["id"], second["id"])
    validate_error(response, ApiErrorId.SITE_DAILY_CAPACITY_EXCEEDED.value)

    assert read_service_booking(held["id"])["status"] == "SITE_HELD"
