"""Cross-cutting validation and access control: not-found, required fields, enum constraints,
authentication, and role authorization. PRD §2.1, §2.5, §3.13.
"""
import pytest

from test_helpers import (
    validate_error,
    setup_provider_and_election,
    create_provider,
    set_clock,
    create_election_payload,
    create_care_day_payload,
    make_physician_headers,
    create_medical_director,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_headers"]
CLINICAL = TEST_USERS["clinical_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── Corner: not found ────────────────────────────────────────────────

def test_get_nonexistent_election_returns_404(api):
    """PRD §2.5: "For any request whose path contains multiple identifiers, the server validates
    each segment left-to-right and rejects the first missing identifier with
    ERR_RESOURCE_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_nonexistent_election_returns_404
    """
    res = api.get_election(NON_EXISTENT_UUID, CLINICAL)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


def test_election_with_nonexistent_provider_returns_404(api):
    """PRD §2.5: "The same existence check covers foreign-key references inside request bodies:
    any of Provider, Election, BenefitPeriod, Certification, CarePlan, Physician, or
    BereavementCase named by a path segment or a body field must exist, validated in declaration
    order, before any business rule is evaluated."

    Design: Corner/entities/election_wrong_provider_id_returns_not_found
    """
    set_clock("2026-01-01T00:00:00Z")
    payload = create_election_payload(NON_EXISTENT_UUID, patient_name="NoProv Pt",
                                      election_date="2026-01-01T00:00:00Z",
                                      attending_physician_id="ext-att-np")
    res = api.create_election(payload, INTAKE)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


# ─── Corner: required field / enum constraints ───────────────────────

def test_create_election_missing_patient_name_invalid(api):
    """PRD §3.2: "An IntakeCoordinator elects the hospice benefit for a beneficiary by submitting
    the owning provider_id, the beneficiary's patient_name (which must be non-empty)..."
    PRD §3.13: "The structural request check — required fields present and well-typed, enum
    values within their declared sets, and pagination parameters within bounds
    (ERR_INVALID_REQUEST) — backstops every operation."

    Design: Corner/entities/create_election_missing_patient_name_returns_invalid_request
    """
    provider = create_provider()
    set_clock("2026-01-01T00:00:00Z")
    payload = create_election_payload(provider["id"], election_date="2026-01-01T00:00:00Z",
                                      attending_physician_id="ext-att-mp")
    del payload["patient_name"]
    res = api.create_election(payload, INTAKE)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_care_day_invalid_level_of_care_enum_rejected(api):
    """PRD §3.6: "The level_of_care is one of ROUTINE, RESPITE, or GIP."
    PRD §3.13: "The structural request check — required fields present and well-typed, enum
    values within their declared sets, and pagination parameters within bounds
    (ERR_INVALID_REQUEST) — backstops every operation."

    Design: Corner/entities/careday_invalid_level_of_care_enum_rejected
    """
    provider, election = setup_provider_and_election(election_date="2026-01-02T00:00:00Z",
                                                     clock="2026-01-02T00:00:00Z")
    payload = create_care_day_payload(election["id"], "2026-01-02T00:00:00Z", "HOSPITAL",
                                      high_intensity=False)
    res = api.create_care_day(payload, CLINICAL)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Corner: authentication ───────────────────────────────────────────

def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected
    with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_headers_returns_401
    """
    res = api.list_elections(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Corner: RBAC forbidden operations ───────────────────────────────

def test_intake_coordinator_cannot_post_care_days(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/intake_coordinator_cannot_post_care_days
    """
    provider, election = setup_provider_and_election(election_date="2026-01-02T00:00:00Z",
                                                     clock="2026-01-02T00:00:00Z")
    payload = create_care_day_payload(election["id"], "2026-01-02T00:00:00Z", "GIP",
                                      high_intensity=False)
    res = api.create_care_day(payload, INTAKE)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_clinical_manager_cannot_settle_cap(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/clinical_manager_cannot_settle_cap
    """
    provider = create_provider()
    set_clock("2026-01-02T00:00:00Z")
    res = api.settle_cap(provider["id"], CLINICAL)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_physician_cannot_create_election(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/physician_cannot_create_election
    """
    provider = create_provider()
    md = create_medical_director(full_name="Dr RBAC")
    set_clock("2026-01-01T00:00:00Z")
    payload = create_election_payload(provider["id"], patient_name="Blocked Pt",
                                      election_date="2026-01-01T00:00:00Z",
                                      attending_physician_id="ext-att-rb")
    res = api.create_election(payload, make_physician_headers(md["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")
