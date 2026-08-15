"""Authentication and role-based access control tests (PRD §2.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_geography, create_active_csa, create_under_classification_incident,
    create_classify_payload, create_offense_count_payload,
    build_user_headers, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
CHIEF = TEST_USERS["chief_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized
    role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unknown_role_returns_unauthenticated
    """
    bogus_headers = build_user_headers("test-superuser-1", "SuperUser")
    res = api.create_geography({"name": "X", "category": "ON_CAMPUS"}, bogus_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_anonymous_cannot_create_incident(api):
    """PRD §2.1: "A request whose role is not listed for the endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: incident creation lists only `CleryCoordinator` and `PoliceChief`;
    `Anonymous` — "an unauthenticated-equivalent public role for crime log
    transparency" — is not listed.

    Design: Corner/rbac/anonymous_cannot_create_incident
    """
    geography = create_geography(name="O", category="ON_CAMPUS")
    res = api.create_incident(
        {
            "reported_at": "2026-04-12T09:00:00Z",
            "occurred_at": "2026-04-12T08:00:00Z",
            "geography_id": geography["id"],
            "source": "POLICE_DIRECT",
            "narrative": "x",
        },
        ANON,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_csa_cannot_classify_incident(api):
    """PRD §2.1: "A request whose role is not listed for the endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.3: "From `SUBMITTED`, a coordinator begins classification" and the
    classify operation is listed for `CleryCoordinator` only in §4.

    Design: Corner/rbac/csa_cannot_classify_incident
    """
    csa, _ = create_active_csa(
        completed_at="2026-06-20T10:00:00Z", score=90,
        full_name="Pat Prof", email="pat@example.edu",
        department="Faculty", csa_category="OTHER_OFFICIAL",
    )
    geography = create_geography(name="N", category="ON_CAMPUS")
    incident = create_under_classification_incident(
        geography["id"], reported_at="2026-04-13T09:00:00Z",
        occurred_at="2026-04-13T08:00:00Z",
    )

    from test_helpers import make_csa_headers
    res = api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=incident["version"],
            offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        ),
        make_csa_headers(csa["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
