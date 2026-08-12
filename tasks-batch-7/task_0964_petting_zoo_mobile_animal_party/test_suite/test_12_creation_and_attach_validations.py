"""Creation-time and attachment-time validation rejections: temporal lead
rules, venue capacity and existence, duplicate roster/add-on attachments,
overpayment, waiver overflow, and the pony-ride venue gate
(PRD §2.7, §3.4, §3.6).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Corner/validations/booking_create_event_too_soon_rejected
# =====================================================================
def test_booking_create_event_too_soon_rejected(api):
    """PRD §3.4: "Three checks guard creation: the start must fall strictly
    after now (`ERR_EVENT_IN_PAST`), at least 48 hours after now
    (`ERR_EVENT_TOO_SOON`), and the guest count must not exceed the venue's
    `max_guest_capacity` (`ERR_VENUE_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/booking_create_event_too_soon_rejected
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"])
    resp = api.create_booking(
        {"venue_id": venue["id"], "start_time": "2026-05-11T12:00:00Z",
         "end_time": "2026-05-11T14:00:00Z", "guest_count": 10,
         "child_guest_count": 0, "booking_type": "PRIVATE_PARTY",
         "planned_handwash_stations": 1},
        make_customer_headers(customer["id"]))
    # 36h after the logical clock: past the 0h rule but inside the 48h lead.
    validate_error(resp, ApiErrorId.ERR_EVENT_TOO_SOON)


# =====================================================================
# Corner/validations/booking_create_event_in_past_rejected
# =====================================================================
def test_booking_create_event_in_past_rejected(api):
    """PRD §3.4: "Three checks guard creation: the start must fall strictly
    after now (`ERR_EVENT_IN_PAST`), at least 48 hours after now
    (`ERR_EVENT_TOO_SOON`), and the guest count must not exceed the venue's
    `max_guest_capacity` (`ERR_VENUE_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/booking_create_event_in_past_rejected
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"])
    resp = api.create_booking(
        {"venue_id": venue["id"], "start_time": "2026-05-09T12:00:00Z",
         "end_time": "2026-05-09T14:00:00Z", "guest_count": 10,
         "child_guest_count": 0, "booking_type": "PRIVATE_PARTY",
         "planned_handwash_stations": 1},
        make_customer_headers(customer["id"]))
    # The start falls before the logical clock.
    validate_error(resp, ApiErrorId.ERR_EVENT_IN_PAST)


# =====================================================================
# Corner/validations/booking_create_over_capacity_rejected
# =====================================================================
def test_booking_create_over_capacity_rejected(api):
    """PRD §3.4: "Three checks guard creation: the start must fall strictly
    after now (`ERR_EVENT_IN_PAST`), at least 48 hours after now
    (`ERR_EVENT_TOO_SOON`), and the guest count must not exceed the venue's
    `max_guest_capacity` (`ERR_VENUE_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/booking_create_over_capacity_rejected
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"], name="Tiny Yard",
                            address="2 Small St", max_guest_capacity=10)
    resp = api.create_booking(
        {"venue_id": venue["id"], "start_time": "2026-06-17T14:00:00Z",
         "end_time": "2026-06-17T16:00:00Z", "guest_count": 20,
         "child_guest_count": 0, "booking_type": "PRIVATE_PARTY",
         "planned_handwash_stations": 1},
        make_customer_headers(customer["id"]))
    # 20 guests against a max_guest_capacity of 10.
    validate_error(resp, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED)


# =====================================================================
# Corner/validations/booking_create_with_unknown_venue_not_found
# =====================================================================
def test_booking_create_with_unknown_venue_not_found(api):
    """PRD §2.7: "Each resource type has its own not-found error:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`,
    `ERR_HANDLER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_ADDON_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, and
    `ERR_ASSIGNMENT_NOT_FOUND`, all HTTP 404."

    Design: Corner/validations/booking_create_with_unknown_venue_not_found
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    resp = api.create_booking(
        {"venue_id": NON_EXISTENT_UUID, "start_time": "2026-06-17T14:00:00Z",
         "end_time": "2026-06-17T16:00:00Z", "guest_count": 10,
         "child_guest_count": 0, "booking_type": "PRIVATE_PARTY",
         "planned_handwash_stations": 1},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_VENUE_NOT_FOUND, expected_status=404)


# =====================================================================
# Corner/validations/duplicate_animal_attach_rejected
# =====================================================================
def test_duplicate_animal_attach_rejected(api):
    """PRD §3.4: "attaching an animal already on the booking in `PROPOSED` or
    `CONFIRMED` status is rejected with `ERR_ANIMAL_ALREADY_ON_BOOKING`
    (HTTP 409)."

    Design: Corner/validations/duplicate_animal_attach_rejected
    """
    ctx = fx.setup_draft_booking(guest_count=10)
    goat = fx.create_certified_animal()
    fx.attach_animal(ctx["booking"]["id"], goat["id"])  # first: PROPOSED
    resp = api.attach_booking_animal(
        ctx["booking"]["id"],
        {"animal_id": goat["id"], "role": "PETTING_ZOO"},
        fx.COORD)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_ALREADY_ON_BOOKING)


# =====================================================================
# Corner/validations/duplicate_addon_request_rejected
# =====================================================================
def test_duplicate_addon_request_rejected(api):
    """PRD §3.4: "A booking may not hold two requests of the same `addon_type`
    in `REQUESTED` or `APPROVED` status — a duplicate is rejected with
    `ERR_ADDON_ALREADY_REQUESTED` (HTTP 409)."

    Design: Corner/validations/duplicate_addon_request_rejected
    """
    ctx = fx.setup_draft_booking(guest_count=10)
    booking_id = ctx["booking"]["id"]
    fx.create_addon(booking_id, ctx["customer"]["id"], "REPTILE_SHOW", 30,
                    ctx["booking"]["version"])
    # Re-read so the second attach carries a fresh OCC version and the
    # stale-version check cannot mask the duplicate check.
    fresh_version = fx.get_booking(booking_id)["version"]
    resp = api.create_addon(
        booking_id,
        {"addon_type": "REPTILE_SHOW", "duration_minutes": 45,
         "expected_booking_version": fresh_version},
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ADDON_ALREADY_REQUESTED)


# =====================================================================
# Corner/validations/overpayment_rejected
# =====================================================================
def test_overpayment_rejected(api):
    """PRD §3.6: "Payments are accepted only while the booking is in `QUOTED`,
    `CONFIRMED`, or `WEATHER_HOLD`, and a payment that would push
    `total_paid_cents` above the current `quoted_total_cents` is rejected —
    both failures surface as `ERR_OVERPAYMENT`."
    PRD §3.6: "Each accepted payment appends a `PAYMENT` ledger entry,
    recomputes `total_paid_cents`, and advances `payment_status`: from
    `UNPAID` to `DEPOSIT_PAID` on the first payment, and on to `PAID_IN_FULL`
    once the paid total reaches the quoted total."

    Design: Corner/validations/overpayment_rejected
    """
    ctx = fx.setup_quoted_goat_booking()  # quoted 16240
    booking_id = ctx["booking"]["id"]
    fx.pay(booking_id, ctx["customer"]["id"], 16240)
    booking = fx.get_booking(booking_id)
    assert booking["payment_status"] == "PAID_IN_FULL"
    assert booking["total_paid_cents"] == 16240

    resp = api.create_payment(
        booking_id, {"amount_cents": 1, "method": "CARD"},
        make_customer_headers(ctx["customer"]["id"]))
    # 16240 + 1 would exceed the quoted 16240.
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)


# =====================================================================
# Corner/validations/waiver_signature_overflow_rejected
# =====================================================================
def test_waiver_signature_overflow_rejected(api):
    """PRD §3.6: "A `Customer` records guardian signatures in batches by
    supplying a `count`; the batch may not push `signed_count` beyond
    `required_signatures` — an overflowing batch is rejected with
    `ERR_WAIVER_SIGNATURE_OVERFLOW` — and after each accepted batch the status
    is re-derived."

    Design: Corner/validations/waiver_signature_overflow_rejected
    """
    ctx = fx.setup_draft_booking(guest_count=10, child_guest_count=2)
    booking_id = ctx["booking"]["id"]
    resp = api.sign_waiver(booking_id, 3,
                           make_customer_headers(ctx["customer"]["id"]))
    # 0 + 3 > 2 required: rejected, not clamped.
    validate_error(resp, ApiErrorId.ERR_WAIVER_SIGNATURE_OVERFLOW)

    waiver = fx.get_waiver(booking_id, ctx["customer"]["id"])
    assert waiver["signed_count"] == 0
    assert waiver["status"] == "PENDING", waiver["status"]


# =====================================================================
# Corner/validations/pony_ride_indoor_venue_rejected
# =====================================================================
def test_pony_ride_indoor_venue_rejected(api):
    """PRD §3.4: "a `PONY_RIDE` may be approved only when the venue's
    `venue_type` is `OUTDOOR` or `MIXED` (`ERR_ADDON_VENUE_INCOMPATIBLE`
    otherwise — ponies do not perform indoors)."

    Design: Corner/validations/pony_ride_indoor_venue_rejected
    """
    ctx = fx.setup_draft_booking(
        guest_count=10,
        venue_overrides={"name": "Old Barn Hall", "address": "3 Barn Rd",
                         "venue_type": "INDOOR", "surface_type": "INDOOR_FLOOR"},
    )
    addon = fx.create_addon(ctx["booking"]["id"], ctx["customer"]["id"],
                            "PONY_RIDE", 30, ctx["booking"]["version"])
    resp = api.decide_addon(ctx["booking"]["id"], addon["id"],
                            {"decision": "APPROVED"}, fx.COORD)
    validate_error(resp, ApiErrorId.ERR_ADDON_VENUE_INCOMPATIBLE)
