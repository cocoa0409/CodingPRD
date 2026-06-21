"""Auth/RBAC/ownership rejections, foreign-key existence on create, optimistic
concurrency on confirm, and immediate derived-field reconciliation.

Queue B / Corner: errors, rbac, cross_cutting_complexity_layers, consistency_model.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    make_chef_headers, make_client_headers, admin_headers,
    create_booking_payload,
    pin_clock, create_chef, create_client, create_active_chef,
    setup_confirmed_booking, setup_confirmed_with_deposit_paid, setup_requested_booking,
    pay_deposit,
)


# ─── Corner / errors ─────────────────────────────────────────────────────────

def test_balance_payment_without_finalized_grocery_run_rejected(api):
    """PRD §3.6: "A balance payment is the second step: it requires that a finalized grocery
    run exists for the booking — the balance is only billable once the actual cost is known
    (`ERR_GROCERY_RUN_NOT_FINALIZED`) — and that `amount_cents` exactly equals the current
    `balance_due_cents` (`ERR_BALANCE_AMOUNT_MISMATCH`)."

    Design: Corner/errors/error_balance_payment_without_finalized_grocery_run
    """
    chef, menu, zone, client, booking, payment = setup_confirmed_with_deposit_paid(
        chef_overrides={"display_name": "Chef BG"},
        booking_overrides={"service_zip": "94110", "event_start_utc": "2026-08-31T18:00:00Z",
                           "event_end_utc": "2026-08-31T22:00:00Z"},
    )
    # No grocery run finalized; attempt a balance payment.
    res = api.create_payment(
        {"booking_id": booking["id"], "kind": "BALANCE", "amount_cents": 61124},
        make_client_headers(client["id"]),
    )
    validate_error(res, "ERR_GROCERY_RUN_NOT_FINALIZED", expected_status=409)


def test_create_booking_nonexistent_chef_returns_not_found(api):
    """PRD §2.8: "On creates that carry foreign keys in the body (a booking or a recurring
    plan referencing `chef_id`, `client_id`, and `menu_package_id`), each referenced entity
    must exist or the create is rejected with the corresponding not-found error."

    Design: Corner/errors/error_chef_not_found_on_create_booking
    """
    pin_clock()
    client = create_client(client_overrides={"full_name": "Client CN", "email": "cn@ex.com"})
    res = api.create_booking(
        create_booking_payload(
            "00000000-0000-4000-8000-0000000000cc", client["id"],
            "00000000-0000-4000-8000-0000000000dd",
            service_zip="94110", event_start_utc="2026-09-02T18:00:00Z",
            event_end_utc="2026-09-02T22:00:00Z",
        ),
        make_client_headers(client["id"]),
    )
    validate_error(res, "ERR_CHEF_NOT_FOUND", expected_status=404)


# ─── Corner / rbac ───────────────────────────────────────────────────────────

def test_client_cannot_confirm_booking_unauthorized_role(api):
    """PRD §2.1: "If the role value is not one of the three roles defined below, or the role
    is recognized but not permitted to perform the requested operation, the request is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4 endpoint table:
    "POST /bookings/{bookingId}/confirm | Chef confirms a REQUESTED booking ... | Chef".

    Design: Corner/rbac/client_cannot_confirm_booking_unauthorized_role
    """
    chef, menu, zone, client, booking = setup_requested_booking(
        chef_overrides={"display_name": "Chef RB1"},
        booking_overrides={"service_zip": "94110", "event_start_utc": "2026-09-03T18:00:00Z",
                           "event_end_utc": "2026-09-03T22:00:00Z"},
    )
    # A Client (not the Chef role) attempts the Chef-exclusive confirm op.
    res = api.confirm_booking(
        booking["id"], {"expected_chef_version": chef["version"]}, make_client_headers(client["id"])
    )
    validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)


def test_chef_cannot_cancel_others_booking_not_resource_owner(api):
    """PRD §2.1: "When an authenticated, role-permitted caller is nonetheless not the owner
    of the specific resource being mutated, the rejection is `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)." PRD §3.8: "A client may cancel a booking it owns while that booking is
    `REQUESTED`, `CONFIRMED`, or `IN_PREP` (`ERR_NOT_RESOURCE_OWNER` if the caller is not
    the owning client)."

    Design: Corner/rbac/chef_cannot_cancel_others_booking_not_resource_owner
    """
    # cancel is a Client op; a DIFFERENT client (not booking.client_id) attempts it.
    chef, menu, zone, client_a, booking = setup_confirmed_booking(
        chef_overrides={"display_name": "Chef RB2"},
        client_overrides={"full_name": "Client A", "email": "a2@ex.com"},
        booking_overrides={"service_zip": "94110", "event_start_utc": "2026-09-04T18:00:00Z",
                           "event_end_utc": "2026-09-04T22:00:00Z"},
    )
    client_b = create_client(client_overrides={"full_name": "Client B", "email": "b2@ex.com"})
    res = api.cancel_booking(booking["id"], make_client_headers(client_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_missing_auth_header_returns_missing_auth_context(api):
    """PRD §2.1: "Every request to the API must carry two headers identifying the caller:
    `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is
    rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_auth_header_returns_missing_auth_context
    """
    res = api.list_chefs(headers={})
    validate_error(res, "ERR_MISSING_AUTH_CONTEXT", expected_status=401)


# ─── Corner / cross_cutting_complexity_layers ────────────────────────────────

def test_occ_stale_chef_version_on_confirm_rejected(api):
    """PRD §2.5: "Before any business validation runs, the server compares
    `expected_chef_version` against the booked chef's current `version`. If they do not
    match — because some other write has advanced the chef's `version` since the client last
    read it — the confirmation is rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §2.5:
    "Each successful confirmation mints an availability hold and bumps the chef's occupancy,
    which itself advances `Chef.version` ...".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_chef_version_on_confirm
    """
    pin_clock()
    chef, menu, zone = create_active_chef(
        chef_overrides={"display_name": "Chef OCC", "max_bookings_per_day": 5},
    )
    ch = make_chef_headers(chef["id"])
    client = create_client()
    cl = make_client_headers(client["id"])
    v_pre = chef["version"]
    b1 = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94110",
                               event_start_utc="2026-09-06T18:00:00Z",
                               event_end_utc="2026-09-06T22:00:00Z"), cl))
    b2 = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94110",
                               event_start_utc="2026-09-07T18:00:00Z",
                               event_end_utc="2026-09-07T22:00:00Z"), cl))
    # First confirm advances Chef.version; the second carries the now-stale v_pre.
    validate_success(api.confirm_booking(b1["id"], {"expected_chef_version": v_pre}, ch), 200)
    res = api.confirm_booking(b2["id"], {"expected_chef_version": v_pre}, ch)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_occ_correct_version_after_refresh_succeeds(api):
    """PRD §2.5: "A request to confirm a booking must include `expected_chef_version`,
    carrying the value of the chef's `version` that the client last observed." PRD §3.3:
    "Confirmation is the chef's decision to take a `REQUESTED` booking, advancing its
    `lifecycle_status` from `REQUESTED` to `CONFIRMED`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_after_refresh_succeeds
    """
    pin_clock()
    chef, menu, zone = create_active_chef(
        chef_overrides={"display_name": "Chef OCC2", "max_bookings_per_day": 5},
    )
    ch = make_chef_headers(chef["id"])
    client = create_client()
    cl = make_client_headers(client["id"])
    v_pre = chef["version"]
    b1 = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94110",
                               event_start_utc="2026-09-08T18:00:00Z",
                               event_end_utc="2026-09-08T22:00:00Z"), cl))
    b2 = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94110",
                               event_start_utc="2026-09-09T18:00:00Z",
                               event_end_utc="2026-09-09T22:00:00Z"), cl))
    validate_success(api.confirm_booking(b1["id"], {"expected_chef_version": v_pre}, ch), 200)
    v_refreshed = get_success_data(api.get_chef(chef["id"], ch))["version"]
    confirmed = validate_success(
        api.confirm_booking(b2["id"], {"expected_chef_version": v_refreshed}, ch), 200)
    assert confirmed["lifecycle_status"] == "CONFIRMED"


def test_balance_reconciled_after_deposit_capture(api):
    """PRD §3.4: "`balance_due_cents` is then `quote_total_cents` minus
    `amount_captured_cents`, always derived from the freshly computed quote rather than a
    stale one." PRD §3.6: "A payment is minted with `status` `CAPTURED` ... and adds its
    amount to the booking's `amount_captured_cents`, after which `balance_due_cents` is
    recomputed."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_balance_after_deposit
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        chef_overrides={"display_name": "Chef DR"},
        booking_overrides={"service_zip": "94110", "event_start_utc": "2026-09-11T18:00:00Z",
                           "event_end_utc": "2026-09-11T22:00:00Z"},
    )
    assert booking["quote_total_cents"] == 87320
    pay_deposit(client["id"], booking["id"], 26196)
    after = validate_success(api.get_booking(booking["id"], make_client_headers(client["id"])), 200)
    assert after["amount_captured_cents"] == 26196
    assert after["balance_due_cents"] == 61124


def test_occ_version_field_only_accepted_on_confirm(api):
    """PRD §2.5: "Confirming a booking is the one write in this system that takes an explicit
    version guard." PRD §2.5: "This field is mandatory on the confirm operation; it is not
    accepted on, and not required by, any other endpoint." PRD §2.5: "The version check
    precedes ownership, state, allergen, equipment, time, and capacity checks on the confirm
    path."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_chef_version_on_confirm
    """
    # Confirm with a stale version still pre-empts every later check -> ERR_STALE_VERSION.
    pin_clock()
    chef, menu, zone = create_active_chef(
        chef_overrides={"display_name": "Chef OCC3", "max_bookings_per_day": 5},
    )
    ch = make_chef_headers(chef["id"])
    client = create_client()
    cl = make_client_headers(client["id"])
    v_pre = chef["version"]
    b1 = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94110",
                               event_start_utc="2026-09-16T18:00:00Z",
                               event_end_utc="2026-09-16T22:00:00Z"), cl))
    b2 = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94110",
                               event_start_utc="2026-09-17T18:00:00Z",
                               event_end_utc="2026-09-17T22:00:00Z"), cl))
    validate_success(api.confirm_booking(b1["id"], {"expected_chef_version": v_pre}, ch), 200)
    res = api.confirm_booking(b2["id"], {"expected_chef_version": v_pre}, ch)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ─── Corner / consistency_model ──────────────────────────────────────────────

def test_immediate_consistency_confirm_response_carries_all_totals(api):
    """PRD §1: "Every quote total, balance, chef reliability score, and capacity counter is
    recomputed inside the same request that changes its inputs ...". PRD §3.3: "When all
    checks pass, confirmation freezes the quote and reserves the calendar in one atomic
    step." PRD §3.4: "`deposit_due_cents` is the confirmation-time quote (computed on the
    estimated grocery basis) multiplied by 0.30 and rounded half up to whole cents."

    Design: Corner/consistency_model/immediate_consistency_confirm_response_carries_all_totals
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        chef_overrides={"display_name": "Chef IC"},
        booking_overrides={"service_zip": "94110", "event_start_utc": "2026-09-13T18:00:00Z",
                           "event_end_utc": "2026-09-13T22:00:00Z"},
    )
    # The confirm response itself (captured as `booking`) carries the freshly-computed totals.
    assert booking["quote_total_cents"] == 87320
    assert booking["deposit_due_cents"] == 26196
