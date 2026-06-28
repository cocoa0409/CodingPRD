"""Barbers, licenses, and the license lifecycle (PRD §3.2).

Covers the ACTIVE<->SUSPENDED cycle, the REVOKED terminal lockdown, the expiry
guard, comp-model defaults, and cross-entity gating of check-in / serve.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    assert_barber,
    setup_shop_with_barber_chair_shift,
    setup_shop_with_active_barber,
    set_clock,
    create_shop,
    create_chair,
    create_service,
    create_shift,
    shop_version,
    enqueue,
    book_appointment,
    create_barber_payload,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


def test_license_active_suspended_active_cycle(api):
    """PRD §3.2: "Because activation can follow suspension, the license forms a
    cycle of `ACTIVE → SUSPENDED → ACTIVE`."

    Design: Difficulty/non_linear_state_machine/barber_license_active_suspended_cycle
    """
    set_clock("2026-06-10T08:00:00Z")
    shop = create_shop(name="Cycle Shop", tax_rate_pct=0)
    barber = get_success_data(api.create_barber(
        create_barber_payload(shop["id"], license_expires_on="2027-01-01"), OWNER))
    activated = validate_success(api.activate_license(barber["id"], OWNER), 200)
    assert activated["license_status"] == "ACTIVE"
    suspended = validate_success(api.suspend_license(barber["id"], OWNER), 200)
    assert suspended["license_status"] == "SUSPENDED", suspended
    reactivated = validate_success(api.activate_license(barber["id"], OWNER), 200)
    assert reactivated["license_status"] == "ACTIVE", reactivated


def test_suspend_cancels_future_booked_appointments(api):
    """PRD §3.2: "Suspending an `ACTIVE` license moves it `ACTIVE → SUSPENDED` and,
    as a cascade, cancels every `BOOKED` appointment of that barber whose
    `start_utc` is later than the current clock, moving each `BOOKED → CANCELLED`
    with no no-show fee."

    Design: Difficulty/non_linear_state_machine/barber_license_active_suspended_cycle
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Cycle Shop", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T16:00:00Z")  # future
    validate_success(api.suspend_license(ctx["barber"]["id"], OWNER), 200)
    after = validate_success(api.get_appointment(appt["id"], OWNER), 200)
    assert after["status"] == "CANCELLED", after


# SKIPPED corner instance: revoke_license_terminal_lockdown_reactivate_fails
# (section state_machines). The instance asserts that activating a REVOKED license
# returns ERR_INVALID_STATE. PRD §3.2 describes REVOKED as the terminal license
# state but never names the error returned when activate is called on it; the
# "wrong state -> ERR_INVALID_STATE" rule is spelled out in PRD prose only for
# tickets (§3.9) and queue tickets (§3.5), not for the license. A PRD-only reader
# cannot uniquely derive that this specific error_id fires here, so the instance
# fails the unique-derivability condition and is skipped (no test emitted).


def test_activate_expired_license_rejected(api):
    """PRD §3.2: "Activating a barber ... succeeds only if `license_expires_on` is
    on or after the logical clock's current date; an expired license is rejected
    with `ERR_LICENSE_EXPIRED`."

    Design: Corner/state_machines/activate_expired_license_returns_license_expired
    """
    set_clock("2026-06-10T08:00:00Z")
    shop = create_shop(name="S", tax_rate_pct=0)
    barber = get_success_data(api.create_barber(
        create_barber_payload(shop["id"], license_expires_on="2026-01-05"), OWNER))
    res = api.activate_license(barber["id"], OWNER)
    validate_error(res, "ERR_LICENSE_EXPIRED")


def test_check_in_requires_barber_active(api):
    """PRD §3.6: "Checking in a `BOOKED` appointment is a `Receptionist`-or-
    `ShopOwner` action requiring an `OPEN` shop (`ERR_SHOP_CLOSED`), the barber's
    `license_status` of `ACTIVE` (`ERR_BARBER_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_barber_license_active
    """
    # Use a large grace so the suspend cascade only targets future appts; book at
    # 09:30, advance clock to 10:00 so the appt is in the past at suspend time and
    # the cascade (future BOOKED only) skips it, leaving it BOOKED.
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Gate Shop", "tax_rate_pct": 0, "late_grace_minutes": 1000},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T09:30:00Z")
    set_clock("2026-06-10T10:00:00Z")
    validate_success(api.suspend_license(ctx["barber"]["id"], OWNER), 200)
    still = validate_success(api.get_appointment(appt["id"], OWNER), 200)
    assert still["status"] == "BOOKED", still  # cascade skipped (start < clock)
    res = api.check_in_appointment(appt["id"], RECEPTION)
    validate_error(res, "ERR_BARBER_NOT_ACTIVE")


def test_check_in_succeeds_while_barber_active(api):
    """PRD §3.6: "Checking in a `BOOKED` appointment is a `Receptionist`-or-
    `ShopOwner` action requiring an `OPEN` shop (`ERR_SHOP_CLOSED`), the barber's
    `license_status` of `ACTIVE` (`ERR_BARBER_NOT_ACTIVE`)". "Check-in moves the
    appointment `BOOKED → CHECKED_IN`".

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_barber_license_active
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Gate Shop", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    # Barber remains ACTIVE -> the cross-entity gate is satisfied, check-in passes.
    checked = validate_success(api.check_in_appointment(appt["id"], RECEPTION), 200)
    assert checked["status"] == "CHECKED_IN", checked


def test_queue_serve_requires_shop_open(api):
    """PRD §3.5: "Serving a queue ticket is a `Receptionist`-or-`ShopOwner` action
    that pulls the front of the line forward. The shop must be `OPEN`."
    PRD §3.1: "While a shop is `CLOSED`, booking, taking a queue ticket, checking
    in, serving, checking out, and marking no-shows are all blocked with
    `ERR_SHOP_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/queue_serve_requires_shop_open
    """
    ctx = setup_shop_with_active_barber(shop_overrides={"name": "Closeable Shop", "tax_rate_pct": 0})
    q = enqueue(ctx["shop"]["id"], ctx["customer"]["id"], requested_barber_id=ctx["barber"]["id"])
    validate_success(api.close_shop(ctx["shop"]["id"], OWNER), 200)
    res = api.serve_queue_ticket(q["id"], RECEPTION)
    validate_error(res, "ERR_SHOP_CLOSED")
    still = validate_success(api.get_queue_ticket(q["id"], OWNER), 200)
    assert still["status"] == "WAITING", still


def test_queue_serve_succeeds_while_shop_open(api):
    """PRD §3.5: "Serving a queue ticket is a `Receptionist`-or-`ShopOwner` action
    that pulls the front of the line forward. The shop must be `OPEN`." "Serving
    moves the queue ticket `WAITING → SERVING`, opens a sales ticket".

    Design: Difficulty/cross_entity_state_dependency/queue_serve_requires_shop_open
    """
    ctx = setup_shop_with_active_barber(shop_overrides={"name": "Open Shop", "tax_rate_pct": 0})
    q = enqueue(ctx["shop"]["id"], ctx["customer"]["id"], requested_barber_id=ctx["barber"]["id"])
    served = validate_success(api.serve_queue_ticket(q["id"], RECEPTION), 200)
    assert served["status"] == "SERVING", served
    assert served["ticket_id"] is not None, served


def test_create_barber_missing_comp_model_rejected(api):
    """PRD §3.2: comp_model "is either `BOOTH_RENT` or `COMMISSION` and is fixed at
    creation because it selects the settlement formula". A missing required field
    yields `ERR_INVALID_REQUEST`.

    Design: Corner/entities/create_barber_missing_comp_model_returns_invalid_request
    """
    set_clock("2026-06-10T08:00:00Z")
    shop = create_shop(name="S", tax_rate_pct=0)
    res = api.create_barber(
        {"shop_id": shop["id"], "full_name": "Bo", "license_number": "L1",
         "license_expires_on": "2027-01-01"},
        OWNER,
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_booth_rent_defaults_from_shop(api):
    """PRD §3.2: "For a booth-rent barber the owner may set `booth_rent_cents`;
    when omitted it inherits the shop's `default_booth_rent_cents`."

    Design: Corner/entities/barber_booth_rent_defaults_from_shop_when_omitted
    """
    set_clock("2026-06-10T08:00:00Z")
    shop = create_shop(name="S", tax_rate_pct=0, default_booth_rent_cents=4500)
    barber = validate_success(
        api.create_barber(
            create_barber_payload(shop["id"], comp_model="BOOTH_RENT",
                                  license_expires_on="2027-01-01"),
            OWNER),
        201,
    )
    assert_barber(barber)
    assert barber["booth_rent_cents"] == 4500, barber


def test_get_barber_nonexistent_returns_not_found(api):
    """PRD §2.8: "rejects on the first identifier that does not resolve, returning
    that identifier's specific not-found error — `ERR_SHOP_NOT_FOUND`,
    `ERR_BARBER_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_QUEUE_TICKET_NOT_FOUND`,
    `ERR_TICKET_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND`, as applicable."

    Design: Corner/entities/get_barber_nonexistent_returns_not_found
    """
    res = api.get_barber(NON_EXISTENT_UUID, OWNER)
    validate_error(res, "ERR_BARBER_NOT_FOUND")
