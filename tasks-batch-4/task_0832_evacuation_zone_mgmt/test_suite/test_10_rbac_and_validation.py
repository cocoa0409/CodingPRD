"""RBAC denials, authentication, input validation, not-found resolution, and pagination."""
from test_helpers import (
    validate_error, validate_paginated,
    ApiErrorId, NONEXISTENT_UUID,
    create_incident, create_active_incident, create_zone, TEST_USERS,
)

COMMANDER = TEST_USERS["commander_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_registrar_cannot_create_shelter(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD 2.1: "the shelter coordinator owns shelters, staffing, and shelter assignments"

    Design: Corner/rbac/registrar_cannot_create_shelter
    """
    inc = create_incident()
    resp = api.create_shelter(
        {"incident_id": inc["id"], "name": "Rogue", "physical_capacity": 10, "power_backup": True},
        REGISTRAR,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_incident_create_missing_auth_returns_unauthenticated(api):
    """PRD 2.1: "Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400)."

    Design: Corner/rbac/incident_create_missing_auth_returns_unauthenticated
    """
    resp = api.create_incident(
        {"name": "Ridge Fire", "jurisdiction": "Butte", "hazard_type": "WILDFIRE"},
        {},  # no X-User-ID / X-User-Role
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT)


def test_incident_create_invalid_enum_hazard_type_rejected(api):
    """PRD 2.9: "`ERR_INVALID_ENUM` (HTTP 422) covers an enum field carrying a non-member value and covers a `channels` array that is empty or contains an unrecognized channel."
    PRD 3.1: "the `hazard_type` driving the evacuation — one of `WILDFIRE`, `FLOOD`, `HURRICANE`, `HAZMAT`, or `TSUNAMI`."

    Design: Corner/entities/incident_create_invalid_enum_hazard_type_rejected
    """
    resp = api.create_incident(
        {"name": "Bad", "jurisdiction": "X", "hazard_type": "EARTHQUAKE"},
        COMMANDER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_registrant_create_missing_required_party_size_returns_validation(api):
    """PRD 3.3: "A `Registrar` enrolls a household into a zone by supplying the `zone_id`, a `household_name`, and the `party_size` (at least 1 person)."
    PRD 2.9: "`ERR_VALIDATION` (HTTP 400) covers a missing required field or a value that violates its declared type or numeric range"

    Design: Corner/entities/registrant_create_missing_required_party_size_returns_validation
    """
    inc = create_incident()
    zone = create_zone(inc["id"])
    resp = api.create_registrant(
        {"zone_id": zone["id"], "household_name": "Alvarez"},  # party_size omitted
        REGISTRAR,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_zone_get_nonexistent_returns_not_found(api):
    """PRD 2.9: "then existence of every resource named in the URL path — validated left to right so that a parent id is resolved before a child id and the earliest missing segment determines which `ERR_..._NOT_FOUND` is returned"

    Design: Corner/entities/zone_get_nonexistent_returns_not_found
    """
    resp = api.get_zone(NONEXISTENT_UUID, COMMANDER)
    validate_error(resp, ApiErrorId.ERR_ZONE_NOT_FOUND)


def test_zone_create_incident_fk_not_found(api):
    """PRD 2.9: "then existence of every foreign key referenced in the request body (again the matching `ERR_..._NOT_FOUND`)"

    Design: Corner/endpoints/zone_create_incident_fk_not_found
    """
    resp = api.create_zone(
        {"incident_id": NONEXISTENT_UUID, "name": "Zone-1",
         "geofence_wkt": "POLYGON((0 0,0 1,1 1,1 0,0 0))", "residential_population": 100},
        COMMANDER,
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_FOUND)


def test_zones_list_pagination_envelope(api):
    """PRD 2.3: "Each list response includes `limit`, `offset`, `total_count` (the number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page) in the `meta` object."

    Design: Corner/endpoints/zones_list_pagination_envelope
    """
    inc = create_active_incident()
    create_zone(inc["id"], name="Zone-1")
    create_zone(inc["id"], name="Zone-2", geofence_wkt="POLYGON((2 2,2 3,3 3,3 2,2 2))")

    data, meta = validate_paginated(
        api.list_zones(COMMANDER, params={"incident_id": inc["id"], "limit": 1})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
