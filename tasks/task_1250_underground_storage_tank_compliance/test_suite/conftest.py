"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def owner_headers():
    return TEST_USERS["facility_owner_headers"]


@pytest.fixture
def owner_2_headers():
    return TEST_USERS["facility_owner_2_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["contractor_admin_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["state_regulator_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]
