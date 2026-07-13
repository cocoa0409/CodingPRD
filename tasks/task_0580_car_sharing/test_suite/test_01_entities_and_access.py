"""Registration, resource reads, required-field validation, RBAC, ownership.

Covers Corner queue: entities, rbac, and the ownership validation instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_host_payload, create_vehicle_payload,
    make_host_headers, make_guest_headers, make_admin_headers, make_anonymous_headers,
    register_host, register_unverified_guest,
)

ANON = make_anonymous_headers()
ADMIN = make_admin_headers()


def test_register_host_returns_active_zeroed_ledger(api):
    """PRD §3.1: "A newly registered host is `ACTIVE`, and all five ledger
    totals start at zero."

    Design: Corner/entities/create_host_returns_201_active
    """
    resp = api.create_host(create_host_payload(name="Host AA", email="haa@x.com"), ANON)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["pending_balance_cents"] == 0
    assert data["available_balance_cents"] == 0
    assert data["reserved_payout_cents"] == 0
    assert data["lifetime_earnings_cents"] == 0
    assert data["lifetime_paid_cents"] == 0


def test_get_unknown_vehicle_returns_not_found(api):
    """PRD §2.5: "The per-entity codes are `ERR_HOST_NOT_FOUND`,
    `ERR_GUEST_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_TRIP_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_PRICING_RULE_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`, and `ERR_PAYOUT_NOT_FOUND`."

    Design: Corner/entities/get_vehicle_not_found
    """
    resp = api.get_vehicle(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_FOUND)


def test_create_vehicle_missing_required_field_rejected(api):
    """PRD §2.5: "If the body itself is malformed — not valid JSON, missing a
    required field, or carrying a value of the wrong type or an invalid enum
    member — the request is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_vehicle_missing_required_field_rejected
    """
    host = register_host(api, name="Host AB", email="hab@x.com")
    headers = make_host_headers(host["id"])
    # base_daily_price_cents is a required booking-price field (PRD §3.1); omit it.
    payload = {"host_id": host["id"], "make": "Toyota", "model": "Corolla",
               "year": 2022, "location_city": "SF"}
    resp = api.create_vehicle(payload, headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_new_vehicle_computed_counters_zero_and_draft(api):
    """PRD §3.1: "A vehicle also tracks two computed counters,
    `booked_night_count` and `completed_trip_count`, both starting at zero. A
    new vehicle begins in `DRAFT`."

    Design: Corner/entities/vehicle_computed_booked_nights_defaults_zero
    """
    host = register_host(api, name="Host AC", email="hac@x.com")
    headers = make_host_headers(host["id"])
    resp = api.create_vehicle(create_vehicle_payload(host["id"]), headers)
    data = validate_success(resp, expected_status=201)
    assert data["booked_night_count"] == 0
    assert data["completed_trip_count"] == 0
    assert data["status"] == "DRAFT"


def test_list_vehicles_carries_pagination_meta(api):
    """PRD §2.3: "The `meta` object of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_vehicles_pagination_envelope
    """
    host = register_host(api, name="Host AD", email="had@x.com")
    headers = make_host_headers(host["id"])
    api.create_vehicle(create_vehicle_payload(host["id"]), headers)
    resp = api.list_vehicles(ADMIN, params={"host_id": host["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_guest_cannot_create_vehicle(api):
    """PRD §2.1: "When the headers are present but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/guest_cannot_create_vehicle
    """
    host = register_host(api, name="Host FA", email="hfa@x.com")
    guest = register_unverified_guest(api, name="Guest FA", email="gfa@x.com")
    resp = api.create_vehicle(create_vehicle_payload(host["id"]), make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_host_cannot_verify_guest(api):
    """PRD §2.1: "When the headers are present but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/host_cannot_verify_guest
    """
    host = register_host(api, name="Host FB", email="hfb@x.com")
    guest = register_unverified_guest(api, name="Guest FB", email="gfb@x.com")
    gid = guest["id"]
    api.submit_verification(gid, {"license_number": "DL-35", "license_state": "CA",
                                  "license_expiry_date": "2030-01-01"}, make_guest_headers(gid))
    resp = api.verify_guest(gid, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed
    value, is rejected with `ERR_MISSING_AUTH_HEADER`."

    Design: Corner/rbac/missing_auth_header_rejected
    """
    resp = api.list_vehicles(headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER)


def test_host_editing_other_hosts_vehicle_is_ownership_violation(api):
    """PRD §2.1: "An ownership violation — an `entity_backed` principal acting
    on a resource it does not own — is rejected with `ERR_OWNERSHIP_VIOLATION`,
    distinct from a role-level permission failure."

    Design: Corner/validations/ownership_violation_host_edits_others_vehicle
    """
    host1 = register_host(api, name="Host DA1", email="hda1@x.com")
    host2 = register_host(api, name="Host DA2", email="hda2@x.com")
    vehicle = api.create_vehicle(create_vehicle_payload(host1["id"]), make_host_headers(host1["id"]))
    vehicle_id = validate_success(vehicle, expected_status=201)["id"]
    resp = api.update_vehicle(vehicle_id, {"base_daily_price_cents": 20000},
                              make_host_headers(host2["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)
