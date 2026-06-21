"""Transitive release cascades and compensating-action invariants: order-cancel
flowing down through assignments, reservations, and instruments; assignment
completion releasing equipment; and the conserved quantities (instrument
availability, crew open_assignment_count) restored after compensating actions.

Difficulty queue: transitive_cascade, compensating_invariant.
"""
from test_helpers import (
    fixtures as fx,
    make_coordinator_headers,
    make_field_tech_headers,
    validate_success,
)


# ════════════════════════════════════════════════════════════════════════
# Difficulty/transitive_cascade/order_cancel_cascade_depth3_assignment_reservation_instrument
# ════════════════════════════════════════════════════════════════════════
def test_order_cancel_cascades_depth3_to_instrument(api):
    """PRD §3.4: "every `FieldAssignment` for that order that is still `SCHEDULED`
    is driven to `CANCELLED`; each such cancelled assignment in turn releases each
    of its `HELD` instrument reservations to `RELEASED`; and each freed instrument
    flips from `RESERVED` back to `AVAILABLE`."

    Cancelling a FIELD_READY order with one SCHEDULED assignment holding one HELD
    reservation drives the full depth-3 chain: order CANCELLED, assignment CANCELLED,
    reservation RELEASED, instrument AVAILABLE.

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth3_assignment_reservation_instrument
    """
    ctx = fx.field_ready_with_reservation(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]

    validate_success(api.cancel_order(ctx["order_id"], make_coordinator_headers(cid)), 200)

    order = validate_success(api.get_survey_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    assert order["status"] == "CANCELLED"
    assignment = validate_success(api.get_field_assignment(ctx["assignment_id"], make_coordinator_headers(cid)), 200)
    assert assignment["status"] == "CANCELLED"
    reservation = validate_success(api.get_instrument_reservation(ctx["reservation_id"], make_coordinator_headers(cid)), 200)
    assert reservation["status"] == "RELEASED"
    instrument = validate_success(api.get_instrument(ctx["instrument_id"], make_coordinator_headers(cid)), 200)
    assert instrument["status"] == "AVAILABLE"


def test_order_cancel_decrements_open_assignment_count(api):
    """PRD §3.4: "As each assignment in the cascade is cancelled, the owning crew
    member's `open_assignment_count` is decremented by one, consistent with the
    direct-cancel behavior in §3.3."

    The TECH owning the cancelled assignment has its open_assignment_count returned
    to 0 after the order-cancel cascade.

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth3_assignment_reservation_instrument
    """
    ctx = fx.field_ready_with_reservation(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]

    before = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert before["open_assignment_count"] == 1

    validate_success(api.cancel_order(ctx["order_id"], make_coordinator_headers(cid)), 200)
    after = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert after["open_assignment_count"] == 0


# ════════════════════════════════════════════════════════════════════════
# Difficulty/transitive_cascade/assignment_complete_cascade_depth2_reservation_instrument
# ════════════════════════════════════════════════════════════════════════
def test_assignment_complete_releases_reservation_and_instrument(api):
    """PRD §3.3: "as side effects every `HELD` reservation for that assignment is
    set to `RELEASED`, each freed instrument flips from `RESERVED` back to
    `AVAILABLE`, and the crew member's `open_assignment_count` is decremented by
    one."

    Completing an IN_PROGRESS assignment that holds one reservation drives the
    depth-2 chain: assignment COMPLETED, reservation RELEASED, instrument AVAILABLE.

    Design: Difficulty/transitive_cascade/assignment_complete_cascade_depth2_reservation_instrument
    """
    ctx = fx.field_ready_with_reservation(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]

    validate_success(api.start_field_assignment(ctx["assignment_id"], make_field_tech_headers(tid)), 200)
    validate_success(api.complete_field_assignment(ctx["assignment_id"], make_field_tech_headers(tid)), 200)

    assignment = validate_success(api.get_field_assignment(ctx["assignment_id"], make_coordinator_headers(cid)), 200)
    assert assignment["status"] == "COMPLETED"
    reservation = validate_success(api.get_instrument_reservation(ctx["reservation_id"], make_coordinator_headers(cid)), 200)
    assert reservation["status"] == "RELEASED"
    instrument = validate_success(api.get_instrument(ctx["instrument_id"], make_coordinator_headers(cid)), 200)
    assert instrument["status"] == "AVAILABLE"


def test_assignment_complete_decrements_open_count(api):
    """PRD §3.3: "the crew member's `open_assignment_count` is decremented by one."

    Completing the assignment drops the TECH's open_assignment_count from 1 to 0.

    Design: Difficulty/transitive_cascade/assignment_complete_cascade_depth2_reservation_instrument
    """
    ctx = fx.field_ready_with_reservation(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]

    validate_success(api.start_field_assignment(ctx["assignment_id"], make_field_tech_headers(tid)), 200)
    before = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert before["open_assignment_count"] == 1

    validate_success(api.complete_field_assignment(ctx["assignment_id"], make_field_tech_headers(tid)), 200)
    after = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert after["open_assignment_count"] == 0


# ════════════════════════════════════════════════════════════════════════
# Difficulty/compensating_invariant/instrument_availability_conserved_on_reserve_then_cancel
# ════════════════════════════════════════════════════════════════════════
def test_instrument_availability_conserved_after_assignment_cancel(api):
    """PRD §3.3: "cancellation likewise releases every `HELD` reservation for the
    assignment, flips each freed instrument back to `AVAILABLE`, and decrements the
    crew member's `open_assignment_count` by one."

    An instrument that started AVAILABLE, was RESERVED by a reservation, and then had
    its assignment cancelled returns to AVAILABLE — net availability identical to
    before the reservation, and the reservation is RELEASED.

    Design: Difficulty/compensating_invariant/instrument_availability_conserved_on_reserve_then_cancel
    """
    ctx = fx.field_ready_with_reservation(
        survey_type="BOUNDARY", acreage=3, rush=False,
        instrument_overrides={"instrument_type": "LEVEL"})
    crew = ctx["crew"]
    cid = crew["coord"]["id"]

    reserved = validate_success(api.get_instrument(ctx["instrument_id"], make_coordinator_headers(cid)), 200)
    assert reserved["status"] == "RESERVED"

    validate_success(api.cancel_field_assignment(ctx["assignment_id"], make_coordinator_headers(cid)), 200)

    assignment = validate_success(api.get_field_assignment(ctx["assignment_id"], make_coordinator_headers(cid)), 200)
    assert assignment["status"] == "CANCELLED"
    reservation = validate_success(api.get_instrument_reservation(ctx["reservation_id"], make_coordinator_headers(cid)), 200)
    assert reservation["status"] == "RELEASED"
    instrument = validate_success(api.get_instrument(ctx["instrument_id"], make_coordinator_headers(cid)), 200)
    assert instrument["status"] == "AVAILABLE"


def test_reservation_flips_instrument_to_reserved(api):
    """PRD §3.3: "On success the reservation's `status` is `HELD` and the
    instrument's `status` flips from `AVAILABLE` to `RESERVED`."

    The forward half of the availability invariant: an instrument that starts
    AVAILABLE flips to RESERVED the moment one HELD reservation exists against it
    (the state the compensating cancel later undoes).

    Design: Difficulty/compensating_invariant/instrument_availability_conserved_on_reserve_then_cancel
    """
    ctx = fx.order_at_field_ready(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]
    from test_helpers import (
        create_field_assignment_payload, create_instrument_payload,
        create_instrument_reservation_payload,
    )
    instrument = validate_success(
        api.create_instrument(create_instrument_payload(instrument_type="LEVEL"),
                              make_coordinator_headers(cid)), 201)
    assert instrument["status"] == "AVAILABLE"
    assignment = validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(ctx["order_id"], tid,
                                            "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid)), 201)
    reservation = validate_success(
        api.create_instrument_reservation(
            create_instrument_reservation_payload(assignment["id"], instrument["id"]),
            make_coordinator_headers(cid)), 201)
    assert reservation["status"] == "HELD"
    reserved = validate_success(api.get_instrument(instrument["id"], make_coordinator_headers(cid)), 200)
    assert reserved["status"] == "RESERVED"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/compensating_invariant/crew_open_count_conserved_on_schedule_then_complete
# ════════════════════════════════════════════════════════════════════════
def test_crew_open_count_conserved_schedule_then_complete(api):
    """PRD §3.3: "the system computes `window_minutes` as the whole number of minutes
    in the window (see §3.7), and the crew member's `open_assignment_count` is
    incremented by one."
    PRD §3.3: "the crew member's `open_assignment_count` is decremented by one."

    A fresh TECH starts at open_assignment_count 0; scheduling raises it to 1;
    completing the assignment returns it to 0 — the conserved quantity restored.

    Design: Difficulty/compensating_invariant/crew_open_count_conserved_on_schedule_then_complete
    """
    ctx = fx.order_at_field_ready(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]

    fresh = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert fresh["open_assignment_count"] == 0

    from test_helpers import create_field_assignment_payload
    assignment = validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(ctx["order_id"], tid,
                                            "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid)), 201)
    scheduled = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert scheduled["open_assignment_count"] == 1

    validate_success(api.start_field_assignment(assignment["id"], make_field_tech_headers(tid)), 200)
    validate_success(api.complete_field_assignment(assignment["id"], make_field_tech_headers(tid)), 200)
    restored = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert restored["open_assignment_count"] == 0


def test_scheduling_increments_crew_open_count(api):
    """PRD §3.1: "the system maintains a computed `open_assignment_count` that starts
    at 0 and tracks how many of that member's `FieldAssignment` rows are currently in
    either `SCHEDULED` or `IN_PROGRESS` status."
    PRD §3.3: "the crew member's `open_assignment_count` is incremented by one."

    The increment half of the conserved-count invariant: a fresh TECH starts at 0,
    and scheduling one assignment (now SCHEDULED) raises the count to exactly 1.

    Design: Difficulty/compensating_invariant/crew_open_count_conserved_on_schedule_then_complete
    """
    ctx = fx.order_at_field_ready(survey_type="BOUNDARY", acreage=3, rush=False)
    crew = ctx["crew"]
    cid = crew["coord"]["id"]
    tid = crew["tech"]["id"]

    fresh = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert fresh["open_assignment_count"] == 0

    from test_helpers import create_field_assignment_payload
    validate_success(
        api.create_field_assignment(
            create_field_assignment_payload(ctx["order_id"], tid,
                                            "2026-07-01T09:00:00.000Z", "2026-07-01T13:00:00.000Z"),
            make_coordinator_headers(cid)), 201)
    scheduled = validate_success(api.get_crew_member(tid, make_coordinator_headers(cid)), 200)
    assert scheduled["open_assignment_count"] == 1
