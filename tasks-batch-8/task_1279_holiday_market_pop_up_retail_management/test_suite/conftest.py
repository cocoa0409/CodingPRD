"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def market_operator_headers():
    return TEST_USERS["market_operator_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def jury_member_headers():
    return TEST_USERS["jury_member_headers"]


@pytest.fixture
def jury_chair_headers():
    return TEST_USERS["jury_chair_headers"]


@pytest.fixture
def utility_crew_headers():
    return TEST_USERS["utility_crew_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]
