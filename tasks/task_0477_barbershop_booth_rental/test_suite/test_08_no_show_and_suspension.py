"""No-shows, strikes, and customer suspension (PRD §3.8).

Covers the no-show grace boundary, the depth-3 cascade
(no-show -> strike -> suspension -> booking blocked), and the too-early guard.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_shop_with_barber_chair_shift,
    book_appointment,
    set_clock,
    create_appointment_payload,
    TEST_USERS,
)

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


def test_no_show_at_exact_grace_boundary_allowed(api):
    """PRD §3.8: "The no-show is permitted only once the logical clock has reached
    `start_utc` plus the shop's `late_grace_minutes`; at exactly that boundary
    instant the no-show is already allowed, while one moment earlier it is refused
    with `ERR_NO_SHOW_TOO_EARLY`."

    Design: Difficulty/boundary_precision_check/no_show_at_exact_grace_boundary_allowed
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "Boundary Shop", "tax_rate_pct": 0,
            "late_grace_minutes": 10, "no_show_fee_cents": 0, "no_show_strike_limit": 5,
        },
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    set_clock("2026-06-10T10:10:00Z")  # exactly start + grace
    res = api.no_show_appointment(appt["id"], RECEPTION)
    updated = validate_success(res, 200)
    assert updated["status"] == "NO_SHOW", updated
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    assert cust["no_show_strikes"] == 1, cust


def test_no_show_one_minute_before_grace_boundary_rejected(api):
    """PRD §3.8: "The no-show is permitted only once the logical clock has reached
    `start_utc` plus the shop's `late_grace_minutes`; at exactly that boundary
    instant the no-show is already allowed, while one moment earlier it is refused
    with `ERR_NO_SHOW_TOO_EARLY`."

    Design: Difficulty/boundary_precision_check/no_show_at_exact_grace_boundary_allowed
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "Boundary Shop", "tax_rate_pct": 0,
            "late_grace_minutes": 10, "no_show_fee_cents": 0, "no_show_strike_limit": 5,
        },
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    set_clock("2026-06-10T10:09:00Z")  # one minute before start + grace
    res = api.no_show_appointment(appt["id"], RECEPTION)
    validate_error(res, "ERR_NO_SHOW_TOO_EARLY")
    appt_after = validate_success(api.get_appointment(appt["id"], OWNER), 200)
    assert appt_after["status"] == "BOOKED", appt_after


def test_no_show_before_grace_rejected(api):
    """PRD §3.8: "one moment earlier it is refused with `ERR_NO_SHOW_TOO_EARLY`."

    Design: Corner/state_machines/no_show_before_grace_returns_too_early
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "S", "tax_rate_pct": 0, "late_grace_minutes": 10,
        },
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    set_clock("2026-06-10T10:09:00Z")  # one minute before start + grace
    res = api.no_show_appointment(appt["id"], RECEPTION)
    validate_error(res, "ERR_NO_SHOW_TOO_EARLY")
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    assert cust["no_show_strikes"] == 0, cust


def test_no_show_strike_suspension_blocks_booking_depth3(api):
    """PRD §3.8: "If that incremented strike count reaches or exceeds the shop's
    `no_show_strike_limit`, the customer's `status` moves to `SUSPENDED` — a
    consequence of the strike increment itself, which thereafter blocks the
    customer from booking or taking a queue ticket."
    PRD §3.4: "a suspended customer cannot book and is refused with
    `ERR_CUSTOMER_SUSPENDED`."

    Design: Difficulty/transitive_cascade/no_show_strike_suspension_blocks_booking_depth3
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "Strike Shop", "tax_rate_pct": 0,
            "no_show_strike_limit": 1, "late_grace_minutes": 10, "no_show_fee_cents": 0,
        },
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    set_clock("2026-06-10T10:30:00Z")
    validate_success(api.no_show_appointment(appt["id"], RECEPTION), 200)
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    assert cust["no_show_strikes"] == 1, cust
    assert cust["status"] == "SUSPENDED", cust
    # The suspended customer can no longer book.
    res = api.create_appointment(
        create_appointment_payload(
            ctx["shop"]["id"], ctx["customer"]["id"], ctx["barber"]["id"],
            ctx["chair"]["id"], ctx["service"]["id"], "2026-06-10T12:00:00Z"),
        RECEPTION,
    )
    validate_error(res, "ERR_CUSTOMER_SUSPENDED")


def test_suspension_boundary_below_limit_stays_active(api):
    """PRD §3.8: "The suspension boundary is inclusive at the limit."

    Design: Difficulty/transitive_cascade/no_show_strike_suspension_blocks_booking_depth3
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "Strike Shop", "tax_rate_pct": 0,
            "no_show_strike_limit": 2, "late_grace_minutes": 10, "no_show_fee_cents": 0,
        },
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    set_clock("2026-06-10T10:30:00Z")
    validate_success(api.no_show_appointment(appt["id"], RECEPTION), 200)
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    assert cust["no_show_strikes"] == 1, cust  # 1 < limit 2
    assert cust["status"] == "ACTIVE", cust
