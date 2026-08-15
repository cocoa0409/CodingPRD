"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def label_analyst_headers():
    return TEST_USERS["label_analyst_headers"]


@pytest.fixture
def regulatory_reviewer_headers():
    return TEST_USERS["regulatory_reviewer_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def client_rep_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["client_rep_headers"]


@pytest.fixture
def quality_manager_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["quality_manager_headers"]
