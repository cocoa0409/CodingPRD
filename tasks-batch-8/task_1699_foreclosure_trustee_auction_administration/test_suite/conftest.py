"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def trustee_admin_headers():
    return TEST_USERS["trustee_admin_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def auctioneer_headers():
    return TEST_USERS["auctioneer_headers"]


@pytest.fixture
def beneficiary_headers():
    return TEST_USERS["beneficiary_headers"]


@pytest.fixture
def third_party_bidder_headers():
    return TEST_USERS["third_party_bidder_headers"]
