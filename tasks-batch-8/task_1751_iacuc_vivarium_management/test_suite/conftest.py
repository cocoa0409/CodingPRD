"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner: the server is
restarted before every test, so each test starts against an empty database
and the default logical clock (2026-08-01T00:00:00Z, PRD §2.4).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def facility_headers():
    return TEST_USERS["facility_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def training_headers():
    return TEST_USERS["training_headers"]


@pytest.fixture
def occ_health_headers():
    return TEST_USERS["occ_health_headers"]


@pytest.fixture
def staff_headers():
    """Shared fallback only — no PRD rule dereferences the staff caller id."""
    return TEST_USERS["staff_headers"]


@pytest.fixture
def vet_headers():
    """Shared fallback only — no PRD rule dereferences the vet caller id."""
    return TEST_USERS["vet_headers"]


@pytest.fixture
def investigator_headers():
    """Shared fallback only — ownership-gated calls must use
    make_investigator_headers(investigator_id) with the real Investigator.id."""
    return TEST_USERS["investigator_headers"]
