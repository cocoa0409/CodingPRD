"""CRUD basics, resource defaults, listing, and access control."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_beach_payload, create_zone_payload, create_advisory_payload,
    assert_beach, assert_zone,
    make_headers,
    TEST_USERS,
    new_beach, new_zone, setup_beach_zone,
)

CAPTAIN = TEST_USERS["beach_captain_headers"]
PUBLIC = TEST_USERS["public_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
CLERK = TEST_USERS["parking_clerk_headers"]
NON_EXISTENT_ZONE = "00000000-0000-4000-8000-000000000000"


def test_beach_create_returns_201_and_echoes_fields(api):
    """PRD §4: "Operations that create a new, stand-alone resource return `201 Created`."
    PRD §3.1: "A `BeachCaptain` establishes a `Beach` by supplying its `name`, the owning
    municipality's `town_code`, and the inclusive season boundaries `season_start_date` and
    `season_end_date`, each written as `YYYY-MM-DD`."
    PRD §2.4: "`version` is an integer that starts at its initial value on creation and
    increments by one on every mutation of the resource; it underpins optimistic concurrency"

    Design: Corner/entities/corner_beach_create_returns_201_with_fields
    """
    resp = api.create_beach(create_beach_payload(name="Ocean Park"), CAPTAIN)
    data = validate_success(resp, 201)
    assert_beach(data)
    assert data["name"] == "Ocean Park", f"expected name echoed, got {data['name']}"
    assert data["version"] == 1, f"fresh beach version must be 1, got {data['version']}"


def test_beach_missing_town_code_rejected(api):
    """PRD §2.5: "After existence, the body must parse and every required field must be
    present with a valid enum or numeric type, or the request fails with `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/corner_beach_missing_town_code_returns_invalid_request
    """
    payload = create_beach_payload()
    payload.pop("town_code")
    resp = api.create_beach(payload, CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_zone_returns_not_found(api):
    """PRD §2.5: "the first one that does not resolve yields `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/entities/corner_zone_get_nonexistent_returns_not_found
    """
    resp = api.get_zone(NON_EXISTENT_ZONE, PUBLIC)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_zone_defaults_on_create(api):
    """PRD §3.1: "A freshly created zone opens in a fixed posture: its `flag_status` is
    `RED`, its `water_status` is `OPEN`, its `rip_current_level` is `LOW`, and its
    `on_duty_guard_count` is 0."

    Design: Corner/entities/corner_zone_defaults_on_create
    """
    beach = new_beach(api)
    resp = api.create_zone(create_zone_payload(beach["id"]), CAPTAIN)
    data = validate_success(resp, 201)
    assert_zone(data)
    assert data["flag_status"] == "RED"
    assert data["water_status"] == "OPEN"
    assert data["rip_current_level"] == "LOW"
    assert data["on_duty_guard_count"] == 0


def test_water_quality_sample_has_no_version_field(api):
    """PRD §2.4: "A `WaterQualitySample` is an append-only, immutable event record: it
    carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because
    once recorded a sample is never changed."

    Design: Corner/entities/corner_sample_immutable_common_fields_false
    """
    beach, zone = setup_beach_zone(api)
    resp = api.create_sample(
        {"zone_id": zone["id"], "enterococci_mpn": 20, "sampled_at": "2026-07-15T08:00:00Z",
         "lab_ref": "L1", "technician": "T"},
        INSPECTOR,
    )
    data = validate_success(resp, 201)
    assert "id" in data and "created_at" in data
    assert "version" not in data, "immutable sample must not carry a version field"
    assert "updated_at" not in data, "immutable sample must not carry an updated_at field"


def test_beach_immediately_readable_after_create(api):
    """PRD §2.7: "Several fields are never written directly by clients; the server recomputes
    them from underlying rows the moment a triggering event occurs, and the system's
    consistency model is immediate."
    PRD §2.2: "operations that create or modify a resource will return the created or updated
    resource object in the data field."

    Design: Corner/consistency_model/corner_immediate_visibility_beach_create_then_get
    """
    beach = new_beach(api, name="Ocean Park")
    resp = api.get_beach(beach["id"], PUBLIC)
    data = validate_success(resp, 200)
    assert data["name"] == "Ocean Park", f"GET must reflect the created beach, got {data['name']}"


def test_zones_listable_filtered_by_beach(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."
    PRD §4: "GET | `/beach-ops/zones` | List zones (filterable by beach) | All roles"

    Design: Corner/endpoints/corner_zones_filtered_by_beach_reverse_fk
    """
    beach, zone = setup_beach_zone(api)
    resp = api.list_zones(PUBLIC, params={"beach_id": beach["id"]})
    data, meta = validate_paginated(resp)
    ids = [z["id"] for z in data]
    assert zone["id"] in ids, "filtered listing must contain the beach's zone"
    assert "total_count" in meta and "has_more" in meta


def test_lifeguard_cannot_create_zone(api):
    """PRD §2.1: "When a recognized role attempts an operation its role is not permitted to
    perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `BeachCaptain` owns beach, zone, tower, lifeguard, and shift-scheduling
    administration, may cancel shifts and create parking lots, and may drive the logical clock."

    Design: Corner/rbac/corner_lifeguard_cannot_create_zone_unauthorized
    """
    beach = new_beach(api)
    lifeguard_headers = make_headers("Lifeguard", "someone")
    resp = api.create_zone(create_zone_payload(beach["id"]), lifeguard_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_parking_clerk_cannot_issue_advisory(api):
    """PRD §2.1: "When a recognized role attempts an operation its role is not permitted to
    perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `WaterQualityInspector` records bacteria samples, issues advisories, and
    lifts them."

    Design: Corner/rbac/corner_parkingclerk_cannot_issue_advisory_unauthorized
    """
    beach, zone = setup_beach_zone(api, clock="2026-07-15T09:00:00Z")
    resp = api.create_advisory(
        zone["id"], create_advisory_payload("SINGLE_SAMPLE", zone["version"]), CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/corner_unknown_role_returns_unauthenticated
    """
    intruder = make_headers("Intruder", "x")
    resp = api.create_beach(create_beach_payload(), intruder)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_season_end_before_start_rejected(api):
    """PRD §3.1: "The season close must fall strictly after the season open; a
    `season_end_date` that is not later than `season_start_date` is rejected with
    `ERR_SEASON_DATES_INVALID` (422)."

    Design: Corner/validations/corner_season_dates_invalid_end_before_start
    """
    payload = create_beach_payload(season_start_date="2026-09-07", season_end_date="2026-05-23")
    resp = api.create_beach(payload, CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_SEASON_DATES_INVALID.value)
