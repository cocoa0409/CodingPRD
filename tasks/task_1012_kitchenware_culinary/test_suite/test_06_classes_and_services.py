"""Cooking classes and service tickets: station half-open overlap, capacity
boundary, temporal-over-capacity precedence, cancel cascade, the class-open
precondition, service-bar buffer conflicts, and ticket completion."""
from test_helpers import (
    validate_success, validate_error,
    make_store, make_member, make_class, setup_open_class, book_registration,
    make_service_ticket, set_clock,
    create_cooking_class_payload, create_class_registration_payload,
    create_service_ticket_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOC = TEST_USERS["associate_headers"]


# ── resource_temporal_overlap / class_station_halfopen_overlap ──
def test_overlapping_class_on_same_station_rejected(api):
    """PRD §3.5: "if any other non-canceled class at the same store and station has a time
    interval that overlaps the proposed one, the request is rejected with
    `ERR_CLASS_STATION_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/class_station_halfopen_overlap
    """
    set_clock("2026-07-05T00:00:00Z")
    store = make_store(state_code="CA", name="Ovl Store")
    make_class(store["id"], station="DEMO_KITCHEN", start_at="2026-07-10T10:00:00Z",
               end_at="2026-07-10T12:00:00Z", capacity=8, title="Class 1")
    res = api.create_cooking_class(create_cooking_class_payload(
        store["id"], station="DEMO_KITCHEN", start_at="2026-07-10T11:00:00Z",
        end_at="2026-07-10T13:00:00Z", capacity=8, title="Class 2 overlap"), ASSOC)
    validate_error(res, "ERR_CLASS_STATION_CONFLICT")


def test_adjacent_class_starting_at_prior_end_accepted(api):
    """PRD §3.5: "Overlap is judged on half-open intervals, so a class that starts exactly
    when another ends does not conflict."

    Design: Difficulty/resource_temporal_overlap/class_station_halfopen_overlap
    """
    set_clock("2026-07-05T00:00:00Z")
    store = make_store(state_code="CA", name="Ovl Store")
    make_class(store["id"], station="DEMO_KITCHEN", start_at="2026-07-10T10:00:00Z",
               end_at="2026-07-10T12:00:00Z", capacity=8, title="Class 1")
    res = api.create_cooking_class(create_cooking_class_payload(
        store["id"], station="DEMO_KITCHEN", start_at="2026-07-10T12:00:00Z",
        end_at="2026-07-10T14:00:00Z", capacity=8, title="Class 3 adjacent"), ASSOC)
    cls = validate_success(res, 201)
    assert cls["status"] == "DRAFT"


# ── boundary_precision_check / class_capacity_full_boundary ───
def test_registration_at_capacity_rejected(api):
    """PRD §3.5: "the class's registered count must be strictly below its capacity, or the
    request is rejected with `ERR_CLASS_FULL`."

    Design: Difficulty/boundary_precision_check/class_capacity_full_boundary
    """
    store, cls = setup_open_class(state_code="NY", station="HEARTH_BAR",
                                  start_at="2026-07-20T18:00:00Z", end_at="2026-07-20T20:00:00Z",
                                  capacity=2, price_cents=7000)
    m1 = make_member(store["id"], full_name="Cap One")
    m2 = make_member(store["id"], full_name="Cap Two")
    m3 = make_member(store["id"], full_name="Cap Three")
    book_registration(cls["id"], m1["id"])
    book_registration(cls["id"], m2["id"])  # registered_count now == capacity 2
    res = api.create_class_registration(create_class_registration_payload(cls["id"], m3["id"]), ADMIN)
    validate_error(res, "ERR_CLASS_FULL")


def test_registration_just_below_capacity_accepted(api):
    """PRD §3.5: "On success the registration snapshots the class's per-seat price into
    `seat_price_cents`, enters `BOOKED` status, and the class's registered count is
    recomputed."

    Design: Difficulty/boundary_precision_check/class_capacity_full_boundary
    """
    store, cls = setup_open_class(state_code="NY", station="HEARTH_BAR",
                                  start_at="2026-07-20T18:00:00Z", end_at="2026-07-20T20:00:00Z",
                                  capacity=2, price_cents=7000)
    m1 = make_member(store["id"], full_name="Cap One")
    m2 = make_member(store["id"], full_name="Cap Two")
    book_registration(cls["id"], m1["id"])  # count 1, strictly below capacity 2
    reg2 = validate_success(
        api.create_class_registration(create_class_registration_payload(cls["id"], m2["id"]), ADMIN), 201)
    assert reg2["status"] == "BOOKED"
    cls_after = validate_success(api.get_cooking_class(cls["id"], ADMIN), 200)
    assert cls_after["registered_count"] == 2


# ── priority_pair_validation_conflict / registration_temporal_over_constraint ──
def _setup_full_and_past_start_class(api):
    set_clock("2026-07-05T00:00:00Z")
    store, cls = setup_open_class(state_code="NY", station="DEMO_KITCHEN",
                                  start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T12:00:00Z",
                                  capacity=1, price_cents=6000, clock=None)
    m1 = make_member(store["id"], full_name="Cook One")
    m2 = make_member(store["id"], full_name="Cook Two")
    book_registration(cls["id"], m1["id"])  # registered_count 1 == capacity
    set_clock("2026-07-11T00:00:00Z")       # now past start_at
    return cls, m2


def test_temporal_error_returned_when_full_and_past_start(api):
    """PRD §3.5: "the current logical clock must be strictly before the class's start time,
    or the request is rejected with `ERR_REGISTRATION_CLOSED`".

    Design: Difficulty/priority_pair_validation_conflict/registration_temporal_over_constraint
    """
    cls, m2 = _setup_full_and_past_start_class(api)
    res = api.create_class_registration(create_class_registration_payload(cls["id"], m2["id"]), ADMIN)
    validate_error(res, "ERR_REGISTRATION_CLOSED")


def test_temporal_check_wins_over_capacity(api):
    """PRD §2.1: "then time-window rules (HTTP 422); then capacity, overlap, and stock
    constraints (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/registration_temporal_over_constraint
    """
    cls, m2 = _setup_full_and_past_start_class(api)
    res = api.create_class_registration(create_class_registration_payload(cls["id"], m2["id"]), ADMIN)
    body = res.json()["data"]
    assert body["error_id"] == "ERR_REGISTRATION_CLOSED", (
        f"temporal check must win over capacity; got {body['error_id']}")
    assert res.status_code == 422


# ── Corner/state_machines/class_cancel_cascades_registrations ─
def test_class_cancel_cascades_booked_registration(api):
    """PRD §3.5: "Cancelling a class is permitted while it is `DRAFT` or `OPEN`: every
    still-booked registration on the class is moved to `CANCELED`, and the class itself
    becomes `CANCELED`."

    Design: Corner/state_machines/class_cancel_cascades_registrations
    """
    store, cls = setup_open_class(state_code="NY", station="HEARTH_BAR",
                                  start_at="2026-07-25T10:00:00Z", end_at="2026-07-25T12:00:00Z",
                                  capacity=6, price_cents=5000)
    member = make_member(store["id"])
    reg = book_registration(cls["id"], member["id"])
    canceled = validate_success(api.cancel_class(cls["id"], ASSOC), 200)
    assert canceled["status"] == "CANCELED"
    reg_after = validate_success(api.get_class_registration(reg["id"], ADMIN), 200)
    assert reg_after["status"] == "CANCELED"


# ── Corner/state_machines/registration_requires_class_open_rejected ──
def test_registration_into_draft_class_rejected(api):
    """PRD §3.5: "the class must be `OPEN`, or the request is rejected with
    `ERR_CLASS_NOT_OPEN`".

    Design: Corner/state_machines/registration_requires_class_open_rejected
    """
    set_clock("2026-07-05T00:00:00Z")
    store = make_store(state_code="NY")
    member = make_member(store["id"])
    cls = make_class(store["id"], station="DEMO_KITCHEN", start_at="2026-07-28T10:00:00Z",
                     end_at="2026-07-28T12:00:00Z", capacity=6, title="Sauces")  # left in DRAFT
    res = api.create_class_registration(create_class_registration_payload(cls["id"], member["id"]), ADMIN)
    validate_error(res, "ERR_CLASS_NOT_OPEN")


# ── resource_temporal_overlap / service_bar_buffer_conflict ───
def test_service_ticket_within_buffer_rejected(api):
    """PRD §3.6: "if any other non-canceled ticket at the same store and service type falls
    within the service buffer of the proposed interval, the request is rejected with
    `ERR_SERVICE_SLOT_CONFLICT`. The buffer is applied as a padding on both ends of the
    closed appointment interval, spanning 30 buffer minutes on each side."

    Design: Difficulty/resource_temporal_overlap/service_bar_buffer_conflict
    """
    set_clock("2026-07-05T00:00:00Z")
    store = make_store(state_code="CA", name="Bar Store")
    make_service_ticket(store["id"], service_type="KNIFE_SHARPENING",
                        start_at="2026-07-11T09:00:00Z", end_at="2026-07-11T09:30:00Z")
    res = api.create_service_ticket(create_service_ticket_payload(
        store["id"], service_type="KNIFE_SHARPENING",
        start_at="2026-07-11T09:45:00Z", end_at="2026-07-11T10:15:00Z"), ASSOC)
    validate_error(res, "ERR_SERVICE_SLOT_CONFLICT")


def test_service_ticket_exactly_buffer_apart_accepted(api):
    """PRD §3.6: "The buffer is applied as a padding on both ends of the closed appointment
    interval, spanning 30 buffer minutes on each side."

    Design: Difficulty/resource_temporal_overlap/service_bar_buffer_conflict
    """
    set_clock("2026-07-05T00:00:00Z")
    store = make_store(state_code="CA", name="Bar Store")
    make_service_ticket(store["id"], service_type="KNIFE_SHARPENING",
                        start_at="2026-07-11T09:00:00Z", end_at="2026-07-11T09:30:00Z")
    res = api.create_service_ticket(create_service_ticket_payload(
        store["id"], service_type="KNIFE_SHARPENING",
        start_at="2026-07-11T10:00:00Z", end_at="2026-07-11T10:30:00Z"), ASSOC)
    ticket = validate_success(res, 201)
    assert ticket["status"] == "SCHEDULED"


# ── Corner/state_machines/service_ticket_complete_lifecycle ───
def test_service_ticket_completes(api):
    """PRD §3.6: "A booked ticket begins `SCHEDULED`, and its lifecycle runs to `COMPLETED`
    or `CANCELED`. Completing a ticket moves it from `SCHEDULED` to `COMPLETED`."

    Design: Corner/state_machines/service_ticket_complete_lifecycle
    """
    set_clock("2026-07-05T00:00:00Z")
    store = make_store(state_code="CA", name="Svc Store")
    ticket = make_service_ticket(store["id"], service_type="KNIFE_SHARPENING",
                                 start_at="2026-07-12T09:00:00Z", end_at="2026-07-12T09:30:00Z")
    completed = validate_success(api.complete_service_ticket(ticket["id"], ASSOC), 200)
    assert completed["status"] == "COMPLETED"
