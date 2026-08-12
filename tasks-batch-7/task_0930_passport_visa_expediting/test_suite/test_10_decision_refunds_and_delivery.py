"""The agency decision, its four-level rejection cascade, and the return delivery."""

from test_helpers import (
    ApiErrorId,
    agency_decision,
    book_appointment,
    build_scenario,
    complete_leg,
    dispatch_leg,
    list_legs,
    new_slot,
    read_applicant,
    read_appointment,
    read_order,
    read_shipment,
    read_slot,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AGENCY, CASE_MANAGER, COURIER


# ==========================================================================
# The rejection cascade: order -> traveller -> appointment -> slot capacity
# ==========================================================================
def _at_agency_order_with_interview_booked_before_tender():
    """The interview is booked while the file is still with the traveller, then the order
    is driven to AT_AGENCY around it."""
    from test_helpers.fixtures import (
        accept_quote,
        add_photo,
        check_photo,
        new_active_form,
        new_applicant,
        new_catalog_item,
        new_consulate,
        new_document_requirement,
        new_order,
        pay,
        prepare_form,
        quote,
        review_doc,
        run_leg,
        submit_doc,
        submit_order,
        tender_order,
    )

    set_clock("2026-06-01T09:00:00Z")
    form = new_active_form()
    catalog = new_catalog_item(visa_type="TOURIST")
    new_document_requirement(catalog["id"])
    consulate = new_consulate()
    slot = new_slot(consulate["id"], starts_at="2026-06-05T10:00:00Z", capacity=1)
    order = new_order(catalog["id"], consulate_id=consulate["id"])
    applicant = new_applicant(order["id"], full_name="Reject Cascade")
    appointment = book_appointment(applicant["id"], slot["id"])

    passport = submit_doc(applicant["id"])
    review_doc(passport["id"], "ACCEPT")
    photo = add_photo(applicant["id"])
    check_photo(photo["id"])
    prepare_form(applicant["id"], form["id"])

    quoted = quote(order["id"])
    pay(order["id"], quoted["total_quoted_cents"])
    accept_quote(order["id"])
    run_leg(order["id"], leg_index=1, from_holder="APPLICANT", to_holder="SERVICE",
            scheduled_date="2026-06-01")
    submit_order(order["id"])
    run_leg(order["id"], leg_index=2, from_holder="SERVICE", to_holder="AGENCY",
            scheduled_date="2026-06-02")
    tender_order(order["id"])
    return order, applicant, slot, appointment


def test_agency_rejection_withdraws_the_traveller_and_frees_the_interview_seat(api):
    """PRD §3.11: "*Hop 1:* every traveller of this order whose `readiness_status` is
    `PENDING` or `COMPLETE` is set to `WITHDRAWN`; travellers already `WITHDRAWN` are
    untouched. *Hop 2:* because those travellers are now withdrawn, every appointment of
    theirs whose `booking_status` is `BOOKED` moves to `CANCELLED`; appointments in
    `ATTENDED`, `NO_SHOW` or `CANCELLED` are untouched. *Hop 3:* because those appointments
    were cancelled, each referenced slot's `booked_count` is decremented and its `status`
    re-derived — a slot that was `FULL` returns to `OPEN` once `booked_count` falls below
    `capacity`, while a slot whose calendar date sits in its mission's `closure_dates` stays
    `CLOSED` regardless."

    Design: Difficulty/transitive_cascade/agency_rejection_cascades_from_order_to_slot_capacity
    """
    order, applicant, slot, appointment = _at_agency_order_with_interview_booked_before_tender()
    assert read_slot(slot["id"])["status"] == "FULL"

    rejected = validate_success(
        api.record_agency_decision(order["id"], {"decision": "REJECTED"}, AGENCY)
    )
    assert rejected["workflow_status"] == "REJECTED"

    assert read_applicant(applicant["id"])["readiness_status"] == "WITHDRAWN"
    assert read_appointment(appointment["id"])["booking_status"] == "CANCELLED"
    stored_slot = read_slot(slot["id"])
    assert stored_slot["booked_count"] == 0
    assert stored_slot["status"] == "OPEN"


def test_agency_rejection_schedules_the_post_tender_refund_and_opens_the_return_hop(api):
    """PRD §3.11: "*The post-tender variant* runs when `government_tendered_cents` is
    strictly above 0. The government refund is **0** — the pass-through money is with the
    agency and is never returned. No ledger row is written yet: instead
    `refund_scheduled_cents` is set to the adjudicated total and `payment_status` moves to
    `REFUND_PENDING`."
    PRD §3.11: "Both branches stamp `decided_at` with the logical clock, close the open SLA
    segment by writing its `ended_at` and `business_minutes`, and create the return hop from
    `AGENCY` to `SERVICE` in `leg_status` `CREATED`, with a `leg_index` one above the
    highest existing hop on the order and a `scheduled_date` equal to the calendar date of
    the logical clock at decision time."

    Design: Difficulty/transitive_cascade/agency_rejection_cascades_from_order_to_slot_capacity
    """
    order, _applicant, _slot, _appointment = _at_agency_order_with_interview_booked_before_tender()

    validate_success(api.record_agency_decision(order["id"], {"decision": "REJECTED"}, AGENCY))

    stored = read_order(order["id"])
    assert stored["payment_status"] == "REFUND_PENDING"
    # 10500 collected on the SERVICE stream at the 0.15 AT_AGENCY fraction.
    assert stored["refund_scheduled_cents"] == 1575
    assert stored["refunded_cents"] == 0, "no ledger row is written until the book comes back"

    legs = list_legs(order["id"])
    assert len(legs) == 3, f"a third hop is created by the decision, got {len(legs)}"
    return_leg = legs[-1]
    assert return_leg["from_holder"] == "AGENCY"
    assert return_leg["to_holder"] == "SERVICE"
    assert return_leg["leg_status"] == "CREATED"


# ==========================================================================
# Cancelling out of agency custody, and the return shipment
# ==========================================================================
def test_cancelling_from_agency_custody_demands_an_explicit_forfeit_acknowledgment(api):
    """PRD §3.12: "Cancellation from `AT_AGENCY` is the cancellation-with-restrictions
    path: it is on the agency-custody gate's exclusion list precisely so that it can be
    reached, and it demands the request carry `acknowledge_government_fee_forfeit` set to
    true, or it is refused with `ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED` — the tendered
    government fee is gone and the customer must say so in writing."
    PRD §3.10: "From this instant the pass-through money belongs to the agency and no
    refund path can ever bring it back."

    Design: Corner/errors/corner_error_government_fee_forfeit_unacknowledged_on_cancel
    """
    scenario = build_scenario("at_agency", visa_type="PASSPORT_RENEWAL")
    order_id = scenario["order_id"]

    refused = api.cancel_order(order_id, CASE_MANAGER, {})
    validate_error(refused, ApiErrorId.ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED.value)

    cancelled = validate_success(
        api.cancel_order(order_id, CASE_MANAGER, {"acknowledge_government_fee_forfeit": True})
    )
    assert cancelled["workflow_status"] == "CANCELLED"

    stored = read_order(order_id)
    assert stored["government_tendered_cents"] == 16000
    assert stored["payment_status"] == "REFUND_PENDING"
    assert stored["refund_scheduled_cents"] == 1575
    assert stored["refunded_cents"] == 0


def test_ground_shipment_close_to_travel_escalates_and_the_attempt_cap_holds_it_for_pickup(api):
    """PRD §3.11: "When the requested `method` is `GROUND` **and** that count is at most
    **7** days — the comparison is inclusive, so exactly 7 escalates — the shipment's
    `method` is forced to `OVERNIGHT`, its `escalation_fee_cents` is set to **4500**, the
    order's `service_fee_quoted_cents` rises by 4500, `total_quoted_cents` is recomputed as
    `government_fee_quoted_cents` plus the new `service_fee_quoted_cents`, and
    `payment_status` is re-derived against the new total."
    PRD §3.11: "A `FAILED` attempt increments `attempt_count`; while the incremented value
    is strictly below **3** the shipment stays `OUT_FOR_DELIVERY`, and when the incremented
    value reaches exactly 3 the shipment moves `OUT_FOR_DELIVERY → HELD_FOR_PICKUP` and
    accepts no further delivery attempts."
    PRD §3.11: "A held shipment is closed out by recording a pickup, which moves it
    `HELD_FOR_PICKUP → PICKED_UP`, closes the open custody event and appends one with
    `holder_type` `APPLICANT` and `reason` `SHIPMENT_PICKED_UP`, and completes the order."

    Design: Corner/errors/corner_error_delivery_attempt_cap_and_escalation
    """
    scenario = build_scenario(
        "at_agency",
        visa_type="PASSPORT_RENEWAL",
        travel_date="2026-07-01",
        return_date="2026-07-20",
    )
    order_id = scenario["order_id"]

    set_clock("2026-06-24T09:00:00Z")
    agency_decision(order_id, "APPROVED")
    return_leg = list_legs(order_id)[-1]
    dispatch_leg(return_leg["id"])
    complete_leg(return_leg["id"], "DELIVERED")

    shipment = validate_success(
        api.create_shipment(order_id, {"method": "GROUND", "address_region_code": "CA"}, COURIER),
        expected_status=201,
    )
    assert shipment["method"] == "OVERNIGHT", (
        "exactly 7 calendar days of runway escalates a GROUND request"
    )
    assert shipment["escalation_fee_cents"] == 4500
    escalated_order = read_order(order_id)
    assert escalated_order["service_fee_quoted_cents"] == 15000, (
        f"10500 plus the 4500 surcharge, got {escalated_order['service_fee_quoted_cents']}"
    )
    assert escalated_order["total_quoted_cents"] == 31000

    for _ in range(3):
        validate_success(
            api.record_delivery_attempt(shipment["id"], {"outcome": "FAILED"}, COURIER)
        )
    held = read_shipment(shipment["id"])
    assert held["delivery_status"] == "HELD_FOR_PICKUP"
    assert held["attempt_count"] == 3

    refused = api.record_delivery_attempt(shipment["id"], {"outcome": "FAILED"}, COURIER)
    validate_error(refused, ApiErrorId.ERR_DELIVERY_ATTEMPT_CAP_EXCEEDED.value)

    validate_success(api.record_pickup(shipment["id"], COURIER))
    assert read_shipment(shipment["id"])["delivery_status"] == "PICKED_UP"
    completed = read_order(order_id)
    assert completed["workflow_status"] == "COMPLETED"
    assert completed["custody_holder"] == "APPLICANT"
