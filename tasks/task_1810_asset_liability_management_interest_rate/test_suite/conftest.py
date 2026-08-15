"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst2_headers():
    return TEST_USERS["analyst2_headers"]


@pytest.fixture
def validator_headers():
    return TEST_USERS["validator_headers"]


@pytest.fixture
def chair_headers():
    return TEST_USERS["chair_headers"]


@pytest.fixture
def chair2_headers():
    return TEST_USERS["chair2_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]
