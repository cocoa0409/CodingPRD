"""CRUD creation, input validation, invalid-transition guards, and list envelopes."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    assert_court, setup_booking_scenario, make_court, make_reservation,
    create_court_payload, NON_EXISTENT_UUID, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── Corner: court_create_returns_all_fields ──────────────────────────
def test_court_create_returns_available_status():
    """PRD §3.1: "A new court opens in `AVAILABLE` status."

    Design: Corner/entities/court_create_returns_all_fields
    """
    res = api_client.create_court(
        create_court_payload(name="Outdoor 3", surface="CLAY",
                             location_type="OUTDOOR", hourly_rate_cents=3000), FD)
    court = validate_success(res, 201)
    assert_court(court)
    assert court["status"] == "AVAILABLE"
    assert court["location_type"] == "OUTDOOR"


# ─── Corner: member_get_not_found_returns_404 ─────────────────────────
def test_member_get_unknown_id_returns_not_found():
    """PRD §2.4: "Path identifiers are validated from left to right; the first
    identifier that does not resolve to an existing resource yields ERR_NOT_FOUND (HTTP
    404) before any later identifier or body reference is examined."

    Design: Corner/entities/member_get_not_found_returns_404
    """
    res = api_client.get_member(NON_EXISTENT_UUID, FD)
    validate_error(res, "ERR_NOT_FOUND")


# ─── Corner: member_create_missing_required_email ─────────────────────
def test_member_create_missing_email_rejected():
    """PRD §2.8: "Body well-formedness — required fields present, types and enums
    valid, end_time strictly greater than start_time ... otherwise ERR_VALIDATION
    (400)."
    PRD §3.2: "A member is created by the front desk with a full_name and a unique
    email, opening in ACTIVE status with no_show_strikes at 0 and account_balance_cents
    at 0."

    Design: Corner/entities/member_create_missing_required_email
    """
    res = api_client.create_member({"full_name": "No Email"}, FD)
    validate_error(res, "ERR_VALIDATION")


# ─── Corner: court_create_invalid_enum_surface ────────────────────────
def test_court_create_invalid_surface_enum_rejected():
    """PRD §2.8: "Body well-formedness — required fields present, types and enums
    valid ... otherwise ERR_VALIDATION (400)."
    PRD §3.1: "a surface of HARD, CLAY, or GRASS".

    Design: Corner/entities/court_create_invalid_enum_surface
    """
    res = api_client.create_court(
        {"name": "Bad", "surface": "WOOD", "location_type": "INDOOR",
         "hourly_rate_cents": 3000}, FD)
    validate_error(res, "ERR_VALIDATION")


# ─── Corner: cancel_already_cancelled_reservation_invalid_state ───────
def test_cancel_already_cancelled_reservation_rejected():
    """PRD §2.8: "State precondition — the target resource is in a state that admits the
    requested transition; otherwise ERR_INVALID_STATE (409). Applies to all
    state-transition operations."
    PRD §3.2: "Cancelling a BOOKED reservation restores its credits_used, whereas a
    reservation marked as a no-show retains its deduction."

    Design: Corner/state_machines/cancel_already_cancelled_reservation_invalid_state
    """
    s = setup_booking_scenario()
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z")
    get_success_data(api_client.cancel_reservation(res["id"], FD))
    again = api_client.cancel_reservation(res["id"], FD)
    validate_error(again, "ERR_INVALID_STATE")
    sub = validate_success(api_client.get_subscription(s["sub"]["id"], FD), 200)
    assert sub["court_credits_remaining"] == 8


# ─── Corner: reopen_available_court_invalid_state ─────────────────────
def test_reopen_available_court_rejected():
    """PRD §3.1: "Returning a court to service moves it MAINTENANCE → AVAILABLE, and
    requires the court to currently be in MAINTENANCE."

    Design: Corner/state_machines/reopen_available_court_invalid_state
    """
    court = make_court()
    res = api_client.court_reopen(court["id"], FD)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: retired_court_maintenance_terminal_lockdown ──────────────
def test_maintenance_on_retired_court_rejected():
    """PRD §3.1: "Taking an AVAILABLE court out of service moves it AVAILABLE →
    MAINTENANCE; attempting this on a court not currently AVAILABLE is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/retired_court_maintenance_terminal_lockdown
    """
    court = make_court()
    get_success_data(api_client.court_retire(court["id"], FD))
    res = api_client.court_maintenance(court["id"], FD)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api_client.get_court(court["id"], FD), 200)
    assert after["status"] == "RETIRED"


# ─── Corner: reservations_filtered_list_by_member_returns_array ───────
def test_reservations_filtered_by_member_returns_array():
    """PRD §2.3: "The meta block of a list response carries the pagination fields limit,
    offset, total_count, and has_more, where total_count reflects the full number of
    matching records before the page window is applied and has_more indicates whether
    records remain beyond the current page."

    Design: Corner/endpoints/reservations_filtered_list_by_member_returns_array
    """
    s = setup_booking_scenario()
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z")
    data, meta = validate_paginated(
        api_client.list_reservations(FD, params={"member_id": s["member"]["id"]}))
    assert res["id"] in [r["id"] for r in data]
    assert "total_count" in meta and "has_more" in meta


# ─── Corner: courts_list_pagination_envelope ──────────────────────────
def test_courts_list_returns_pagination_envelope():
    """PRD §2.3: "The meta block of a list response carries the pagination fields limit,
    offset, total_count, and has_more, where total_count reflects the full number of
    matching records before the page window is applied and has_more indicates whether
    records remain beyond the current page."

    Design: Corner/endpoints/courts_list_pagination_envelope
    """
    make_court()
    data, meta = validate_paginated(api_client.list_courts(FD))
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"missing pagination field {field}"
