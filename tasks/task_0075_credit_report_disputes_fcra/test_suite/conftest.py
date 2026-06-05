"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]


@pytest.fixture
def furnisher_headers():
    return TEST_USERS["furnisher_headers"]


@pytest.fixture
def bureau_headers():
    return TEST_USERS["bureau_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]
