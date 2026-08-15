"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst2_headers():
    return TEST_USERS["analyst2_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor2_headers():
    return TEST_USERS["supervisor2_headers"]


@pytest.fixture
def desk1_headers():
    return TEST_USERS["desk1_headers"]


@pytest.fixture
def desk2_headers():
    return TEST_USERS["desk2_headers"]


@pytest.fixture
def market_ops_headers():
    return TEST_USERS["market_ops_headers"]
