"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def station_admin_headers():
    return TEST_USERS["station_admin_headers"]


@pytest.fixture
def airline_rep_headers():
    return TEST_USERS["airline_rep_headers"]


@pytest.fixture
def pad_operator_headers():
    return TEST_USERS["pad_operator_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def environmental_officer_headers():
    return TEST_USERS["environmental_officer_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]
