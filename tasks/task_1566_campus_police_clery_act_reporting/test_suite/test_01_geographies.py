"""Geography registry tests: defaults, enum constraints, updates, listing (PRD §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_geography, create_geography_payload, create_submitted_incident,
    ApiErrorId, assert_geography, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
CHIEF = TEST_USERS["chief_headers"]


def test_create_geography_applies_defaults(api):
    """PRD §3.1: "A `SystemAdmin` registers each zone with a `name`, a `category`
    drawn from `ON_CAMPUS`, `ON_CAMPUS_RESIDENTIAL`, `NON_CAMPUS`, or
    `PUBLIC_PROPERTY`, and an `is_residential_facility` flag (defaulting to false)
    that is true only for on-campus student housing facilities and is a
    precondition for reporting a fire against that zone. New geographies are
    born `ACTIVE` and carry a `status` that later moves to `RETIRED`."
    PRD §2.5: "an integer `version` that increments by one on every mutation."

    Design: Corner/entities/create_clery_geography_applies_defaults
    """
    created = validate_success(api.create_geography(
        {"name": "North Campus", "category": "ON_CAMPUS"}, ADMIN
    ), 201)
    assert_geography(created)
    geography = validate_success(api.get_geography(created["id"], ADMIN), 200)
    assert geography["is_residential_facility"] is False, (
        "is_residential_facility must default to false when omitted"
    )
    assert geography["status"] == "ACTIVE"
    assert geography["version"] == 1


def test_create_geography_with_invalid_enum(api):
    """PRD §2.8: "Enum fields accept only their declared members ... Violations
    of these field-level constraints are rejected with `ERR_VALIDATION_FAILED`
    (HTTP 422)."

    Design: Corner/entities/create_geography_with_invalid_enum
    """
    res = api.create_geography({"name": "Downtown", "category": "DOWNTOWN"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value, expected_status=422)


def test_patch_geography_increments_version(api):
    """PRD §2.5: "an integer `version` that increments by one on every mutation"
    and "`updated_at` timestamp of the same format refreshed on every mutation".

    Design: Corner/entities/patch_geography_increments_version
    """
    created = validate_success(api.create_geography(
        create_geography_payload(name="Old Name", category="NON_CAMPUS"), ADMIN
    ), 201)
    assert created["version"] == 1

    updated = validate_success(api.update_geography(
        created["id"], {"name": "New Name"}, ADMIN
    ), 200)
    assert updated["version"] == 2, (
        f"PATCH must bump version 1 -> 2, got {updated['version']}"
    )
    assert updated["updated_at"] >= updated["created_at"]
    assert updated["name"] == "New Name"


def test_list_geographies_pagination_envelope(api):
    """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."
    PRD §2.3: "The default `limit` is 10 ... The default `offset` is 0."

    Design: Corner/entities/list_endpoint_pagination_envelope
    """
    api.create_geography(create_geography_payload(name="G1", category="ON_CAMPUS"), ADMIN)
    api.create_geography(create_geography_payload(name="G2", category="NON_CAMPUS"), ADMIN)

    data, meta = validate_paginated(api.list_geographies(ADMIN))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(data) == 2


def test_retire_geography_in_use_blocked(api):
    """PRD §3.1: "a geography cannot be retired while any non-terminal incident
    report (any incident not in `UNFOUNDED` or `WITHDRAWN`) or any fire incident
    still references it; such an update is rejected with `ERR_GEOGRAPHY_IN_USE`
    (HTTP 409)."

    Design: Corner/validations/retire_geography_in_use_blocked
    """
    geography = create_geography(name="Busy", category="ON_CAMPUS")
    incident = create_submitted_incident(
        geography["id"], reported_at="2026-04-09T09:00:00Z",
        occurred_at="2026-04-09T08:00:00Z",
    )
    res = api.update_geography(geography["id"], {"status": "RETIRED"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_GEOGRAPHY_IN_USE.value, expected_status=409)

    geography_after = validate_success(api.get_geography(geography["id"], ADMIN), 200)
    assert geography_after["status"] == "ACTIVE", (
        "Geography referenced by a non-terminal incident must remain ACTIVE"
    )


def test_retired_geography_rejected_on_incident_create(api):
    """PRD §3.1: "any operation that references a geography — incident creation,
    incident classification, referral creation, or fire-incident creation —
    requires the geography's `status` to be `ACTIVE` and is rejected with
    `ERR_GEOGRAPHY_RETIRED` (HTTP 422) otherwise."

    Design: Corner/validations/retired_geography_rejected_on_incident_create
    """
    geography = create_geography(name="Retired Lot", category="NON_CAMPUS")
    validate_success(api.update_geography(geography["id"], {"status": "RETIRED"}, ADMIN), 200)

    res = api.create_incident(
        {
            "reported_at": "2026-04-10T09:00:00Z",
            "occurred_at": "2026-04-10T08:00:00Z",
            "geography_id": geography["id"],
            "source": "POLICE_DIRECT",
            "narrative": "x",
        },
        CHIEF,
    )
    validate_error(res, ApiErrorId.ERR_GEOGRAPHY_RETIRED.value, expected_status=422)
