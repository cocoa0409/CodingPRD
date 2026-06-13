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
def teller_headers() -> dict:
    """Teller (opaque id teller-1)."""
    return TEST_USERS["teller_headers"]


@pytest.fixture
def teller2_headers() -> dict:
    """A second Teller (opaque id teller-2)."""
    return TEST_USERS["teller2_headers"]


@pytest.fixture
def officer_headers() -> dict:
    """ComplianceOfficer (opaque id officer-1)."""
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer2_headers() -> dict:
    """A second ComplianceOfficer (opaque id officer-2) — for segregation-of-duties
    runs where the adjudicator must differ from the submitter (PRD §3.3)."""
    return TEST_USERS["officer2_headers"]


@pytest.fixture
def account_holder_headers() -> dict:
    """Generic AccountHolder headers (fake id). Use only for non-ownership paths
    (401/403/404), never where ownership must match a real Customer.id (PRD §2.1)."""
    return TEST_USERS["account_holder_headers"]
