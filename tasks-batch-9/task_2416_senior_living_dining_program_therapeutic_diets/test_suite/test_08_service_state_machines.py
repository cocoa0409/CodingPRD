"""Service-side state machines: seating, tickets, releases, suspension and closure."""
import pytest

from test_helpers import (
    BILLING_SPECIALIST,
    DIETITIAN_ALT,
    DINING_MANAGER,
    ApiErrorId,
    approve_diet_order,
    create_community,
    create_diet_order,
    create_reconciliation,
    create_reservation,
    create_resident,
    issue_ticket,
    log_temperature,
    read_diet_order,
    read_reservation,
    read_resident,
    read_seat_availability,
    read_ticket,
    read_venue,
    record_observation,
    release_reservation,
    reviews_for,
    seat_reservation,
    set_clock,
    setup_dining_program,
    setup_published_menu_cycle,
    tickets_for_reservation,
    validate_error,
    validate_success,
    venue_version,
    void_ticket,
)


def _aldergate_lunch_service(clock="2026-08-10T11:55:00Z"):
    """A community whose published rotation covers 2026-08-10, with one verified resident."""
    program = setup_dining_program(
        clock=clock,
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Main Dining",
        seat_capacity=6,
        resident_name="Elsie Ravenna",
        baseline_weight_kg=60.0,
    )
    program["menu"] = setup_published_menu_cycle(
        program["community"]["id"],
        cycle_number=1,
        week_count=1,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[
            {
                "item_code": "REG-COD",
                "name": "Baked Cod",
                "day_index": 1,
                "meal_period": "LUNCH",
                "base_texture": "REGULAR",
            }
        ],
    )
    return program


def test_seating_stamps_the_clock_and_mints_the_resident_ticket(api):
    """`seated_at` is the logical clock at the moment of seating rather than the booked
    `seat_start_utc`, and the transition cascades exactly one `ISSUED` `RESIDENT` ticket priced at
    the lunch transfer rate.

    PRD: "On success, seating cascades a meal ticket into existence: a ticket with `ticket_type`
    `RESIDENT`, its `reservation_id` pointing at this row, and `venue_id`, `service_date` and
    `meal_period` copied from it, created in `ISSUED` status with `billed_amount_cents` priced by the
    ticket pricing rules of section 3.6."

    Design: Corner/state_machines/seat_transition_issues_resident_ticket_and_stamps_seated_at
    """
    program = _aldergate_lunch_service()
    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=1,
    )
    assert reservation["status"] == "RESERVED"
    assert reservation["seated_at"] is None

    seated = validate_success(api.seat_reservation(reservation["id"], DINING_MANAGER))

    assert seated["status"] == "SEATED"
    assert seated["seated_at"].startswith("2026-08-10T11:55:00")

    tickets = tickets_for_reservation(reservation["id"])
    assert len(tickets) == 1
    assert tickets[0]["ticket_type"] == "RESIDENT"
    assert tickets[0]["status"] == "ISSUED"
    assert tickets[0]["billed_amount_cents"] == 650
    assert tickets[0]["resident_id"] == program["resident"]["id"]
    assert tickets[0]["venue_id"] == program["venue"]["id"]
    assert tickets[0]["billed_reconciliation_id"] is None


def test_a_voided_ticket_can_no_longer_be_served(api):
    """`VOIDED` is terminal, so serving is refused by the state tier and the row keeps the audit
    pair: nothing billed, the original amount preserved as the voided amount.

    PRD: "Serving a ticket is a `DiningServicesManager` or `SatelliteKitchenLead` action taking no
    payload, accepted only from `ISSUED`, and it requires the venue's `temp_compliance_posture` not
    be `SUSPENDED`."

    Design: Corner/state_machines/voided_ticket_cannot_be_served
    """
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Main Dining",
        seat_capacity=6,
        resident_name="Franz Oberlin",
        baseline_weight_kg=77.0,
    )
    ticket = issue_ticket(
        program["venue"]["id"],
        "RESIDENT",
        "2026-08-10",
        "LUNCH",
        resident_id=program["resident"]["id"],
    )
    assert ticket["billed_amount_cents"] == 650

    voided = void_ticket(ticket["id"], void_reason="wrong resident")
    assert voided["status"] == "VOIDED"

    response = api.serve_meal_ticket(ticket["id"], DINING_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    final = read_ticket(ticket["id"])
    assert final["status"] == "VOIDED"
    assert final["billed_amount_cents"] == 0
    assert final["voided_amount_cents"] == 650


def test_releasing_an_already_released_reservation_is_refused(api):
    """The repeat of an applied transition falls to the state tier, and because the refusal never
    reaches the release logic the venue's `version` does not move again.

    PRD: "Releasing a reservation is a `DiningServicesManager` action with an optional `reason`,
    accepted from `RESERVED`, `WAITLISTED` or `SEATED`, and it moves the row to `RELEASED` and
    increments the venue's `version` by 1."

    Design: Corner/state_machines/second_release_of_released_reservation_returns_409
    """
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Main Dining",
        seat_capacity=6,
        resident_name="Greta Vance",
        baseline_weight_kg=65.0,
    )
    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=1,
    )
    released = release_reservation(reservation["id"], reason="resident declined")
    assert released["status"] == "RELEASED"
    assert venue_version(program["venue"]["id"]) == 3

    response = api.release_reservation(
        reservation["id"], {"reason": "duplicate cancellation"}, DINING_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    assert read_reservation(reservation["id"])["status"] == "RELEASED"
    assert venue_version(program["venue"]["id"]) == 3


def test_the_third_violation_waitlists_the_future_booking_and_frees_its_seats(api):
    """Suspension sweeps forward: the future `RESERVED` row moves to `WAITLISTED` with
    `suspension_hold` true, and its two seats leave the committed arithmetic for that meal period.

    PRD: "Every reservation of that venue whose `status` is `RESERVED` and whose `seat_start_utc` is
    at or after the logical clock — that is, every future booking — moves to `WAITLISTED` with
    `suspension_hold` set to true, and those rows leave committed-seat arithmetic."

    Design: Corner/state_machines/temperature_suspension_waitlists_future_reserved_reservation
    """
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["MEMORY_CARE"],
        venue_name="Aldergate Satellite",
        venue_kind="SATELLITE",
        seat_capacity=6,
        resident_name="Hugo Belanger",
        care_level="MEMORY_CARE",
        baseline_weight_kg=69.0,
    )
    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=2,
    )
    assert reservation["status"] == "RESERVED"
    log_temperature(program["venue"]["id"], "COLD_HOLDING", 50.0)
    second = log_temperature(program["venue"]["id"], "COLD_HOLDING", 50.0)
    assert second["violation_sequence_index"] == 2

    third = log_temperature(program["venue"]["id"], "COLD_HOLDING", 50.0)

    assert third["in_range"] is False
    assert third["violation_sequence_index"] == 3

    venue = read_venue(program["venue"]["id"])
    assert venue["temp_compliance_posture"] == "SUSPENDED"
    assert venue["consecutive_temp_violation_count"] == 3

    held = read_reservation(reservation["id"])
    assert held["status"] == "WAITLISTED"
    assert held["suspension_hold"] is True

    availability = read_seat_availability(program["venue"]["id"], "2026-08-11", "LUNCH")
    assert availability["committed_seats"] == 0
    assert availability["open_seats"] == 6


def test_finalizing_bills_the_served_ticket_and_links_it_to_the_period(api):
    """Closure is a two-sided move: the reconciliation freezes at its computed net of 689 with the
    acting specialist recorded, and the served ticket becomes `BILLED` carrying the period's id.

    PRD: "On success the reconciliation moves to `FINALIZED` with `finalized_by_user_id` set to the
    acting `X-User-ID`, and it cascades into the ticket ledger: every meal ticket at in-scope venues
    whose `status` is `SERVED` and whose `service_date` lies inside the closed period moves to
    `BILLED` with its `billed_reconciliation_id` set to this reconciliation's `id`."

    Design: Corner/state_machines/finalize_marks_served_tickets_billed_and_links_reconciliation
    """
    program = _aldergate_lunch_service()
    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=1,
    )
    seat_reservation(reservation["id"])
    ticket = tickets_for_reservation(reservation["id"])[0]
    served = validate_success(api.serve_meal_ticket(ticket["id"], DINING_MANAGER))
    assert served["status"] == "SERVED"

    reconciliation = create_reconciliation(
        program["community"]["id"], "2026-08-10", "2026-08-10"
    )
    assert reconciliation["ticket_ledger_total_cents"] == 650
    assert reconciliation["census_projection_total_cents"] == 650
    assert reconciliation["variance_cents"] == 0
    assert reconciliation["administrative_fee_cents"] == 39
    assert reconciliation["net_billable_total_cents"] == 689
    assert reconciliation["status"] == "RECONCILED"

    finalized = validate_success(
        api.finalize_reconciliation(reconciliation["id"], {}, BILLING_SPECIALIST)
    )

    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_by_user_id"] == BILLING_SPECIALIST["X-User-ID"]
    assert finalized["net_billable_total_cents"] == 689

    billed = read_ticket(ticket["id"])
    assert billed["status"] == "BILLED"
    assert billed["billed_reconciliation_id"] == reconciliation["id"]
    assert billed["billed_amount_cents"] == 650


def test_an_escalated_review_blocks_the_tray_without_touching_the_diet_order(api):
    """The escalation is a resident-level halt: `tray_card_state` becomes `BLOCKED` while the diet
    order keeps the axes the monitoring cascade left it in.

    PRD: "The resident's `tray_card_state` is set to `BLOCKED`, which makes every tray card resolve
    as `BLOCKED` and therefore blocks seating with `ERR_UNSAFE_TRAY_NO_SUBSTITUTION`. No diet order
    is mutated."

    Design: Corner/state_machines/plan_of_care_escalated_outcome_blocks_tray_without_touching_diet_order
    """
    set_clock("2026-08-02T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Jules Ferraro", baseline_weight_kg=78.0
    )
    order = create_diet_order(
        resident["id"],
        texture_level="MINCED_MOIST",
        liquid_consistency="MILDLY_THICK",
        therapeutic_codes=["LOW_SODIUM", "RENAL"],
    )
    approve_diet_order(order["id"])
    record_observation(resident["id"], "2026-08-02", "LUNCH", 80, weight_kg=80.0)
    set_clock("2026-08-20T08:00:00Z")
    record_observation(resident["id"], "2026-08-20", "LUNCH", 60, weight_kg=76.0)

    reviews = reviews_for(resident["id"], status="OPEN")
    assert len(reviews) == 1
    assert reviews[0]["risk_score_at_open"] == pytest.approx(75.00, abs=0.01)

    completed = validate_success(
        api.complete_plan_of_care_review(
            reviews[0]["id"],
            {"outcome": "ESCALATED", "note": "physician follow-up requested"},
            DIETITIAN_ALT,
        )
    )

    assert completed["status"] == "COMPLETED"
    assert completed["outcome"] == "ESCALATED"
    assert completed["completed_by_user_id"] == DIETITIAN_ALT["X-User-ID"]
    assert read_resident(resident["id"])["tray_card_state"] == "BLOCKED"

    unchanged = read_diet_order(order["id"])
    assert unchanged["review_status"] == "REREVIEW_REQUIRED"
    assert unchanged["clinical_status"] == "ACTIVE"
    assert unchanged["review_round"] == 0
