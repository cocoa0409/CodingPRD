"""Practice bookings: the RESERVED/CHECKED_IN/COMPLETED lifecycle, driver and
kart state gates, FLAT versus METERED billing with per-booking rounding, and
the half-open window overlap semantics."""
from test_helpers import (
    ApiErrorId,
    activate_driver,
    add_kart,
    assert_booking,
    book_practice,
    cancel_booking,
    complete_booking,
    create_booking_payload,
    get_booking,
    make_driver_headers,
    register_active_driver,
    register_driver,
    suspend_driver,
    validate_error,
    validate_success,
)

WINDOW_10_11 = ("2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z")
WINDOW_11_12 = ("2026-09-01T11:00:00Z", "2026-09-01T12:00:00Z")
WINDOW_1030_1130 = ("2026-09-01T10:30:00Z", "2026-09-01T11:30:00Z")


def _active_rental_driver(name="Driver"):
    return register_active_driver(full_name=name, license_type="RENTAL")


def test_checkout_from_reserved_rejected(api):
    """PRD 3.8: "The visit itself is two driver-scoped steps. Check-in moves `RESERVED
    → CHECKED_IN`; check-out moves `CHECKED_IN → COMPLETED` and settles the bill."
    PRD 3.8: "A created booking holds status `RESERVED`, with `minutes_used` and
    `fee_cents` null until the visit is complete."

    Design: Corner/state_machines/checkout_from_reserved_rejected
    """
    driver = _active_rental_driver()
    kart = add_kart()
    booking = book_practice(driver["id"], kart["id"], *WINDOW_10_11, pricing_mode="FLAT")

    response = api.check_out_booking(booking["id"], make_driver_headers(driver["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = get_booking(booking["id"])
    assert after["status"] == "RESERVED"
    assert after["minutes_used"] is None
    assert after["fee_cents"] is None


def test_suspended_driver_booking_rejected(api):
    """PRD 3.2: "Only `ACTIVE` drivers may enter events or book practice time — a
    `PENDING` or `SUSPENDED` driver attempting either is refused with
    `ERR_DRIVER_NOT_ACTIVE`."

    Design: Corner/validations/suspended_driver_booking_rejected
    """
    driver = register_driver(full_name="Suspended", license_type="RENTAL")
    activate_driver(driver["id"])
    suspend_driver(driver["id"])
    kart = add_kart()

    response = api.create_booking(
        create_booking_payload(driver["id"], kart["id"], *WINDOW_10_11),
        make_driver_headers(driver["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DRIVER_NOT_ACTIVE.value, 409)


def test_booking_kart_in_maintenance_rejected(api, league_admin_headers):
    """PRD 3.2: "A kart that is not `AVAILABLE` cannot be assigned to a new entry or
    booking (`ERR_KART_UNAVAILABLE`)."

    Design: Corner/validations/booking_kart_in_maintenance_rejected
    """
    driver = _active_rental_driver()
    kart = add_kart()
    validate_success(
        api.update_kart(kart["id"], {"status": "IN_MAINTENANCE"}, league_admin_headers),
        200,
    )

    response = api.create_booking(
        create_booking_payload(driver["id"], kart["id"], *WINDOW_10_11),
        make_driver_headers(driver["id"]),
    )
    validate_error(response, ApiErrorId.ERR_KART_UNAVAILABLE.value, 409)


def test_flat_booking_charges_fixed_fee(api):
    """PRD 3.8: "At check-out, `minutes_used` is set to the whole-minute length of the
    booked window, and `fee_cents` is computed by the variant the booking's
    `pricing_mode` selected: a `FLAT` booking is charged a fixed $40.00 (4000 cents)
    regardless of the minutes used, while a `METERED` booking is charged by multiplying
    the minutes used by the $1.50-per-minute rate (150 cents) and then applying 8.25%
    tax on top, with the result rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/booking_flat_vs_metered_fee
    """
    driver = _active_rental_driver()
    kart = add_kart()
    booking = book_practice(
        driver["id"], kart["id"], *WINDOW_10_11, pricing_mode="FLAT"
    )
    completed = complete_booking(booking["id"], driver["id"])
    assert_booking(completed)
    assert completed["status"] == "COMPLETED"
    assert completed["minutes_used"] == 60
    assert completed["fee_cents"] == 4000, "FLAT is the fixed 4000-cent fee"


def test_metered_booking_charges_time_proportional_fee(api):
    """PRD 3.8: "At check-out, `minutes_used` is set to the whole-minute length of the
    booked window, and `fee_cents` is computed by the variant the booking's
    `pricing_mode` selected: a `FLAT` booking is charged a fixed $40.00 (4000 cents)
    regardless of the minutes used, while a `METERED` booking is charged by multiplying
    the minutes used by the $1.50-per-minute rate (150 cents) and then applying 8.25%
    tax on top, with the result rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/booking_flat_vs_metered_fee
    """
    driver = _active_rental_driver()
    kart = add_kart()
    flat = complete_booking(
        book_practice(driver["id"], kart["id"], *WINDOW_10_11, pricing_mode="FLAT")["id"],
        driver["id"],
    )
    metered = complete_booking(
        book_practice(
            driver["id"],
            kart["id"],
            "2026-09-01T12:00:00Z",
            "2026-09-01T13:00:00Z",
            pricing_mode="METERED",
        )["id"],
        driver["id"],
    )

    assert metered["minutes_used"] == 60
    assert metered["fee_cents"] == 9743, (
        "round_half_up(60 * 150 * 1.0825) = round_half_up(9742.5) = 9743"
    )
    assert flat["minutes_used"] == metered["minutes_used"]
    assert flat["fee_cents"] != metered["fee_cents"], (
        "identical minutes_used, different fee_cents across the two variants"
    )


def test_metered_fee_rounds_half_up_per_booking(api):
    """PRD 3.8: "At check-out, `minutes_used` is set to the whole-minute length of the
    booked window, and `fee_cents` is computed by the variant the booking's
    `pricing_mode` selected: a `FLAT` booking is charged a fixed $40.00 (4000 cents)
    regardless of the minutes used, while a `METERED` booking is charged by multiplying
    the minutes used by the $1.50-per-minute rate (150 cents) and then applying 8.25%
    tax on top, with the result rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/metered_billing_per_booking_rounding_order
    """
    driver = _active_rental_driver()
    kart = add_kart()
    booking = book_practice(
        driver["id"],
        kart["id"],
        "2026-09-01T09:00:00Z",
        "2026-09-01T09:23:00Z",
        pricing_mode="METERED",
    )
    completed = complete_booking(booking["id"], driver["id"])
    assert completed["minutes_used"] == 23
    assert completed["fee_cents"] == 3735, (
        "round_half_up(23 * 150 * 1.0825) = round_half_up(3734.625) = 3735"
    )


def test_per_booking_rounding_not_aggregate_rounding(api, league_admin_headers):
    """PRD 3.8: "Tax and rounding are pinned to the per-booking level at check-out —
    never applied across a sum of bookings — so any per-driver or per-day total is the
    plain sum of the already-rounded per-booking `fee_cents` values."

    Design: Difficulty/combinatorial_formula/metered_billing_per_booking_rounding_order
    """
    driver = _active_rental_driver()
    kart = add_kart()
    first = complete_booking(
        book_practice(
            driver["id"],
            kart["id"],
            "2026-09-01T09:00:00Z",
            "2026-09-01T09:23:00Z",
            pricing_mode="METERED",
        )["id"],
        driver["id"],
    )
    second = complete_booking(
        book_practice(
            driver["id"],
            kart["id"],
            "2026-09-01T10:00:00Z",
            "2026-09-01T10:23:00Z",
            pricing_mode="METERED",
        )["id"],
        driver["id"],
    )

    assert first["fee_cents"] == 3735
    assert second["fee_cents"] == 3735
    assert first["fee_cents"] + second["fee_cents"] == 7470, (
        "per-booking rounding is pinned: the day total is 7470, not the 7469 that "
        "rounding the aggregate would give"
    )


def test_touching_windows_accepted(api):
    """PRD 2.10: "Practice bookings reserve half-open windows: a booking occupies its
    kart from `start_time` inclusive up to, but not including, `end_time`. Two windows
    that merely touch — one ending exactly when the other begins — do not intersect."

    Design: Difficulty/resource_temporal_overlap/kart_half_open_window_overlap
    """
    driver_a = _active_rental_driver("First")
    driver_b = _active_rental_driver("Second")
    kart = add_kart()
    book_practice(driver_a["id"], kart["id"], *WINDOW_10_11, pricing_mode="FLAT")

    response = api.create_booking(
        create_booking_payload(driver_b["id"], kart["id"], *WINDOW_11_12),
        make_driver_headers(driver_b["id"]),
    )
    booking = validate_success(response, 201)
    assert_booking(booking)
    assert booking["status"] == "RESERVED", (
        "the touching window [11:00,12:00) does not intersect [10:00,11:00)"
    )


def test_intersecting_window_rejected(api):
    """PRD 2.10: "A new booking for a kart is rejected with `ERR_BOOKING_OVERLAP` (409)
    when its window intersects any existing booking of the same kart in `RESERVED` or
    `CHECKED_IN` status; `COMPLETED` and `CANCELLED` bookings occupy nothing."

    Design: Difficulty/resource_temporal_overlap/kart_half_open_window_overlap
    """
    driver_a = _active_rental_driver("First")
    driver_b = _active_rental_driver("Second")
    kart = add_kart()
    book_practice(driver_a["id"], kart["id"], *WINDOW_10_11, pricing_mode="FLAT")

    response = api.create_booking(
        create_booking_payload(driver_b["id"], kart["id"], *WINDOW_1030_1130),
        make_driver_headers(driver_b["id"]),
    )
    validate_error(response, ApiErrorId.ERR_BOOKING_OVERLAP.value, 409)


def test_kart_overlap_shadows_track_capacity(api):
    """PRD 2.8: "When several checks could fail on the same request, the server
    evaluates them in a fixed order and answers with the first failing tier:"
    PRD 2.8: "8. **Booking overlap** — the requested window against the kart's
    committed schedule (`ERR_BOOKING_OVERLAP`). Applies only to practice-booking
    creation."
    PRD 2.8: "9. **Uniqueness and capacity** — one non-`WITHDRAWN` entry per driver per
    event (`ERR_DUPLICATE_ENTRY`), unique `round_number` per season
    (`ERR_DUPLICATE_ROUND`), unique class `code` per season (`ERR_DUPLICATE_CLASS_CODE`),
    one result row per entry per batch (`ERR_DUPLICATE_RESULT`), a kart not already
    assigned to a non-`WITHDRAWN` entry of the same event (`ERR_KART_UNAVAILABLE`), and
    the track capacity ceiling (`ERR_TRACK_CAPACITY_EXCEEDED`). Applies to the creation
    endpoints."

    Design: Difficulty/priority_pair_validation_conflict/booking_overlap_shadows_track_capacity
    """
    driver_a = _active_rental_driver("First")
    driver_b = _active_rental_driver("Second")
    driver_c = _active_rental_driver("Third")
    kart_1 = add_kart()
    kart_2 = add_kart()
    # Two intersecting bookings already occupy the window (one of them on the
    # kart the new request targets), so the kart-overlap tier and — depending on
    # the configured ceiling — the capacity tier both stand to fail; the
    # earlier tier must answer.
    book_practice(driver_a["id"], kart_1["id"], *WINDOW_10_11, pricing_mode="FLAT")
    book_practice(driver_b["id"], kart_2["id"], *WINDOW_10_11, pricing_mode="FLAT")

    response = api.create_booking(
        create_booking_payload(driver_c["id"], kart_1["id"], *WINDOW_1030_1130),
        make_driver_headers(driver_c["id"]),
    )
    validate_error(response, ApiErrorId.ERR_BOOKING_OVERLAP.value, 409)


def test_overlapping_booking_accepted_after_cancel_releases_kart(api):
    """PRD 3.8: "Cancellation releases the kart: the booking's owning driver, or a
    `LeagueAdmin`, moves `RESERVED → CANCELLED`, after which the window no longer
    counts against kart overlap or track capacity and subsequent overlapping bookings
    for the same kart are accepted."
    PRD 2.10: "A new booking for a kart is rejected with `ERR_BOOKING_OVERLAP` (409)
    when its window intersects any existing booking of the same kart in `RESERVED` or
    `CHECKED_IN` status; `COMPLETED` and `CANCELLED` bookings occupy nothing."

    Design: Difficulty/priority_pair_validation_conflict/booking_overlap_shadows_track_capacity
    """
    driver_a = _active_rental_driver("First")
    driver_b = _active_rental_driver("Second")
    kart = add_kart()
    blocking = book_practice(
        driver_a["id"], kart["id"], *WINDOW_10_11, pricing_mode="FLAT"
    )

    rejected = api.create_booking(
        create_booking_payload(driver_b["id"], kart["id"], *WINDOW_1030_1130),
        make_driver_headers(driver_b["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_BOOKING_OVERLAP.value, 409)

    cancel_booking(blocking["id"], driver_a["id"])

    accepted = api.create_booking(
        create_booking_payload(driver_b["id"], kart["id"], *WINDOW_1030_1130),
        make_driver_headers(driver_b["id"]),
    )
    booking = validate_success(accepted, 201)
    assert booking["status"] == "RESERVED", (
        "the cancelled booking occupies nothing, so the overlap rejection lifts"
    )
