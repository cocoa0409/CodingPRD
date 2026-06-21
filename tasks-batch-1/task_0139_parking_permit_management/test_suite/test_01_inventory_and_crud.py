"""Inventory CRUD and entity contract: garage/zone/rate-plan/motorist creation,
defaults, system fields, not-found, required-field and enum validation, FK
integrity, PlateRead immutability, listing/pagination, and garage PATCH.

PRD §3.1/§3.2/§3.3 govern entity creation; §2.3 pagination; §2.4 common properties;
§2.5 referential existence; §2.9 well-formedness.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    setup_garage_with_zone,
    create_garage,
    create_rate_plan,
    create_zone,
    create_plate_read,
    assert_plate_read,
    create_garage_payload,
    create_zone_payload,
    create_rate_plan_payload,
    create_motorist_payload,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


def test_create_garage_returns_201_with_defaults(api):
    """PRD §3.1: "The garage optionally takes a `timezone` — an IANA timezone name
    used purely for display, defaulting to `UTC` when omitted — and a `gate_mode`,
    which controls entry admission policy and defaults to `PERMIT_OR_TRANSIENT`."
    PRD §3.1: "The garage's `total_space_count` and `occupied_count` are computed
    fields that begin at zero".

    Design: Corner/entities/create_garage_returns_201_with_defaults
    """
    resp = api.create_garage(create_garage_payload(name="Downtown"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["gate_mode"] == "PERMIT_OR_TRANSIENT"
    assert data["timezone"] == "UTC"
    assert data["occupied_count"] == 0
    assert data["total_space_count"] == 0
    assert data["version"] == 1


def test_get_nonexistent_garage_returns_not_found(api):
    """PRD §2.5: "the system validates each identifier left to right and rejects the
    first one that does not resolve to an existing resource with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_garage_nonexistent_returns_not_found
    """
    resp = api.get_garage(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_zone_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "Any request whose body is malformed, omits a required field, or
    supplies an invalid enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400)
    as a baseline well-formedness check."

    Omitting permit_capacity (a required zone field) → 400.

    Design: Corner/entities/create_zone_missing_required_field_returns_invalid_request
    """
    garage = create_garage(name="G")
    rate_plan = create_rate_plan(name="RP")
    payload = {"garage_id": garage["id"], "code": "Z", "zone_type": "MIXED",
               "rate_plan_id": rate_plan["id"]}  # permit_capacity omitted
    resp = api.create_zone(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_zone_invalid_enum_zone_type_returns_invalid_request(api):
    """PRD §2.9: "Any request whose body is malformed, omits a required field, or
    supplies an invalid enum value is rejected with `ERR_INVALID_REQUEST`".
    PRD §3.1: "The `zone_type` is one of `TRANSIENT`, `PERMIT`, or `MIXED`".

    Design: Corner/entities/create_zone_invalid_enum_zone_type_returns_invalid_request
    """
    garage = create_garage(name="G")
    rate_plan = create_rate_plan(name="RP")
    resp = api.create_zone(
        create_zone_payload(garage["id"], rate_plan["id"], code="Z",
                            zone_type="VIP", permit_capacity=5), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_rate_plan_grace_minutes_default_applied(api):
    """PRD §3.2: "an optional `grace_minutes` free-leading-minutes allowance that
    defaults to fifteen minutes."

    Design: Corner/entities/rate_plan_grace_minutes_default_applied
    """
    data = validate_success(
        api.create_rate_plan(
            create_rate_plan_payload(name="RP", hourly_cents=500, daily_cap_cents=4000,
                                     monthly_permit_cents=9000), ADMIN),
        expected_status=201)
    assert data["grace_minutes"] == 15


def test_motorist_system_fields_generated(api):
    """PRD §2.4: "Most resources additionally carry two system-managed fields:
    `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and
    `version`, an integer that begins at its initial value and increments by one on
    every mutation."
    PRD §3.3: "A motorist also carries a computed `outstanding_balance_cents` that
    begins at zero and tracks unpaid fines as described in §3.9."

    Design: Corner/entities/motorist_system_fields_generated_input_ignored
    """
    data = validate_success(
        api.create_motorist(create_motorist_payload("sys@x.com", default_plate="SYS111"), ADMIN),
        expected_status=201)
    assert data["version"] == 1
    assert data["outstanding_balance_cents"] == 0


def test_plate_read_is_immutable_no_version_field(api):
    """PRD §2.4: "`PlateRead` is the sole exception: an LPR read is immutable once
    recorded, so a `PlateRead` carries only `id` and `created_at`. It has no
    `updated_at` field and no `version` field."

    Design: Corner/entities/plate_read_is_immutable_no_version_field
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    read = create_plate_read(garage["id"], "IMM111", zone["id"], "2026-06-01T08:00:00Z")
    fetched = validate_success(api.get_plate_read(read["id"], OFFICER))
    assert_plate_read(fetched)
    assert fetched["enforcement_outcome"] == "VIOLATION_NO_PERMIT"


def test_create_zone_with_nonexistent_garage_returns_not_found(api):
    """PRD §2.5: "The same existence check governs foreign keys supplied in the
    request body: after path identifiers are confirmed, each referenced body
    identifier is validated, and a dangling reference is rejected with
    `ERR_NOT_FOUND`."

    Design: Corner/entities/zone_garage_id_wrong_parent_returns_not_found
    """
    rate_plan = create_rate_plan(name="RP")
    resp = api.create_zone(
        create_zone_payload(NON_EXISTENT_UUID, rate_plan["id"], code="Z",
                            zone_type="MIXED", permit_capacity=5), ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_event_window_end_before_start_rejected(api):
    """PRD §3.2: "creation requires `window_end_utc` to fall strictly after
    `window_start_utc`, and a window that does not satisfy this is rejected with
    `ERR_EVENT_WINDOW_OVERLAP`."

    Design: Corner/validations/event_window_end_before_start_returns_overlap_error
    """
    garage = create_garage(name="G")
    resp = api.create_event_pricing(
        {"garage_id": garage["id"], "name": "Bad",
         "window_start_utc": "2026-06-01T18:00:00Z", "window_end_utc": "2026-06-01T12:00:00Z",
         "flat_surcharge_cents": 1000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP.value)


def test_list_zones_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Two zones, limit=1 → total_count 2 and has_more true.

    Design: Corner/endpoints/list_zones_pagination_envelope
    """
    garage = create_garage(name="G")
    rate_plan = create_rate_plan(name="RP")
    create_zone(garage["id"], rate_plan["id"], code="A", zone_type="MIXED", permit_capacity=5)
    create_zone(garage["id"], rate_plan["id"], code="B", zone_type="TRANSIENT", permit_capacity=0)
    resp = api.list_garage_zones(garage["id"], ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_pagination_limit_out_of_bounds_returns_error(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or an `offset` below 0, is rejected
    with `ERR_PAGINATION_INVALID`."

    Design: Corner/endpoints/pagination_limit_out_of_bounds_returns_error
    """
    garage = create_garage(name="G")
    resp = api.list_garage_zones(garage["id"], ADMIN, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)


def test_patch_garage_gate_mode_updates_field_and_bumps_version(api):
    """PRD §3.1: "The `gate_mode` may later be changed by updating the garage, which
    takes effect for subsequent entry attempts".
    PRD §2.4: "`version`, an integer that begins at its initial value and increments
    by one on every mutation."

    Design: Corner/endpoints/patch_garage_gate_mode_updates_field
    """
    garage = create_garage(name="G")
    data = validate_success(api.update_garage(garage["id"], {"gate_mode": "CLOSED"}, ADMIN))
    assert data["gate_mode"] == "CLOSED"
    assert data["version"] == 2
