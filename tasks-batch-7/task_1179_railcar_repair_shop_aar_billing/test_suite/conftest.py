"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def shop_admin_headers():
    return TEST_USERS["shop_admin"]


@pytest.fixture
def yard_clerk_headers():
    return TEST_USERS["yard_clerk"]


@pytest.fixture
def car_inspector_headers():
    return TEST_USERS["car_inspector"]


@pytest.fixture
def repair_foreman_headers():
    return TEST_USERS["repair_foreman"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector"]


@pytest.fixture
def parts_clerk_headers():
    return TEST_USERS["parts_clerk"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk"]
