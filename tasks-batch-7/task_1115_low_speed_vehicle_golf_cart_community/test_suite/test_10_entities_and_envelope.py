"""Entity-level claims: community defaults, required fields, computed fields,
type constraints, 404s, server-minted system fields, and the pagination
envelope (PRD §2.2, §2.3, §2.5, §3.1, §3.2, §3.3).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    make_permit_holder_headers,
    create_community, create_holder, create_eligible_holder,
    create_vehicle, create_draft_registration,
    create_community_payload, create_permit_holder_payload,
    create_vehicle_payload,
    COMMUNITY_ADMIN, ANON, ADMIN,
    ApiErrorId, NON_EXISTENT_UUID,
)


def test_create_community_applies_defaults():
    """PRD §3.1: "Six optional parameters tune the ordinance and each carries a
    default applied when omitted: `min_driver_age` is the minimum driver age in
    whole years (an integer from 12 to 25, default 16); `insurance_required`
    decides whether an `ACTIVE` insurance policy is required to activate or
    reinstate a registration (default true); `fleet_program_enabled` decides
    whether the shared fleet option is offered, and also gates the fleet-discount
    assumption inside provisional fee quotes (default false);
    `min_liability_coverage_cents` is the minimum liability coverage an insurance
    policy must document (default 10000000 cents); `renewal_window_days` sets how
    many days before expiry a renewal opens, with the opening boundary inclusive
    (default 60); and `late_grace_days` sets how many days after expiry a late
    renewal remains possible, again with an inclusive boundary (default 90). A
    freshly created community also carries a computed `checked_out_count` starting
    at zero, tracking how many of its fleet vehicles are currently checked out."
    PRD §2.5: "`version` (integer): a system-managed integer that starts at 1 on
    creation and increments by 1 with every mutation of the resource."

    Design: Corner/entities/create_community_applies_defaults
    """
    community = validate_success(
        api_client.create_community(create_community_payload(name="C-DEF"),
                                    ADMIN), 201)
    assert community["min_driver_age"] == 16
    assert community["insurance_required"] is True
    assert community["fleet_program_enabled"] is False
    assert community["min_liability_coverage_cents"] == 10000000
    assert community["renewal_window_days"] == 60
    assert community["late_grace_days"] == 90
    assert community["checked_out_count"] == 0
    assert community["version"] == 1


def test_create_permit_holder_missing_required_birth_date():
    """PRD §2.6: "**Request-body schema** — all required fields are present, enum
    values are in range, integers fall within their declared ranges, and on every
    windowed payload the window end is strictly after its start. Failure:
    `ERR_VALIDATION` (HTTP 400)."
    PRD §3.2: "A resident joins the program through self-registration — open to
    `Anonymous` callers, and also available to a `CommunityAdmin` registering on
    someone's behalf — by supplying the `community_id` of their community, their
    legal `full_name`, their `birth_date` as an ISO 8601 date, and their
    `driver_license_class`, one of `NONE`, `STANDARD`, or `MOTORCYCLE`."

    Design: Corner/entities/create_permit_holder_missing_required_birth_date
    """
    community = create_community(name="C-REQ")
    payload = {
        "community_id": community["id"],
        "full_name": "H REQ",
        "driver_license_class": "STANDARD",
    }
    res = api_client.create_permit_holder(payload, ANON)
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_vehicle_computed_equipment_count_excludes_zero_mirrors():
    """PRD §3.3: "From this declaration the system computes `equipment_count`: the
    number of the seven boolean flags that are true, plus one more when at least
    one mirror is installed, yielding a value from 0 to 8."
    PRD §3.3: "a `mirror_count` from 0 to 4, where zero means the vehicle has no
    mirrors at all."

    Design: Corner/entities/vehicle_computed_equipment_count_excludes_zero_mirrors
    """
    community = create_community(name="C-EC")
    holder = create_eligible_holder(community["id"], full_name="H EC",
                                    birth_date="2010-05-01")
    v0 = create_vehicle(holder["id"], vehicle_type="GOLF_CART", seat_count=4,
                        has_headlights=True, has_brake_lights=True,
                        has_turn_signals=True, has_horn=True, has_windshield=True,
                        has_seatbelts=True, has_reflectors=True, mirror_count=0)
    v2 = create_vehicle(holder["id"], vehicle_type="GOLF_CART", seat_count=4,
                        has_headlights=True, has_brake_lights=True,
                        has_turn_signals=True, has_horn=True, has_windshield=True,
                        has_seatbelts=True, has_reflectors=True, mirror_count=2)
    assert v0["equipment_count"] == 7  # mirror_count 0 -> mirrors item absent
    assert v2["equipment_count"] == 8


def test_vehicle_invalid_enum_rejected():
    """PRD §2.6: "**Request-body schema** — all required fields are present, enum
    values are in range, integers fall within their declared ranges, and on every
    windowed payload the window end is strictly after its start. Failure:
    `ERR_VALIDATION` (HTTP 400)."
    PRD §3.3: "A holder registers a vehicle by declaring its `holder_id`, its
    `vehicle_type` — `GOLF_CART` or `LSV` — its `seat_count` (from 1 to 8), seven
    boolean equipment flags (`has_headlights`, `has_brake_lights`,
    `has_turn_signals`, `has_horn`, `has_windshield`, `has_seatbelts`,
    `has_reflectors`), and a `mirror_count` from 0 to 4, where zero means the
    vehicle has no mirrors at all."

    Design: Corner/entities/vehicle_invalid_enum_rejected
    """
    community = create_community(name="C-EN")
    holder = create_eligible_holder(community["id"], full_name="H EN",
                                    birth_date="2010-05-01")
    payload = create_vehicle_payload(holder["id"], vehicle_type="TRUCK",
                                     seat_count=4, mirror_count=1)
    res = api_client.create_vehicle(payload, make_permit_holder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_get_vehicle_not_found_returns_404(community_admin_headers):
    """PRD §2.6: "**Existence** — every identifier referenced in the path and body
    exists. Identifiers are validated left to right: path parameters first, then
    body foreign keys in their declared field order. Failure: `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_vehicle_not_found_returns_404
    """
    create_community(name="C-NF")
    res = api_client.get_vehicle(NON_EXISTENT_UUID, community_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_system_fields_server_minted_on_create():
    """PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as a
    UUID, with no type prefix."
    PRD §2.5: "`version` (integer): a system-managed integer that starts at 1 on
    creation and increments by 1 with every mutation of the resource."
    PRD §2.4: "Every rule in this document that speaks of \"now\", \"today\", an
    age, a trailing window, or an overdue duration refers to a server-side
    **logical clock**, never the host wall clock. At server startup the logical
    clock reads exactly 2026-05-01T00:00:00Z."
    PRD §3.2: "The new holder starts with `eligibility_status`
    `PENDING_VERIFICATION`, `compliance_status` `GOOD_STANDING`, a `points_balance`
    of zero, and an empty `wallet_balance_cents`."

    Design: Corner/entities/system_fields_server_minted_on_create
    """
    community = create_community(name="C-SYS")
    holder = validate_success(api_client.create_permit_holder(
        create_permit_holder_payload(community["id"], full_name="H SYS",
                                     birth_date="2010-05-01"), ANON), 201)
    assert is_valid_uuid(holder["id"])
    assert "_" not in holder["id"], "id carries no type prefix"
    assert holder["version"] == 1
    # PRD §2.5: created_at is "an ISO 8601 UTC timestamp with three fractional
    # digits"; §2.4 pins the startup instant to exactly 2026-05-01T00:00:00Z.
    assert holder["created_at"] == "2026-05-01T00:00:00.000Z"
    assert holder["points_balance"] == 0
    assert holder["eligibility_status"] == "PENDING_VERIFICATION"
    assert holder["compliance_status"] == "GOOD_STANDING"
    assert holder["wallet_balance_cents"] == 0


def test_list_registrations_pagination_envelope(community_admin_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return; if not provided it defaults to 10, with a minimum of 1 and a maximum
    of 100. The `offset` parameter specifies the number of items to skip and
    defaults to 0. Unless otherwise specified, all list endpoints return resources
    sorted by their creation timestamp in ascending order. Paginated list responses
    include the following fields in the `meta` object of the response envelope:
    `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/list_registrations_pagination_envelope
    """
    community = create_community(name="C-PG")
    holder = create_eligible_holder(community["id"], full_name="H PG",
                                    birth_date="2010-05-01")
    v1 = create_vehicle(holder["id"])
    v2 = create_vehicle(holder["id"])
    create_draft_registration(v1["id"], holder["id"], registration_year=2026)
    create_draft_registration(v2["id"], holder["id"], registration_year=2026)

    res1 = api_client.list_registrations(
        community_admin_headers, params={"holder_id": holder["id"],
                                         "limit": 1, "offset": 0})
    data1, meta1 = validate_paginated(res1)
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert len(data1) == 1

    res2 = api_client.list_registrations(
        community_admin_headers, params={"holder_id": holder["id"],
                                         "limit": 1, "offset": 1})
    data2, meta2 = validate_paginated(res2)
    assert meta2["has_more"] is False
    assert len(data2) == 1
    assert data1[0]["id"] != data2[0]["id"]

    body = res1.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
