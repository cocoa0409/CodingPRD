"""Role-based access control, optimistic-concurrency on reschedule, derived-field
reconciliation, and immediate-consistency of the quote.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_config, create_venue, create_quote_draft_booking, hold_booking,
    create_held_booking, create_weather_held_booking, take_payment,
    make_guardian_headers,
)

VM = "venue_manager_headers"
COORD = "coordinator_headers"


# ─── Corner: rbac / guardian_cannot_confirm_booking ────────────────────────────

def test_guardian_cannot_confirm_booking(api, coordinator_headers, guardian_headers):
    """PRD 2.1: "A `Coordinator` drives the booking lifecycle (holding, releasing,
    confirming, weather-holding, rescheduling, completing)".
    PRD 2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/guardian_cannot_confirm_booking
    """
    venue, room, package = setup_config()
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    hold_booking(bid)
    # Confirm is Coordinator-only; RBAC (priority 2) rejects before any ownership check.
    res = api.confirm_booking(bid, guardian_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "HELD"


# ─── Corner: rbac / coordinator_cannot_create_venue ────────────────────────────

def test_coordinator_cannot_create_venue(api, coordinator_headers):
    """PRD 2.1: "A `VenueManager` owns configuration — venues, rooms, party packages,
    and staff members".
    PRD 2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/coordinator_cannot_create_venue
    """
    res = api.create_venue({"name": "Nope"}, coordinator_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


# ─── Corner: rbac / missing_user_context_header ────────────────────────────────

def test_missing_user_context_header_rejected(api):
    """PRD 2.1: "A request that omits either header, or whose `X-User-Role` is not one
    of these four known roles, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

    Design: Corner/rbac/missing_user_context_header
    """
    res = api.list_venues(headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=401)


# ─── Corner: cross_cutting_complexity_layers / occ_stale_version_on_reschedule ─

def test_reschedule_with_stale_version_rejected(api, coordinator_headers):
    """PRD 2.6: "The server compares it against the booking's current `version`; if
    another writer has advanced the version since the client read it ... the client's
    view is stale and the reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_reschedule
    """
    ctx = create_weather_held_booking(children_count=8)
    bid = ctx["booking"]["id"]
    current_version = ctx["booking"]["version"]
    res = api.reschedule_booking(
        bid, {"event_start_utc": "2026-07-05T10:00:00Z",
              "expected_booking_version": current_version - 1}, coordinator_headers)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "WEATHER_HOLD"


# ─── Corner: cross_cutting_complexity_layers / derived_balance_reconciles_after_payment

def test_balance_and_status_reconcile_after_payment(api, coordinator_headers):
    """PRD 3.11: "After this, `balance_due_cents` is reconciled as the applicable total
    — `final_total_cents` when the booking is `COMPLETED`, otherwise `quote_total_cents`
    — minus `amount_paid_cents`."
    PRD 3.11: "Otherwise, if `amount_paid_cents` is at least `deposit_due_cents`, the
    status is `DEPOSIT_PAID`."

    Design: Corner/cross_cutting_complexity_layers/derived_balance_reconciles_after_payment
    """
    venue, room, package, booking = create_held_booking(
        children_count=8, base_price_cents=30000, included_children=8, deposit_pct=0.25)
    bid = booking["id"]  # quote 30000, deposit 7500
    paid = take_payment(bid, 10000, direction="CHARGE", purpose="BALANCE")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["amount_paid_cents"] == 10000
    assert booking["balance_due_cents"] == 20000
    assert booking["payment_status"] == "DEPOSIT_PAID"


# ─── Corner: consistency_model / immediate_quote_visible_in_create_response ────

def test_quote_total_present_in_create_response(api, coordinator_headers):
    """PRD 3.2: "The **quote estimate** is computed immediately and stored as
    `quote_total_cents`."

    Design: Corner/consistency_model/immediate_quote_visible_in_create_response
    """
    venue, room, package = setup_config(base_price_cents=30000, included_children=8,
                                        per_extra_child_cents=1500, max_capacity=20)
    res = api.create_booking(
        {"room_id": room["id"], "package_id": package["id"],
         "event_start_utc": "2026-07-01T10:00:00Z", "children_count": 11}, coordinator_headers)
    booking = validate_success(res, 201)
    # Overage 3 -> 30000 + 3*1500 = 34500, present immediately in the create response.
    assert booking["quote_total_cents"] == 34500
