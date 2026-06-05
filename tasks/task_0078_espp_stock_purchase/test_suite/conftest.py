"""Pytest fixtures exposing test_helpers infrastructure (PRD §2.1).

Server lifecycle is managed by prd-bench-local-runner; each test starts against a
freshly-restarted (empty-database) API per the per-test-server isolation contract.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """PlanAdministrator (opaque id admin1)."""
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def admin2_headers() -> dict:
    """A second PlanAdministrator (opaque id admin2) — for segregation-of-duties
    runs where the runner must differ from the certifying officer."""
    return TEST_USERS["plan_admin2_headers"]


@pytest.fixture
def officer_headers() -> dict:
    """ComplianceOfficer (opaque id officer1)."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def officer2_headers() -> dict:
    return TEST_USERS["compliance_officer2_headers"]


@pytest.fixture
def participant_headers() -> dict:
    """Generic Participant headers (fake id). Use only for non-ownership paths
    (401/403/404), never where ownership must match a real Participant.id."""
    return TEST_USERS["participant_headers"]
