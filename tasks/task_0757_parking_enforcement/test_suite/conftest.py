"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts
against a freshly-restarted (empty-database) API with the logical clock at
its startup default per the per-test-server isolation contract.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


@pytest.fixture
def supervisor_headers() -> dict:
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def hearing_officer_headers() -> dict:
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def motorist_headers() -> dict:
    return TEST_USERS["motorist_headers"]


@pytest.fixture
def enforcement_officer_headers() -> dict:
    """Placeholder EnforcementOfficer headers. Safe for non-ownership tests
    only; ownership paths use make_enforcement_officer_headers(officer_id)."""
    return TEST_USERS["enforcement_officer_headers"]
