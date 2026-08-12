"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def neighbor_headers():
    return TEST_USERS["neighbor_headers"]


@pytest.fixture
def traffic_reviewer_headers():
    return TEST_USERS["traffic_reviewer_headers"]


@pytest.fixture
def safety_reviewer_headers():
    return TEST_USERS["safety_reviewer_headers"]


@pytest.fixture
def permit_officer_headers():
    return TEST_USERS["permit_officer_headers"]


@pytest.fixture
def city_admin_headers():
    return TEST_USERS["city_admin_headers"]


@pytest.fixture
def depot_officer_1_headers():
    return TEST_USERS["depot_officer_1_headers"]


@pytest.fixture
def depot_officer_2_headers():
    return TEST_USERS["depot_officer_2_headers"]
