"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, make_grower_rep_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def contractor_admin_headers():
    return TEST_USERS["contractor_admin_headers"]


@pytest.fixture
def program_reviewer_headers():
    return TEST_USERS["program_reviewer_headers"]


@pytest.fixture
def housing_inspector_headers():
    return TEST_USERS["housing_inspector_headers"]


@pytest.fixture
def visa_officer_headers():
    return TEST_USERS["visa_officer_headers"]


@pytest.fixture
def wage_auditor_headers():
    return TEST_USERS["wage_auditor_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def grower_rep_headers():
    return TEST_USERS["grower_rep_headers"]


@pytest.fixture
def grower_rep_headers_factory():
    """Per-instance GrowerRep header builder (X-User-ID = acting Grower id)."""
    return make_grower_rep_headers
