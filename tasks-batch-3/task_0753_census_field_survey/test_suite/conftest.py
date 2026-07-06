"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS, make_enumerator_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["survey_admin_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["field_supervisor_headers"]


@pytest.fixture
def qc_headers():
    return TEST_USERS["qc_reviewer_headers"]


@pytest.fixture
def enumerator_headers():
    """Fallback Enumerator headers for non-ownership scenarios (RBAC denials, 404s)."""
    return TEST_USERS["enumerator_headers"]


@pytest.fixture
def eh():
    """Return the per-instance Enumerator-role header builder."""
    return make_enumerator_headers
