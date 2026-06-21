"""Resource creation, validation, listing, and role-based access control.

Covers election/precinct creation envelopes, body-shape validation
(ERR_INVALID_REQUEST), not-found existence checks, pagination metadata, and the
RBAC rejections (unauthenticated / unauthorized).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    fixtures,
    factories,
    MISSING_UUID,
    build_user_headers,
)
from test_helpers.test_users import ADMIN, OFF1, PW1

ERR = ApiErrorId


# ---------------------------------------------------------------------------
# Creation envelope + system fields (Corner: entities)
# ---------------------------------------------------------------------------
def test_create_election_returns_201_with_system_fields(api):
    """PRD §3.1: "A new election begins with its status field set to SCHEDULED."
    PRD §2.4: "and a version integer that begins at its initial value and
    increments by one on every mutation."

    Design: Corner/entities/create_election_returns_201_with_system_fields
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    data = validate_success(api.create_election(factories.create_election_payload(), ADMIN), 201)
    assert data["status"] == "SCHEDULED"
    assert data["version"] == 1
    assert data["total_registered"] == 0


def test_get_election_not_found_returns_404(api):
    """PRD §2.6: "The first reference that does not resolve to an existing resource
    causes the request to be rejected with ERR_NOT_FOUND, before any state,
    eligibility, or capacity logic runs."

    Design: Corner/entities/get_election_not_found_returns_404
    """
    resp = api.get_election(MISSING_UUID, ADMIN)
    validate_error(resp, ERR.ERR_NOT_FOUND.value)


def test_create_precinct_missing_max_registrations_invalid_request(api):
    """PRD §2.9: "generic body-shape validation (ERR_INVALID_REQUEST) — required
    fields present, enum values in range, and numeric constraints such as
    max_registrations being at least 1 and street_high being at least street_low."

    Design: Corner/entities/create_precinct_missing_required_field_returns_invalid_request
    """
    election = fixtures.create_election()
    payload = factories.create_precinct_payload(election["id"])
    payload.pop("max_registrations")
    validate_error(api.create_precinct(payload, ADMIN), ERR.ERR_INVALID_REQUEST.value)


def test_create_precinct_max_registrations_below_one_invalid_request(api):
    """PRD §3.1: "The cap must be at least 1, and street_high must be at least
    street_low; violating either yields ERR_INVALID_REQUEST."

    Design: Corner/entities/create_precinct_max_registrations_below_one_returns_invalid_request
    """
    election = fixtures.create_election()
    payload = factories.create_precinct_payload(election["id"], max_registrations=0)
    validate_error(api.create_precinct(payload, ADMIN), ERR.ERR_INVALID_REQUEST.value)


def test_list_precincts_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields limit, offset,
    total_count, and has_more inside the meta object of the envelope."

    Design: Corner/entities/list_precincts_pagination_envelope
    """
    election = fixtures.create_election()
    fixtures.create_precinct(election["id"], code="P1", street_low=1, street_high=999)
    fixtures.create_precinct(election["id"], code="P2", street_low=1000, street_high=1999)
    resp = api.list_precincts(ADMIN, params={"election_id": election["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, "limit=1 returns a single item"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ---------------------------------------------------------------------------
# RBAC (Corner: rbac)
# ---------------------------------------------------------------------------
def test_voter_cannot_approve_registration(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/voter_cannot_approve_registration
    """
    election, precinct = fixtures.setup_election_with_precinct("REGISTRATION_OPEN")
    reg = fixtures.create_registration(election["id"])
    voter_headers = build_user_headers(reg["id"], "Voter")
    resp = api.approve_registration(reg["id"], voter_headers)
    validate_error(resp, ERR.ERR_UNAUTHORIZED.value)
    after = validate_success(api.get_registration(reg["id"], OFF1), 200)
    assert after["status"] == "PENDING"


def test_pollworker_cannot_create_precinct(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."

    Design: Corner/rbac/pollworker_cannot_create_precinct
    """
    election = fixtures.create_election()
    payload = factories.create_precinct_payload(election["id"])
    resp = api.create_precinct(payload, PW1)
    validate_error(resp, ERR.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing or malformed in either header is rejected with
    ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    fixtures.create_election()
    resp = api.list_elections(headers={"Content-Type": "application/json"})
    validate_error(resp, ERR.ERR_UNAUTHENTICATED.value)
