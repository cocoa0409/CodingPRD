"""Donor/kit registration, custody chain integrity, kit state machine, kit expiry sweep."""
from test_helpers import (
    validate_success,
    validate_error,
    is_valid_uuid,
    is_iso8601_timestamp,
    ApiErrorId,
    COORD_HEADERS,
    assert_custody_event,
    create_donor,
    create_in_stock_kit,
    create_returned_kit,
    set_clock_to,
    run_sweep,
    get_kit,
    make_coordinator_headers,
)


def test_donor_creation_returns_system_fields(api):
    """PRD §3.1: "A `ConsentCoordinator` onboards a donor by registering a
    `donor_reference_code`, an external reference that must be unique across donors.
    A donor's `status` is `ENROLLED` — the sole donor status in this version of the
    system."

    Design: Corner/entities/donor_creation_returns_system_fields
    """
    resp = api.create_donor({"donor_reference_code": "D-ENT1"}, COORD_HEADERS)
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert data["status"] == "ENROLLED"
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"]), "created_at must be set"
    assert data["donor_reference_code"] == "D-ENT1"


def test_collection_kit_missing_kit_type_rejected(api):
    """PRD §2.6: "5. **Request shape** — required fields present, types valid, enum
    values within their declared sets, and `starts_at` strictly before `ends_at`
    wherever a window is supplied; any unknown request field is rejected. All shape
    failures return `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/collection_kit_missing_kit_type_rejected
    """
    resp = api.create_collection_kit({"expires_at": "2027-01-01T00:00:00Z"}, COORD_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_donor_create_unknown_field_rejected(api):
    """PRD §2.6: "5. **Request shape** — required fields present, types valid, enum
    values within their declared sets, and `starts_at` strictly before `ends_at`
    wherever a window is supplied; any unknown request field is rejected. All shape
    failures return `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/donor_create_unknown_field_rejected
    """
    resp = api.create_donor({"donor_reference_code": "D-ENT6", "nickname": "x"}, COORD_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_custody_events_append_only_ordered(api):
    """PRD §3.2: "The chain of custody for a kit is therefore an ordered list of
    custody events, retrievable per kit in `created_at` ascending order. Each event
    carries the `kit_id` it belongs to, an `event_type` of `DISTRIBUTED`, `RETURNED`,
    `CONSUMED`, or `EXPIRED`, the `actor_user_id` of whoever caused it (the literal
    value "system" for sweep-driven expirations), and the free-text `location` and
    `note`, either of which may be null."
    PRD §2.4: "Three resource types are immutable audit records and deviate from this
    pattern: custody events, temperature readings, and review votes carry only `id`
    and `created_at`."

    Design: Corner/entities/custody_events_append_only_ordered
    """
    donor = create_donor("D-ENT8")
    kit = create_in_stock_kit()
    resp = api.distribute_kit(kit["id"], {"donor_id": donor["id"]},
                              make_coordinator_headers("coord-1"))
    validate_success(resp, expected_status=200)
    resp = api.receive_return_kit(kit["id"], {}, make_coordinator_headers("coord-2"))
    validate_success(resp, expected_status=200)
    resp = api.list_custody_events(kit["id"], COORD_HEADERS)
    data = validate_success(resp, expected_status=200)
    assert len(data) == 2, f"expected exactly 2 custody events, got {len(data)}"
    first, second = data[0], data[1]
    assert first["event_type"] == "DISTRIBUTED"
    assert first["actor_user_id"] == "coord-1"
    assert second["event_type"] == "RETURNED"
    assert second["actor_user_id"] == "coord-2"
    for event in data:
        assert_custody_event(event)


def test_kit_distribute_from_returned_rejected(api):
    """PRD §3.2: "The kit must be `IN_STOCK` — any other status fails with
    `ERR_KIT_NOT_DISTRIBUTABLE` (HTTP 409) — and the current time must be strictly
    earlier than the kit's `expires_at`, failing otherwise with `ERR_KIT_EXPIRED`
    (HTTP 409); the state check precedes the expiry check."

    Design: Corner/state_machines/kit_distribute_from_returned_rejected
    """
    donor = create_donor("D-SM1")
    kit = create_returned_kit(donor["id"])
    resp = api.distribute_kit(kit["id"], {"donor_id": donor["id"]}, COORD_HEADERS)
    validate_error(resp, ApiErrorId.ERR_KIT_NOT_DISTRIBUTABLE)
    events_resp = api.list_custody_events(kit["id"], COORD_HEADERS)
    events = validate_success(events_resp, expected_status=200)
    assert len(events) == 2, f"no custody event may be appended by the rejected call: {len(events)}"


def test_kit_expired_by_sweep(api):
    """PRD §2.5: "A kit expires when the current time is at or after its `expires_at`,
    but only while the kit is `IN_STOCK` or `DISTRIBUTED`."
    PRD §3.2: "The sweep of §2.5 expires any kit still `IN_STOCK` or `DISTRIBUTED` once
    the current time reaches its `expires_at`, moving it to `EXPIRED` and appending a
    custody event of type `EXPIRED`."

    Design: Corner/state_machines/kit_expired_by_sweep
    """
    kit = create_in_stock_kit(kit_type="SALIVA", expires_at="2026-05-02T00:00:00Z")
    set_clock_to("2026-05-02T00:00:00Z")  # inclusive boundary: exactly expires_at
    sweep = run_sweep()
    assert sweep["kits_expired"] == 1
    assert get_kit(kit["id"])["status"] == "EXPIRED"
    events = validate_success(api.list_custody_events(kit["id"], COORD_HEADERS))
    expired_events = [e for e in events if e["event_type"] == "EXPIRED"]
    assert len(expired_events) == 1
    assert expired_events[0]["actor_user_id"] == "system"
