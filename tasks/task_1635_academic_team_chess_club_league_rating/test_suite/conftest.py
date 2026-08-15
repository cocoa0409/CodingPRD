"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def federation_admin_headers():
    return TEST_USERS["federation_admin_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def club_coach_headers():
    # Shared fallback — only for tests that do not exercise ownership.
    return TEST_USERS["club_coach_headers"]


@pytest.fixture
def proctor_headers():
    # Shared fallback — only for tests that do not exercise ownership.
    return TEST_USERS["proctor_headers"]
