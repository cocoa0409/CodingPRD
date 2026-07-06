"""Entity creation/retrieval basics, simple state-machine guards, an action
endpoint, and role-based access control.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, ApiErrorId, NON_EXISTENT_UUID,
    make_guest_patron_headers,
    create_ticket_payload, create_add_on_payload,
)
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_park, assert_session_ticket


# ===========================================================================
# Corner/entities/create_park_returns_201_with_open_posture_and_system_fields
# ===========================================================================

def test_create_park_returns_open_posture_and_system_fields(api):
    """PRD §3.1: "A freshly created park has `operational_posture` of `OPEN`, an `open_lane_count` of
    0, and a `total_capacity_remaining` of 0."
    PRD §2.4: "a `version` integer that starts at 1 and increments by one on every mutation."

    Design: Corner/entities/create_park_returns_201_with_open_posture_and_system_fields
    """
    data = validate_success(api.create_park({"name": "First Park", "resident_zip_prefixes": []}, fx.ANON), 201)
    assert_park(data)
    assert data["operational_posture"] == "OPEN"
    assert data["open_lane_count"] == 0
    assert data["version"] == 1


# ===========================================================================
# Corner/entities/create_park_applies_defaults_when_thresholds_omitted
# ===========================================================================

def test_create_park_applies_threshold_defaults(api):
    """PRD §3.1: "a `min_snow_depth_cm` (defaulting to 15), and a `max_safe_wind_kph` (defaulting to
    50)."

    Design: Corner/entities/create_park_applies_defaults_when_thresholds_omitted
    """
    data = validate_success(api.create_park({"name": "Default Park"}, fx.ANON), 201)
    assert data["min_snow_depth_cm"] == 15
    assert data["max_safe_wind_kph"] == 50


# ===========================================================================
# Corner/entities/get_park_not_found_returns_404
# ===========================================================================

def test_get_nonexistent_park_returns_not_found(api):
    """PRD §2.9: "any referenced resource that does not exist yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_park_not_found_returns_404
    """
    resp = api.get_park("00000000-0000-4000-8000-000000000000", fx.OPERATOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner/entities/create_ticket_missing_required_field_returns_invalid_request
# ===========================================================================

def test_create_ticket_missing_rider_age_returns_invalid_request(api):
    """PRD §2.10: "the catch-all request-shape check that required fields are present and well-typed,
    enum values are in their declared sets, and numeric ranges are honored, which
    otherwise yields `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.4: "the declared `rider_age_years` (at least 0)."

    Design: Corner/entities/create_ticket_missing_required_field_returns_invalid_request
    """
    fx.set_clock("2026-03-20T09:00:00Z")
    park = fx.create_park(name="Tk Park", resident_zip_prefixes=[])
    patron = fx.create_patron(zip_code="90001")
    block = fx.create_time_block(park["id"], starts_at="2026-03-20T10:00:00Z", ends_at="2026-03-20T12:00:00Z")
    # Omit rider_age_years (required, no default).
    payload = {"park_id": park["id"], "time_block_id": block["id"],
               "holder_patron_id": patron["id"], "rider_height_cm": 175}
    resp = api.create_ticket(payload, make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner/entities/create_ticket_invalid_enum_addon_category_returns_invalid_request
# ===========================================================================

def test_create_addon_invalid_category_returns_invalid_request(api):
    """PRD §3.8: "a `category` of `FOOD`, `RENTAL_UPGRADE`, or `HOT_DRINK".
    PRD §2.10: "the catch-all request-shape check that required fields are present and well-typed,
    enum values are in their declared sets, and numeric ranges are honored, which
    otherwise yields `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_ticket_invalid_enum_addon_category_returns_invalid_request
    """
    fx.set_clock("2026-03-21T09:00:00Z")
    park = fx.create_park(name="Enum Park", resident_zip_prefixes=[])
    patron = fx.create_patron(zip_code="90002")
    block = fx.create_time_block(park["id"], starts_at="2026-03-21T10:00:00Z", ends_at="2026-03-21T12:00:00Z")
    ticket = fx.create_ticket(park["id"], block["id"], patron["id"])
    payload = create_add_on_payload(park_id=park["id"], ticket_id=ticket["id"],
                                    category="SOUVENIR", unit_price_cents=500, quantity=1)
    resp = api.create_add_on(payload, make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner/entities/ticket_computed_base_price_ignores_client_supplied_value
# ===========================================================================

def test_ticket_base_price_computed_for_adult_walkup_non_resident(api):
    """PRD §3.4: "otherwise (ages 13 through 64) the base is 3500 cents."
    PRD §3.4: "computes `is_resident` — true when the holder's zip prefix matches the park's
    `resident_zip_prefixes` at issuance, false otherwise".
    PRD §3.4: "A new ticket starts with `lifecycle_state` of `RESERVED` and `checkin_state` of
    `NOT_CHECKED_IN".

    Design: Corner/entities/ticket_computed_base_price_ignores_client_supplied_value
    """
    fx.set_clock("2026-03-22T09:00:00Z")
    park = fx.create_park(name="Compute Park", resident_zip_prefixes=[])
    patron = fx.create_patron(zip_code="90003")
    block = fx.create_time_block(park["id"], starts_at="2026-03-22T10:00:00Z", ends_at="2026-03-22T12:00:00Z")
    payload = create_ticket_payload(park_id=park["id"], time_block_id=block["id"],
                                    holder_patron_id=patron["id"], rider_height_cm=175, rider_age_years=40)
    data = validate_success(api.create_ticket(payload, make_guest_patron_headers(patron["id"])), 201)
    assert_session_ticket(data)
    assert data["base_price_cents"] == 3500
    assert data["is_resident"] is False
    assert data["lifecycle_state"] == "RESERVED"
    assert data["checkin_state"] == "NOT_CHECKED_IN"


# ===========================================================================
# Corner/entities/list_parks_pagination_envelope_fields_present
# ===========================================================================

def test_list_parks_pagination_envelope(api):
    """PRD §2.3: "Each list response carries these four fields in the `meta` object of the envelope:
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_parks_pagination_envelope_fields_present
    """
    fx.create_park(name="P1", resident_zip_prefixes=[])
    fx.create_park(name="P2", resident_zip_prefixes=[])
    data, meta = validate_paginated(api.list_parks(fx.OPERATOR, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ===========================================================================
# Corner/state_machines/refund_from_reserved_ticket_returns_invalid_state
# ===========================================================================

def test_refund_reserved_ticket_returns_invalid_state(api):
    """PRD §3.4: "A confirmed ticket may be refunded by its holder — the `CONFIRMED → REFUNDED`
    transition — but only while the ticket is `CONFIRMED".
    PRD §3.1: "A transition requested from a state where it is not defined is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/refund_from_reserved_ticket_returns_invalid_state
    """
    fx.set_clock("2026-03-23T09:00:00Z")
    park = fx.create_park(name="RefBad", resident_zip_prefixes=[])
    patron = fx.create_patron(zip_code="90004")
    block = fx.create_time_block(park["id"], starts_at="2026-03-23T10:00:00Z", ends_at="2026-03-23T12:00:00Z")
    ticket = fx.create_ticket(park["id"], block["id"], patron["id"])  # RESERVED, never confirmed
    resp = api.refund_ticket(ticket["id"], make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_ticket(ticket["id"], fx.OPERATOR), 200)
    assert fetched["lifecycle_state"] == "RESERVED"


# ===========================================================================
# Corner/state_machines/sweep_already_swept_block_returns_invalid_state
# ===========================================================================

def test_sweep_already_swept_block_returns_invalid_state(api):
    """PRD §3.1: "Sweeping a block — `ACTIVE → SWEPT` — requires the block to be `ACTIVE` and is
    terminal".
    PRD §3.1: "A transition requested from a state where it is not defined is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sweep_already_swept_block_returns_invalid_state
    """
    fx.set_clock("2026-03-24T10:30:00Z")
    park = fx.create_park(name="SweepPark", resident_zip_prefixes=[])
    block = fx.create_time_block(park["id"], starts_at="2026-03-24T10:00:00Z", ends_at="2026-03-24T12:00:00Z")
    fx.activate_block(block["id"])
    validate_success(api.sweep_time_block(block["id"], fx.OPERATOR), 200)
    resp = api.sweep_time_block(block["id"], fx.OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_time_block(block["id"], fx.OPERATOR), 200)
    assert fetched["status"] == "SWEPT"


# ===========================================================================
# Corner/state_machines/activate_block_outside_window_returns_block_window_closed
# ===========================================================================

def test_activate_block_before_window_returns_block_window_closed(api):
    """PRD §3.1: "Activating a block — `SCHEDULED → ACTIVE` — requires the block to be `SCHEDULED`,
    the park's posture to be other than `CLOSED`, and the logical clock to fall within
    the block's window, meaning the clock instant is at or after `starts_at` and
    strictly before `ends_at`; activating outside that window is rejected with
    `ERR_BLOCK_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/state_machines/activate_block_outside_window_returns_block_window_closed
    """
    fx.set_clock("2026-03-25T09:00:00Z")  # before the 10:00 window
    park = fx.create_park(name="WinPark", resident_zip_prefixes=[])
    block = fx.create_time_block(park["id"], starts_at="2026-03-25T10:00:00Z", ends_at="2026-03-25T12:00:00Z")
    resp = api.activate_time_block(block["id"], fx.OPERATOR)
    validate_error(resp, ApiErrorId.ERR_BLOCK_WINDOW_CLOSED.value)
    fetched = validate_success(api.get_time_block(block["id"], fx.OPERATOR), 200)
    assert fetched["status"] == "SCHEDULED"


# ===========================================================================
# Corner/endpoints/equipment_return_transitions_dispatched_to_returned
# ===========================================================================

def test_equipment_return_transitions_to_returned(api):
    """PRD §3.5: "A rental starts in `state` `DISPATCHED` and may be moved by a marshal to `RETURNED`
    or `DAMAGED`, each requiring the rental to be currently `DISPATCHED`."

    Design: Corner/endpoints/equipment_return_transitions_dispatched_to_returned
    """
    fx.set_clock("2026-04-03T09:00:00Z")
    park = fx.create_park(name="EquipPark", resident_zip_prefixes=[])
    patron = fx.create_patron(zip_code="90014")
    block = fx.create_time_block(park["id"], starts_at="2026-04-03T10:00:00Z", ends_at="2026-04-03T12:00:00Z")
    ticket = fx.create_ticket(park["id"], block["id"], patron["id"])
    rental = fx.dispatch_tube(ticket["id"], tube_size="LARGE")
    data = validate_success(api.return_equipment_rental(rental["id"], fx.MARSHAL), 200)
    assert data["state"] == "RETURNED"


# ===========================================================================
# Corner/rbac/guest_cannot_close_lane
# ===========================================================================

def test_guest_cannot_close_lane(api):
    """PRD §2.1: "When a caller presents valid headers but the role is not permitted to invoke the
    targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/guest_cannot_close_lane
    """
    fx.set_clock("2026-03-01T09:00:00Z")
    park = fx.create_park(name="RbacPark", resident_zip_prefixes=[])
    lane = fx.create_lane(park["id"], label="L1", rider_capacity_per_block=5)
    patron = fx.create_patron(zip_code="90015")
    resp = api.close_lane(lane["id"], make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    fetched = validate_success(api.get_lane(lane["id"], fx.OPERATOR), 200)
    assert fetched["status"] == "OPEN"


# ===========================================================================
# Corner/rbac/guest_cannot_confirm_another_patrons_ticket
# ===========================================================================

def test_guest_cannot_confirm_another_patrons_ticket(api):
    """PRD §2.1: "ownership checks on any resource that references a patron compare the resource's
    `holder_patron_id` to `X-User-ID`."
    PRD §2.1: "A `GuestPatron` acting on a ticket they do not hold, or a `GroupHost` acting on a
    reservation they do not host, is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/guest_cannot_confirm_another_patrons_ticket
    """
    base = fx.setup_park_with_lane_and_block(
        clock="2026-04-05T10:30:00Z", lane_capacity=5, num_lanes=1,
        block_starts="2026-04-05T10:00:00Z", block_ends="2026-04-05T12:00:00Z",
    )
    park_id, block_id = base["park"]["id"], base["block"]["id"]
    pa, _ = fx.setup_waivered_patron(park_id)  # owner
    pb = fx.create_patron()                     # different patron
    ticket = fx.create_ticket(park_id, block_id, pa["id"])
    v = fx.block_version(block_id, pa["id"])
    # Patron B (X-User-ID = pb) confirms patron A's ticket.
    resp = api.confirm_ticket(ticket["id"], v, make_guest_patron_headers(pb["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    fetched = validate_success(api.get_ticket(ticket["id"], fx.OPERATOR), 200)
    assert fetched["lifecycle_state"] == "RESERVED"


# ===========================================================================
# Corner/rbac/missing_auth_headers_returns_unauthenticated
# ===========================================================================

def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not one of these
    declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    park = fx.create_park(name="AuthPark", resident_zip_prefixes=[])
    # GET /tickets with no auth headers at all.
    resp = api.list_tickets({}, params={"park_id": park["id"]})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
