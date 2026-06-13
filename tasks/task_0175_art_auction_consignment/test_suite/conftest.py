"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def auctioneer_headers():
    return TEST_USERS["auctioneer_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def viewer_headers():
    return TEST_USERS["viewer_headers"]


@pytest.fixture
def seller_headers():
    return TEST_USERS["seller_headers"]


@pytest.fixture
def bidder_headers():
    return TEST_USERS["bidder_headers"]
