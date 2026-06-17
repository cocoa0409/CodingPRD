"""Optimistic concurrency on charter writes and immediate read-after-write
consistency: a correct expected_charter_version succeeds and bumps the charter
version, a stale version on booking or slot-reservation creation is rejected, and
a freshly booked seat count is visible on the next read. Covers the corner-design
cross_cutting_complexity_layers (optimistic_concurrency) and consistency_model
instances rooted in §2.6, §2.8, and §3.4 of the PRD.
"""
from test_helpers import (
    validate_success,
    validate_error,
    make_customer_headers,
    create_booking_payload,
    create_slot_reservation_payload,
    create_marina,
    create_dock_slot,
    create_boat,
    create_customer,
    create_charter,
    create_booking,
    current_charter_version,
    get_charter,
    api_client,
)
from test_helpers.fixtures import FLEET_MANAGER, DOCK_MASTER


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_correct_version_succeeds_and_increments
# ===========================================================================

def test_booking_with_correct_charter_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "A request to create a booking must carry `expected_charter_version`
    matching the target charter's current `version`."
    PRD §2.6: "The charter's own `version` increments by one ... on each booking
    creation and slot reservation creation that targets it."

    Booking with expected_charter_version == current version (1) succeeds (201)
    and the charter's version advances to 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    marina = create_marina(name="Occ2 Marina")
    boat = create_boat(marina["id"], name="Occ2boat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"])
    version = current_charter_version(charter["id"])
    res = api.create_booking(
        create_booking_payload(charter["id"], customer["id"], version, party_size=2),
        make_customer_headers(customer["id"]),
    )
    booking = validate_success(res, expected_status=201)
    assert booking["status"] == "RESERVED", booking["status"]
    fresh = get_charter(charter["id"])
    assert fresh["version"] == 2, fresh["version"]


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_version_on_booking_create_rejected
# ===========================================================================

def test_booking_with_stale_charter_version_rejected(api):
    """PRD §2.8: "If another writer has advanced the charter's version since the
    client last read it ... admitting the new party could oversell the charter.
    The create is therefore rejected with `ERR_STALE_CHARTER_VERSION` (HTTP 412)."

    First booking advances the charter to version 2; a second create still carrying
    the original version 1 -> ERR_STALE_CHARTER_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_booking_create_rejected
    """
    marina = create_marina(name="Stale Marina")
    boat = create_boat(marina["id"], name="Staleboat", passenger_capacity=8)
    cust1 = create_customer()
    cust2 = create_customer()
    charter = create_charter(marina["id"], boat["id"], seats_total=8)
    stale_version = current_charter_version(charter["id"])
    create_booking(charter["id"], cust1["id"], party_size=1)  # advances version
    res = api.create_booking(
        create_booking_payload(charter["id"], cust2["id"], stale_version, party_size=1),
        make_customer_headers(cust2["id"]),
    )
    validate_error(res, "ERR_STALE_CHARTER_VERSION")


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_version_on_slot_reservation_rejected
# ===========================================================================

def test_slot_reservation_with_stale_charter_version_rejected(api):
    """PRD §2.8: "A request to create a slot reservation must likewise carry
    `expected_charter_version` matching the target charter's current `version`. A
    schedule or reschedule that already re-anchored the charter's window will have
    advanced its `version`, making a fresh reservation built on the old window
    stale; such a request is rejected with `ERR_STALE_CHARTER_VERSION` (HTTP 412)."

    A booking advances the charter version; a slot reservation carrying the stale
    original version -> ERR_STALE_CHARTER_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_slot_reservation_rejected
    """
    marina = create_marina(name="SlotStale Marina")
    slot = create_dock_slot(marina["id"], slot_label="Z1")
    boat = create_boat(marina["id"], name="SlotStaleboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"])
    stale_version = current_charter_version(charter["id"])
    create_booking(charter["id"], customer["id"], party_size=1)  # advances version
    res = api.create_slot_reservation(
        create_slot_reservation_payload(slot["id"], charter["id"], stale_version),
        DOCK_MASTER,
    )
    validate_error(res, "ERR_STALE_CHARTER_VERSION")


# ===========================================================================
# Corner: consistency_model / immediate_seat_count_visible_in_same_flow
# ===========================================================================

def test_seats_booked_visible_immediately_after_booking(api):
    """PRD §3.4: "On success, the charter's `seats_booked` is increased by
    `party_size`."

    After POST /bookings party 2, an immediate GET /charters/{id} reflects
    seats_booked == 2 with no lag.

    Design: Corner/consistency_model/immediate_seat_count_visible_in_same_flow
    """
    marina = create_marina(name="Imm Marina")
    boat = create_boat(marina["id"], name="Immboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"], seats_total=6)
    create_booking(charter["id"], customer["id"], party_size=2)
    fresh = validate_success(api.get_charter(charter["id"], FLEET_MANAGER),
                             expected_status=200)
    assert fresh["seats_booked"] == 2, fresh["seats_booked"]
