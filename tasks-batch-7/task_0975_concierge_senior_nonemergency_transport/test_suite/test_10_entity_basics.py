"""Entity basics: creation defaults, required fields, enum constraints,
not-found, computed snapshots, and the append-only ride log."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_client,
    assert_family_member,
    assert_ride,
    assert_ride_event,
    create_active_rate_card,
    create_active_wav_rate_card,
    create_client,
    create_client_payload,
    create_family_member_payload,
    create_ride_payload,
    get_success_data,
    make_client_headers,
    make_family_member_headers,
    set_clock,
    setup_standard_dispatch_env,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]


def test_client_creation_applies_defaults(api):
    """PRD §3.1: "Registration may also set `billing_hold_limit_cents`, the
    overdue-receivables threshold at or above which new bookings are blocked;
    when omitted it defaults to 20,000 cents. A new client starts `ACTIVE` with
    a `credit_balance_cents` of zero and a `no_show_count` of zero."

    Design: Corner/entities/client_creation_applies_defaults
    """
    client = get_success_data(api_client.create_client(create_client_payload(), COORD))
    assert_client(client)
    assert client["billing_hold_limit_cents"] == 20000, (
        f"omitted hold limit defaults to 20000; got {client['billing_hold_limit_cents']}")
    assert client["status"] == "ACTIVE"
    assert client["credit_balance_cents"] == 0
    assert client["no_show_count"] == 0


def test_client_missing_required_full_name_returns_invalid_request(api):
    """PRD §2.6: "The request body must be valid JSON, declare all required
    fields, and carry well-formed enum and typed values; violations are
    rejected with `ERR_INVALID_REQUEST`."
    PRD §3.1: "A `Coordinator` registers a senior client with their legal
    `full_name`, their `mobility_aid` (one of `NONE`, `WALKER`,
    `FOLDING_WHEELCHAIR`, or `POWER_WHEELCHAIR`), their `assist_level_default`
    escort tier (`DOOR_TO_DOOR` or `DOOR_THROUGH_DOOR`), a `home_zone` label
    used later in driver ranking, and a free-text `address`."

    Design: Corner/entities/client_missing_required_full_name_returns_invalid_request
    """
    payload = create_client_payload()
    del payload["full_name"]
    resp = api_client.create_client(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_family_member_notify_defaults_true(api):
    """PRD §3.1: "The optional `notify_on_ride_events` flag, defaulting to
    true, governs whether ride log events surface in that member's portal
    feed. Memberships start `ACTIVE`"

    Design: Corner/entities/family_member_notify_defaults_true
    """
    client = create_client()
    member = get_success_data(api_client.create_family_member(
        create_family_member_payload(client["id"], access_level="VIEW_ONLY"), COORD))
    assert_family_member(member)
    assert member["notify_on_ride_events"] is True
    assert member["status"] == "ACTIVE"


def test_ride_snapshots_computed_at_creation(api):
    """PRD §3.4: "A created ride snapshots the client's profile: `requires_wav`
    is true exactly when the client's `mobility_aid` is `POWER_WHEELCHAIR`,
    `service_class` is `WAV` exactly when `requires_wav` and `STANDARD`
    otherwise, and `assist_level` copies `assist_level_default`. The
    provisional quote of §3.3 lands in `quoted_fare_cents`"

    Design: Corner/entities/ride_snapshots_computed_at_creation
    """
    create_active_wav_rate_card()
    client = create_client(full_name="Walt W", mobility_aid="POWER_WHEELCHAIR",
                           assist_level_default="DOOR_THROUGH_DOOR", address="9 Oak Ave")
    set_clock("2026-05-20T09:00:00Z")
    ride = get_success_data(api_client.create_ride(
        create_ride_payload(client["id"], kind="APPOINTMENT",
                            scheduled_pickup_at="2026-06-03T10:00:00Z",
                            estimated_duration_minutes=120,
                            estimated_distance_miles=16),
        make_client_headers(client["id"])))
    assert_ride(ride)
    assert ride["requires_wav"] is True
    assert ride["service_class"] == "WAV"
    assert ride["assist_level"] == "DOOR_THROUGH_DOOR"
    # 3600 * 120 / 60 = 7200 hourly; 175 * 16 = 2800 mileage; + 1200 surcharge.
    assert ride["quoted_fare_cents"] == 11200, (
        f"WAV provisional quote 7200 + 2800 + 1200 = 11200; got "
        f"{ride['quoted_fare_cents']}")


def test_ride_computed_field_input_ignored(api):
    """PRD §3.4: "A created ride snapshots the client's profile: `requires_wav`
    is true exactly when the client's `mobility_aid` is `POWER_WHEELCHAIR`"
    PRD §3.4: "The provisional quote of §3.3 lands in `quoted_fare_cents`, the
    ride starts `SCHEDULED` with `dispatch_round` zero and an empty
    `excluded_driver_ids`, and the log opens with a `CREATED` event."

    Design: Corner/entities/ride_computed_field_input_ignored
    """
    create_active_wav_rate_card()
    client = create_client(full_name="Walt W", mobility_aid="POWER_WHEELCHAIR",
                           assist_level_default="DOOR_THROUGH_DOOR", address="9 Oak Ave")
    set_clock("2026-05-20T09:00:00Z")
    payload = create_ride_payload(
        client["id"], kind="APPOINTMENT",
        scheduled_pickup_at="2026-06-03T10:00:00Z",
        estimated_duration_minutes=120, estimated_distance_miles=16)
    payload["requires_wav"] = False
    payload["status"] = "CANCELLED"
    ride = get_success_data(api_client.create_ride(payload, make_client_headers(client["id"])))
    assert ride["requires_wav"] is True, "client-supplied requires_wav=false is ignored"
    assert ride["status"] == "SCHEDULED", "client-supplied status is ignored"


def test_get_ride_not_found_returns_404(api):
    """PRD §2.6: "Path-referenced and body-referenced ids must exist, validated
    left to right; the first missing reference yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_ride_not_found_returns_404
    """
    resp = api_client.get_ride(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_invalid_enum_mobility_aid_returns_invalid_request(api):
    """PRD §2.6: "The request body must be valid JSON, declare all required
    fields, and carry well-formed enum and typed values; violations are
    rejected with `ERR_INVALID_REQUEST`."
    PRD §3.1: "their `mobility_aid` (one of `NONE`, `WALKER`,
    `FOLDING_WHEELCHAIR`, or `POWER_WHEELCHAIR`)"

    Design: Corner/entities/invalid_enum_mobility_aid_returns_invalid_request
    """
    resp = api_client.create_client(
        create_client_payload(mobility_aid="ROCKET_CHAIR"), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_ride_event_log_is_append_only_and_ordered(api):
    """PRD §2.4: "The ride event log is the one exception: a `RideEvent` is an
    immutable ledger entry and carries only `id` and `created_at`. Both
    `updated_at` and `version` are absent from ride events — an event, once
    recorded, is never mutated."
    PRD §3.6: "The portal-facing log reads in `occurred_at` ascending order
    with `created_at` ascending breaking ties"
    PRD §3.5: "the ride log gains `DISPATCHED` and `OFFERED` events."

    Design: Corner/entities/ride_event_log_is_append_only_and_ordered
    """
    client, _ = setup_standard_dispatch_env()
    from test_helpers import create_booked_ride, create_family_member
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    member = create_family_member(client["id"], access_level="VIEW_ONLY")
    resp = api_client.list_ride_events(ride["id"], make_family_member_headers(member["id"]))
    events, _ = validate_paginated(resp)
    types = [e["event_type"] for e in events]
    assert types == ["CREATED", "DISPATCHED", "OFFERED"], (
        f"log opens with CREATED, then DISPATCHED and OFFERED; got {types}")
    occurred = [e["occurred_at"] for e in events]
    assert occurred == sorted(occurred), "occurred_at must be non-decreasing"
    for event in events:
        assert_ride_event(event)
