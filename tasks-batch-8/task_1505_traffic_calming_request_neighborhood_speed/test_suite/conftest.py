"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]


@pytest.fixture
def traffic_engineer_headers():
    return TEST_USERS["traffic_engineer_headers"]


@pytest.fixture
def city_engineer_headers():
    return TEST_USERS["city_engineer_headers"]


@pytest.fixture
def emergency_reviewer_headers():
    return TEST_USERS["emergency_reviewer_headers"]


@pytest.fixture
def city_admin_headers():
    return TEST_USERS["city_admin_headers"]
