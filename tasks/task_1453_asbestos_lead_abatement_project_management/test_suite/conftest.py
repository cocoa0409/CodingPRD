"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def contractor_admin_headers():
    return TEST_USERS["contractor_admin_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def industrial_hygienist_headers():
    return TEST_USERS["industrial_hygienist_headers"]


@pytest.fixture
def regulator_clerk_headers():
    return TEST_USERS["regulator_clerk_headers"]


@pytest.fixture
def facility_operator_headers():
    return TEST_USERS["facility_operator_headers"]
