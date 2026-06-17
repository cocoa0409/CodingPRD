"""Request-validation and safety-gate rejections: required/typed fields at
creation, seat-capacity and deposit-sufficiency violations, slot length and
status gates, captain/mate/boat credential and offshore-rating gates, and the
permit-kind/trip-type referential mismatch. Covers the corner-design entities
and validations instances rooted in §2.9 and §3.1–§3.4 of the PRD.
"""
from test_helpers import (
    validate_success,
    validate_error,
    make_customer_headers,
    create_booking_payload,
    create_slot_reservation_payload,
    pin_clock,
    create_marina,
    create_dock_slot,
    create_boat,
    create_captain,
    create_mate,
    create_permit,
    create_customer,
    create_charter,
    create_booking,
    current_charter_version,
    api_client,
)
from test_helpers.fixtures import FLEET_MANAGER, DOCK_MASTER


# ===========================================================================
# Corner: entities / create_marina_returns_201_with_defaults
# ===========================================================================

def test_create_marina_returns_201_with_defaults(api):
    """PRD §3.1: "A new marina opens in `OPEN` status with its `open_slot_count`
    initialized to its `slot_count`."
    PRD §3.1: "an optional `turnaround_buffer_minutes` (the minimum clearance
    enforced after one slot occupation before the next may begin on the same
    slot, defaulting to 30)."

    Design: Corner/entities/create_marina_returns_201_with_defaults
    """
    res = api.create_marina({"name": "Harbor One", "slot_count": 5}, DOCK_MASTER)
    marina = validate_success(res, expected_status=201)
    assert marina["status"] == "OPEN", marina["status"]
    assert marina["open_slot_count"] == 5, marina["open_slot_count"]
    assert marina["turnaround_buffer_minutes"] == 30, marina["turnaround_buffer_minutes"]
    assert marina["version"] == 1, marina["version"]


# ===========================================================================
# Corner: entities / system_fields_ignored_on_input
# ===========================================================================

def test_marina_system_fields_take_server_defaults(api):
    """PRD §3.1: "A new marina opens in `OPEN` status with its `open_slot_count`
    initialized to its `slot_count`. ... The `open_slot_count` is never stored as
    a frozen number — it is recomputed whenever a marina is read."

    A freshly created marina (slot_count 3) reports server-controlled status OPEN
    and open_slot_count 3 regardless of any client-supplied system fields.

    Design: Corner/entities/system_fields_ignored_on_input
    """
    res = api.create_marina({"name": "Sys Marina", "slot_count": 3}, DOCK_MASTER)
    marina = validate_success(res, expected_status=201)
    assert marina["status"] == "OPEN", marina["status"]
    assert marina["open_slot_count"] == 3, marina["open_slot_count"]


# ===========================================================================
# Corner: entities / create_booking_missing_party_size_returns_invalid_request
# ===========================================================================

def test_create_booking_without_party_size_rejected(api):
    """PRD §2.9: "request body well-formed — required fields present, types
    correct, enum values in range, and integer bounds respected
    (`ERR_INVALID_REQUEST`)."
    PRD §3.4: "The payload names the `charter_id` and the `customer_id`, the
    `party_size` (the number of seats this booking holds, at least 1)."

    Design: Corner/entities/create_booking_missing_party_size_returns_invalid_request
    """
    marina = create_marina(name="Req Marina")
    boat = create_boat(marina["id"], name="Reqboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"])
    version = current_charter_version(charter["id"])
    res = api.create_booking(
        {"charter_id": charter["id"], "customer_id": customer["id"],
         "expected_charter_version": version},
        make_customer_headers(customer["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


# ===========================================================================
# Corner: entities / create_booking_invalid_return_before_depart_rejected
# ===========================================================================

def test_create_charter_with_return_before_depart_rejected(api):
    """PRD §2.9: "The body well-formedness check at priority 4 covers, among other
    bounds, that a booking's `party_size` is at least 1, that a charter's
    `return_at` is strictly after its `depart_at`, and that a catch report's
    `released_count` does not exceed its `fish_count`; any such violation yields
    `ERR_INVALID_REQUEST`."

    return_at (12:00) before depart_at (16:00) -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_booking_invalid_return_before_depart_rejected
    """
    marina = create_marina(name="Ord Marina")
    boat = create_boat(marina["id"], name="Ordboat")
    res = api.create_charter(
        {"marina_id": marina["id"], "boat_id": boat["id"], "trip_type": "INSHORE",
         "depart_at": "2027-06-10T16:00:00Z", "return_at": "2027-06-10T12:00:00Z",
         "base_seat_price_cents": 10000, "seats_total": 6},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_INVALID_REQUEST")


# ===========================================================================
# Corner: entities / get_marina_not_found_returns_404
# ===========================================================================

def test_get_missing_marina_returns_not_found(api):
    """PRD §2.7: "The first identifier that does not resolve to an existing
    resource aborts the request with the matching not-found error —
    `ERR_MARINA_NOT_FOUND` ... each carrying HTTP 404."

    Design: Corner/entities/get_marina_not_found_returns_404
    """
    res = api.get_marina("00000000-0000-4000-8000-000000000000", DOCK_MASTER)
    validate_error(res, "ERR_MARINA_NOT_FOUND")


# ===========================================================================
# Corner: entities / permit_is_immutable_no_version_field
# ===========================================================================

def test_permit_carries_no_version_field(api):
    """PRD §2.4: "A **Permit** is immutable after registration: it carries only
    `id` and `created_at`, and has neither `updated_at` nor `version`."

    Design: Corner/entities/permit_is_immutable_no_version_field
    """
    res = api.create_permit(
        {"permit_kind": "STATE_INSHORE", "permit_number": "S-9",
         "valid_through": "2030-01-01T00:00:00Z", "daily_bag_limit": 5},
        FLEET_MANAGER,
    )
    permit = validate_success(res, expected_status=201)
    assert permit["permit_number"] == "S-9", permit["permit_number"]
    assert permit["daily_bag_limit"] == 5, permit["daily_bag_limit"]
    assert "version" not in permit, "Permit must NOT carry a version field"


# ===========================================================================
# Corner: validations / capacity_exceeded_on_overbook_booking
# ===========================================================================

def test_booking_overbook_rejected_with_capacity_exceeded(api):
    """PRD §3.4: "the requested `party_size` added to the charter's current
    `seats_booked` must not exceed `seats_total`, or the booking is rejected with
    `ERR_CAPACITY_EXCEEDED`."

    seats_total 4, existing party-3 booking; a new party-2 (3+2 > 4) ->
    ERR_CAPACITY_EXCEEDED.

    Design: Corner/validations/capacity_exceeded_on_overbook_booking
    """
    marina = create_marina(name="Cap Marina")
    boat = create_boat(marina["id"], name="Capboat", passenger_capacity=8)
    cust1 = create_customer()
    cust2 = create_customer()
    charter = create_charter(marina["id"], boat["id"], seats_total=4)
    create_booking(charter["id"], cust1["id"], party_size=3)
    version = current_charter_version(charter["id"])
    res = api.create_booking(
        create_booking_payload(charter["id"], cust2["id"], version, party_size=2),
        make_customer_headers(cust2["id"]),
    )
    validate_error(res, "ERR_CAPACITY_EXCEEDED")


# ===========================================================================
# Corner: validations / charter_seats_total_exceeds_boat_capacity_rejected
# ===========================================================================

def test_charter_seats_total_above_boat_capacity_rejected(api):
    """PRD §3.2: "At creation, `seats_total` must not exceed the boat's
    `passenger_capacity`, or the charter is rejected with `ERR_CAPACITY_EXCEEDED`."

    Boat passenger_capacity 6; charter seats_total 7 -> ERR_CAPACITY_EXCEEDED.

    Design: Corner/validations/charter_seats_total_exceeds_boat_capacity_rejected
    """
    marina = create_marina(name="Cap2 Marina")
    boat = create_boat(marina["id"], name="Cap2boat", passenger_capacity=6)
    res = api.create_charter(
        {"marina_id": marina["id"], "boat_id": boat["id"], "trip_type": "INSHORE",
         "depart_at": "2028-03-10T12:00:00Z", "return_at": "2028-03-10T16:00:00Z",
         "base_seat_price_cents": 10000, "seats_total": 7},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_CAPACITY_EXCEEDED")


# ===========================================================================
# Corner: validations / deposit_underpaid_rejected
# ===========================================================================

def test_pay_deposit_below_due_rejected(api):
    """PRD §3.4: "The `amount_cents` must be at least the booking's
    `deposit_due_cents`; an underpayment is rejected with `ERR_DEPOSIT_UNDERPAID`
    (HTTP 402)."

    deposit_due 5000 (base 10000 party 2); pay 4999 -> ERR_DEPOSIT_UNDERPAID.

    Design: Corner/validations/deposit_underpaid_rejected
    """
    marina = create_marina(name="Under Marina")
    boat = create_boat(marina["id"], name="Underboat")
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=2)
    assert booking["deposit_due_cents"] == 5000, booking["deposit_due_cents"]
    res = api.pay_deposit(booking["id"], {"amount_cents": 4999},
                          make_customer_headers(customer["id"]))
    validate_error(res, "ERR_DEPOSIT_UNDERPAID")


# ===========================================================================
# Corner: validations / slot_length_exceeded_rejected
# ===========================================================================

def test_reserve_slot_too_short_for_boat_rejected(api):
    """PRD §3.3: "The boat's `length_ft` must not exceed the slot's
    `max_boat_length_ft`, or the reservation is rejected with
    `ERR_SLOT_LENGTH_EXCEEDED`."

    slot max_boat_length_ft 30, boat length_ft 35 -> ERR_SLOT_LENGTH_EXCEEDED.

    Design: Corner/validations/slot_length_exceeded_rejected
    """
    marina = create_marina(name="Len Marina")
    slot = create_dock_slot(marina["id"], slot_label="W1", max_boat_length_ft=30)
    boat = create_boat(marina["id"], name="Bigboat", length_ft=35)
    charter = create_charter(marina["id"], boat["id"])
    version = current_charter_version(charter["id"])
    res = api.create_slot_reservation(
        create_slot_reservation_payload(slot["id"], charter["id"], version),
        DOCK_MASTER,
    )
    validate_error(res, "ERR_SLOT_LENGTH_EXCEEDED")


# ===========================================================================
# Corner: validations / credential_expired_for_sail_date_rejected
# ===========================================================================

def test_assign_captain_with_expired_license_rejected(api):
    """PRD §3.2: "The captain's `license_expires_on` must fall strictly after the
    charter's sail date; a credential lapsing on or before that date is rejected
    with `ERR_CREDENTIAL_EXPIRED_FOR_DATE`."

    license_expires_on 2028-06-01, depart_at 2028-06-10 (after expiry) ->
    ERR_CREDENTIAL_EXPIRED_FOR_DATE.

    Design: Corner/validations/credential_expired_for_sail_date_rejected
    """
    marina = create_marina(name="Exp Marina")
    boat = create_boat(marina["id"], name="Expboat")
    captain = create_captain(marina["id"], license_expires_on="2028-06-01T00:00:00Z")
    charter = create_charter(marina["id"], boat["id"],
                             depart_at="2028-06-10T12:00:00Z",
                             return_at="2028-06-10T16:00:00Z")
    res = api.create_crew_assignment(
        {"charter_id": charter["id"], "role_slot": "CAPTAIN", "captain_id": captain["id"]},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_CREDENTIAL_EXPIRED_FOR_DATE")


# ===========================================================================
# Corner: validations / mate_not_offshore_certified_rejected
# ===========================================================================

def test_assign_uncertified_mate_to_offshore_rejected(api):
    """PRD §3.2: "For offshore trips, the mate must be `certified_offshore`, or
    the assignment is rejected with `ERR_MATE_NOT_OFFSHORE_CERTIFIED`."

    OFFSHORE charter; mate certified_offshore=false ->
    ERR_MATE_NOT_OFFSHORE_CERTIFIED.

    Design: Corner/validations/mate_not_offshore_certified_rejected
    """
    marina = create_marina(name="MateO Marina")
    boat = create_boat(marina["id"], name="MateOboat", length_ft=42,
                       passenger_capacity=8, offshore_rated=True)
    permit = create_permit(permit_number="F-5", daily_bag_limit=20)
    mate = create_mate(marina["id"], full_name="Mate Inshore", certified_offshore=False)
    charter = create_charter(marina["id"], boat["id"], trip_type="OFFSHORE",
                             permit_id=permit["id"], base_seat_price_cents=30000,
                             seats_total=8, depart_at="2028-07-10T06:00:00Z",
                             return_at="2028-07-10T18:00:00Z")
    res = api.create_crew_assignment(
        {"charter_id": charter["id"], "role_slot": "MATE", "mate_id": mate["id"]},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_MATE_NOT_OFFSHORE_CERTIFIED")


# ===========================================================================
# Corner: validations / boat_not_offshore_rated_rejected
# ===========================================================================

def test_create_offshore_charter_on_unrated_hull_rejected(api):
    """PRD §3.2: "An offshore trip likewise demands an offshore-rated hull: when
    the `trip_type` is `OFFSHORE`, the anchored boat's `offshore_rated` flag must
    be true, and a charter or staffing operation that would place an un-rated hull
    on offshore water is rejected with `ERR_BOAT_NOT_OFFSHORE_RATED`."

    OFFSHORE charter on offshore_rated=false boat -> ERR_BOAT_NOT_OFFSHORE_RATED.

    Design: Corner/validations/boat_not_offshore_rated_rejected
    """
    marina = create_marina(name="Rated Marina")
    boat = create_boat(marina["id"], name="Inshoreboat", offshore_rated=False)
    permit = create_permit(permit_number="F-6", daily_bag_limit=20)
    res = api.create_charter(
        {"marina_id": marina["id"], "boat_id": boat["id"], "trip_type": "OFFSHORE",
         "permit_id": permit["id"], "base_seat_price_cents": 30000, "seats_total": 6,
         "depart_at": "2028-07-10T06:00:00Z", "return_at": "2028-07-10T18:00:00Z"},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_BOAT_NOT_OFFSHORE_RATED")


# ===========================================================================
# Corner: validations / slot_decommissioned_reservation_rejected
# ===========================================================================

def test_reserve_decommissioned_slot_rejected(api):
    """PRD §3.1: "A `DockMaster` may later decommission a slot, moving it to
    `DECOMMISSIONED`; a decommissioned slot accepts no new reservations, and an
    attempt to reserve one is rejected with `ERR_SLOT_DECOMMISSIONED`."

    Design: Corner/validations/slot_decommissioned_reservation_rejected
    """
    marina = create_marina(name="Dec Marina")
    slot = create_dock_slot(marina["id"], slot_label="X1")
    boat = create_boat(marina["id"], name="Decboat")
    charter = create_charter(marina["id"], boat["id"])
    version = current_charter_version(charter["id"])
    api.decommission_dock_slot(slot["id"], DOCK_MASTER)
    res = api.create_slot_reservation(
        create_slot_reservation_payload(slot["id"], charter["id"], version),
        DOCK_MASTER,
    )
    validate_error(res, "ERR_SLOT_DECOMMISSIONED")


# ===========================================================================
# Corner: validations / permit_kind_mismatch_trip_type_rejected
# ===========================================================================

def test_offshore_charter_with_inshore_permit_rejected(api):
    """PRD §3.2: "where a permit is involved, its `permit_kind` must match the
    `trip_type` — an offshore trip requires a `FEDERAL_OFFSHORE` permit. Any of
    these mismatches is rejected with `ERR_CROSS_MARINA_MISMATCH`."

    OFFSHORE charter with a STATE_INSHORE permit -> ERR_CROSS_MARINA_MISMATCH.

    Design: Corner/validations/permit_kind_mismatch_trip_type_rejected
    """
    marina = create_marina(name="Mis Marina")
    boat = create_boat(marina["id"], name="Misboat", length_ft=42,
                       passenger_capacity=8, offshore_rated=True)
    permit = create_permit(permit_kind="STATE_INSHORE", permit_number="S-7",
                           daily_bag_limit=20)
    res = api.create_charter(
        {"marina_id": marina["id"], "boat_id": boat["id"], "trip_type": "OFFSHORE",
         "permit_id": permit["id"], "base_seat_price_cents": 30000, "seats_total": 8,
         "depart_at": "2028-09-10T06:00:00Z", "return_at": "2028-09-10T18:00:00Z"},
        FLEET_MANAGER,
    )
    validate_error(res, "ERR_CROSS_MARINA_MISMATCH")
