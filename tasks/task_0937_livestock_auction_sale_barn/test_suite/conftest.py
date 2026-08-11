"""Pytest fixtures exposing the sale barn test helpers."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def barn_admin_headers():
    return TEST_USERS["barn_admin_headers"]


@pytest.fixture
def yard_operator_headers():
    return TEST_USERS["yard_operator_headers"]


@pytest.fixture
def auctioneer_headers():
    return TEST_USERS["auctioneer_headers"]


@pytest.fixture
def ring_clerk_headers():
    return TEST_USERS["ring_clerk_headers"]


@pytest.fixture
def settlement_clerk_headers():
    return TEST_USERS["settlement_clerk_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]
