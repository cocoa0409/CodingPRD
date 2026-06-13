"""Component sourcing: interval validity, supplier-kind routing, hotel within-booking
overlap, and flight/activity cross-booking supplier-capacity buffer.

Covers difficulty rule resource_temporal_overlap (hotel half-open, flight buffer); plus
corner validation claims (invalid interval, supplier kind mismatch, overpayment).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, create_payment_payload,
)
from test_helpers.fixtures import (
    create_agency, create_customer, create_supplier, create_published_package,
    open_draft_booking, add_travelers, request_component,
    setup_reserved_booking, get_booking, _booking_version,
    AGENT, ADMIN,
)
from test_helpers import api_client


# ─── resource_temporal_overlap: HOTEL within-booking half-open ───────────
def test_hotel_overlap_within_booking_rejected(api):
    """PRD §3.5: "For a `HOTEL` component, the system looks at the other `HOTEL`
    components on the **same booking** booked against the **same supplier** that are
    still in `REQUESTED` or `CONFIRMED` status, and applies a half-open clash test: the
    new component clashes with an existing one when the new component's `starts_at` is
    before the existing one's `ends_at` and the existing one's `starts_at` is before the
    new component's `ends_at`."
    PRD §3.5: "Both comparisons are strict, so two stays that merely touch at a boundary
    — where one's `ends_at` equals the next one's `starts_at` — do not clash and are
    allowed; any genuine overlap is rejected with `ERR_COMPONENT_OVERLAP`."

    h1 [08:00,11:00), h2 [10:00,12:00) genuinely overlap => ERR_COMPONENT_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/rto_hotel_within_booking_half_open
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="HOTEL", name="Hotel1", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"],
                                 departure_date="2026-06-10T00:00:00.000Z")
    request_component(booking["id"], supplier["id"], kind="HOTEL",
                      starts_at="2026-06-01T08:00:00.000Z", ends_at="2026-06-01T11:00:00.000Z")
    res = api.create_component({
        "booking_id": booking["id"], "supplier_id": supplier["id"], "kind": "HOTEL",
        "starts_at": "2026-06-01T10:00:00.000Z", "ends_at": "2026-06-01T12:00:00.000Z",
        "is_mandatory": True}, AGENT)
    validate_error(res, "ERR_COMPONENT_OVERLAP")


def test_hotel_touching_boundary_allowed(api):
    """PRD §3.5: "Both comparisons are strict, so two stays that merely touch at a
    boundary — where one's `ends_at` equals the next one's `starts_at` — do not clash
    and are allowed".

    h1 [08:00,11:00) then h2 [11:00,13:00) touch at 11:00 => allowed (CREATED).

    Design: Difficulty/resource_temporal_overlap/rto_hotel_within_booking_half_open
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="HOTEL", name="Hotel1", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"],
                                 departure_date="2026-06-10T00:00:00.000Z")
    request_component(booking["id"], supplier["id"], kind="HOTEL",
                      starts_at="2026-06-01T08:00:00.000Z", ends_at="2026-06-01T11:00:00.000Z")
    h2 = validate_success(api.create_component({
        "booking_id": booking["id"], "supplier_id": supplier["id"], "kind": "HOTEL",
        "starts_at": "2026-06-01T11:00:00.000Z", "ends_at": "2026-06-01T13:00:00.000Z",
        "is_mandatory": True}, AGENT), 201)
    assert h2["status"] in ("REQUESTED", "CONFIRMED")


# ─── resource_temporal_overlap: FLIGHT cross-booking supplier buffer ─────
def test_flight_supplier_buffer_conflict_across_bookings(api):
    """PRD §3.5: "For a `FLIGHT` or `ACTIVITY` component, the resource being protected is
    the supplier's aggregate capacity across **all bookings**: the system looks at
    components of the **same supplier** and **same kind** on any booking that are in
    `REQUESTED` or `CONFIRMED` status (those that are `RELEASED` or `REJECTED` are
    excluded), and inflates each interval by a two-hour turnaround buffer of 7200 seconds
    before testing. The new component conflicts when its
    `starts_at` is before the existing component's `ends_at` plus the buffer and the
    existing component's `starts_at` is before the new component's `ends_at` plus the
    buffer; because of the buffer inflation, even adjacent or touching intervals conflict,
    and the request is rejected with `ERR_SUPPLIER_CAPACITY_CONFLICT`."

    B1 FLIGHT [08:00,11:00); B2 FLIGHT [11:05,13:00) on same supplier: 11:05 < 11:00+2h
    => ERR_SUPPLIER_CAPACITY_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/rto_flight_cross_booking_supplier_buffer
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", name="FlightCo", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    b1 = open_draft_booking(agency["id"], customer["id"], package["id"],
                            departure_date="2026-06-10T00:00:00.000Z")
    request_component(b1["id"], supplier["id"], kind="FLIGHT",
                      starts_at="2026-06-01T08:00:00.000Z", ends_at="2026-06-01T11:00:00.000Z")
    b2 = open_draft_booking(agency["id"], customer["id"], package["id"],
                            departure_date="2026-06-12T00:00:00.000Z")
    res = api.create_component({
        "booking_id": b2["id"], "supplier_id": supplier["id"], "kind": "FLIGHT",
        "starts_at": "2026-06-01T11:05:00.000Z", "ends_at": "2026-06-01T13:00:00.000Z",
        "is_mandatory": True}, AGENT)
    validate_error(res, "ERR_SUPPLIER_CAPACITY_CONFLICT")


def test_flight_outside_buffer_allowed_across_bookings(api):
    """PRD §3.5: "inflates each interval by a two-hour turnaround buffer of 7200 seconds
    before testing. The new component conflicts when its `starts_at` is before the existing
    component's `ends_at` plus the buffer".

    B1 FLIGHT [08:00,11:00); B2 FLIGHT [13:01,15:00): 13:01 is after 11:00+2h (13:00),
    so the buffered intervals do not collide => allowed.

    Design: Difficulty/resource_temporal_overlap/rto_flight_cross_booking_supplier_buffer
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", name="FlightCo", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    b1 = open_draft_booking(agency["id"], customer["id"], package["id"],
                            departure_date="2026-06-10T00:00:00.000Z")
    request_component(b1["id"], supplier["id"], kind="FLIGHT",
                      starts_at="2026-06-01T08:00:00.000Z", ends_at="2026-06-01T11:00:00.000Z")
    b2 = open_draft_booking(agency["id"], customer["id"], package["id"],
                            departure_date="2026-06-12T00:00:00.000Z")
    comp = validate_success(api.create_component({
        "booking_id": b2["id"], "supplier_id": supplier["id"], "kind": "FLIGHT",
        "starts_at": "2026-06-01T13:01:00.000Z", "ends_at": "2026-06-01T15:00:00.000Z",
        "is_mandatory": True}, AGENT), 201)
    assert comp["status"] in ("REQUESTED", "CONFIRMED")


# ─── Corner validation claims ────────────────────────────────────────────
def test_component_ends_before_starts_rejected(api):
    """PRD §3.5: "The interval must be well-formed — `ends_at` must be strictly after
    `starts_at` — or it is rejected with `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/component_ends_before_starts_invalid_interval
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="HOTEL", name="H", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    res = api.create_component({
        "booking_id": booking["id"], "supplier_id": supplier["id"], "kind": "HOTEL",
        "starts_at": "2026-06-02T00:00:00.000Z", "ends_at": "2026-06-01T00:00:00.000Z",
        "is_mandatory": True}, AGENT)
    validate_error(res, "ERR_INVALID_INTERVAL")


def test_component_supplier_kind_mismatch_rejected(api):
    """PRD §3.5: "The chosen supplier's `kind` must equal the component's `kind`, or the
    request is rejected with `ERR_INVALID_REFERENCE`."

    A FLIGHT component requested against a HOTEL supplier => ERR_INVALID_REFERENCE.

    Design: Corner/validations/component_supplier_kind_mismatch_invalid_reference
    """
    agency = create_agency(clock=None)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="HOTEL", name="H", auto_confirm=True)
    package = create_published_package(agency["id"], base_price_per_person_cents=100000)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"])
    res = api.create_component({
        "booking_id": booking["id"], "supplier_id": supplier["id"], "kind": "FLIGHT",
        "starts_at": "2026-06-01T08:00:00.000Z", "ends_at": "2026-06-01T10:00:00.000Z",
        "is_mandatory": True}, AGENT)
    validate_error(res, "ERR_INVALID_REFERENCE")


def test_overpayment_exceeds_milestone_due_rejected(api):
    """PRD §3.8: "A payment's `amount_cents` may not exceed the targeted milestone's
    remaining due — its `amount_due_cents` minus its current `settled_amount_cents` — or
    the payment is rejected as an overpayment with `ERR_OVERPAYMENT`."

    Paying 20001 against a DEPOSIT due 20000 (settled 0) => ERR_OVERPAYMENT; settled stays 0.

    Design: Corner/validations/overpayment_exceeds_milestone_due_rejected
    """
    ctx = setup_reserved_booking(
        num_travelers=1, clock="2026-01-01T00:00:00.000Z",
        pkg_overrides={"base_price_per_person_cents": 100000, "deposit_pct": 20})
    res = api.create_payment(
        create_payment_payload(ctx["booking_id"], ctx["deposit_ms_id"], 20001), AGENT)
    validate_error(res, "ERR_OVERPAYMENT")
    deposit = validate_success(api.get_milestone(ctx["deposit_ms_id"], AGENT), 200)
    assert deposit["settled_amount_cents"] == 0
