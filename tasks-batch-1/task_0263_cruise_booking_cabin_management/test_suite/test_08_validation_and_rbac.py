"""Validation ordering, RBAC, ownership, OCC, and booking-inactive payment guard.

Covers the state-before-fiscal precedence on a cancelled booking, the
missing-header guard, role denials and entity-backed ownership, the stale
sailing-version OCC rejection, and payment creation against a cancelled booking.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_sailing_payload, create_booking_payload, create_payment_payload,
    create_folio_charge_payload, make_guest_user_headers,
    setup_open_sailing, create_quote_booking,
)

RM = TEST_USERS["revenue_manager_headers"]


# ===========================================================================
# Difficulty: state precedence beats fiscal on a cancelled booking
# ===========================================================================
def test_confirm_cancelled_booking_state_beats_fiscal(api):
    """PRD 2.5: "then the legality of the requested state transition
    (`ERR_INVALID_STATE`) ... then the deposit and balance gates
    (`ERR_BALANCE_OUTSTANDING` and its siblings)". Earlier checks strictly precede
    later ones, so a cancelled booking confirm surfaces `ERR_INVALID_STATE`.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_booking_confirm
    """
    sailing, category, booking = create_quote_booking(
        "guest-8", num_guests=2, num_cabins=2, guests=[("I One", 40), ("I Two", 38)],
    )
    get_success_data(api.cancel_booking(booking["id"], "CASH", make_guest_user_headers("guest-8")))
    resp = api.confirm_booking(booking["id"], make_guest_user_headers("guest-8"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_cancelled_booking_not_fiscal_error(api):
    """PRD 2.5: "Earlier checks strictly precede later ones; a failure surfaces the
    earliest applicable error rather than being masked by a later one." The state
    check (`ERR_INVALID_STATE`) precedes the balance gate.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_booking_confirm
    """
    sailing, category, booking = create_quote_booking(
        "guest-8b", num_guests=2, num_cabins=2, guests=[("I One", 40), ("I Two", 38)],
    )
    get_success_data(api.cancel_booking(booking["id"], "CASH", make_guest_user_headers("guest-8b")))
    resp = api.confirm_booking(booking["id"], make_guest_user_headers("guest-8b"))
    # The earliest applicable error is the state error, not the fiscal one.
    assert resp.status_code == 409
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value


# ===========================================================================
# Corner: missing header, RBAC, ownership
# ===========================================================================
def test_missing_user_context_header_rejected(api):
    """PRD 2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_user_context_header_rejected
    """
    resp = api._request("POST", "/sailings", create_sailing_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_guest_user_cannot_create_sailing(api):
    """PRD 2.1: "When a caller presents a well-formed role that is not authorized for
    the targeted operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD 4: `POST /sailings` is authorized for RevenueManager only.

    Design: Corner/rbac/guest_user_cannot_create_sailing
    """
    resp = api.create_sailing(create_sailing_payload(), make_guest_user_headers("guest-cx"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_guest_user_cannot_post_folio_charge(api):
    """PRD 2.1: "When a caller presents a well-formed role that is not authorized for
    the targeted operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD 4: `POST /folios/{id}/charges` is authorized for PortAgent only.

    Design: Corner/rbac/guest_user_cannot_post_folio_charge
    """
    resp = api.post_folio_charge(
        "33333333-3333-4333-8333-333333333333",
        create_folio_charge_payload("Spa", 5000),
        make_guest_user_headers("guest-cy"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_guest_user_cannot_act_on_other_users_booking(api):
    """PRD 2.1: "A `GuestUser` acting on a booking that is not theirs is rejected
    with `ERR_NOT_BOOKING_OWNER`." PRD 2.5: ownership is checked after existence and
    before the state transition.

    Design: Corner/rbac/guest_user_cannot_act_on_other_users_booking
    """
    sailing, category, booking = create_quote_booking(
        "guest-owner", num_guests=2, num_cabins=1, guests=[("C One", 40), ("C Two", 38)],
    )
    from test_helpers import make_and_capture_payment, get_booking
    deposit = get_booking(booking["id"])["deposit_due_cents"]
    make_and_capture_payment(booking["id"], "guest-owner", "DEPOSIT", deposit)
    # An intruder GuestUser (X-User-ID != owner_user_id) tries to hold the deposit.
    resp = api.hold_deposit(booking["id"], make_guest_user_headers("guest-intruder"))
    validate_error(resp, ApiErrorId.ERR_NOT_BOOKING_OWNER.value)


# ===========================================================================
# Corner: OCC stale version, booking-inactive payment
# ===========================================================================
def test_stale_sailing_version_on_booking_create(api):
    """PRD 2.7: "If `expected_sailing_version` does not equal the sailing's current
    `version` at the moment of creation, the request is rejected with
    `ERR_STALE_SAILING_VERSION` and HTTP status 412. Because opening, closing,
    departing, or cancelling a sailing each increments `Sailing.version` ... a
    non-matching value means another writer has changed the sailing".

    Design: Corner/errors/stale_sailing_version_on_booking_create
    """
    sailing, category, _cabins = setup_open_sailing(num_cabins=1)
    stale_version = sailing["version"]
    get_success_data(api.close_sailing(sailing["id"], RM))  # advances Sailing.version
    resp = api.create_booking(
        create_booking_payload(sailing["id"], category["id"], "guest-c14", stale_version),
        make_guest_user_headers("guest-c14"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SAILING_VERSION.value)


def test_payment_create_on_cancelled_booking_inactive(api):
    """PRD 3.5: "A payment cannot be created against a booking that is already
    `CANCELLED` or `EXPIRED`; such an attempt is rejected with
    `ERR_BOOKING_INACTIVE`."

    Design: Corner/errors/payment_create_on_cancelled_booking_inactive
    """
    sailing, category, booking = create_quote_booking(
        "guest-c17", num_guests=1, num_cabins=1, guests=[("C One", 40)],
    )
    get_success_data(api.cancel_booking(booking["id"], "CASH", make_guest_user_headers("guest-c17")))
    resp = api.create_payment(
        create_payment_payload(booking["id"], "DEPOSIT", 25000),
        make_guest_user_headers("guest-c17"),
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_INACTIVE.value)
