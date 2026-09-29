"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def underwriter_2_headers():
    return TEST_USERS["underwriter_2_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager_2_headers():
    return TEST_USERS["manager_2_headers"]


@pytest.fixture
def risk_engineer_headers():
    return TEST_USERS["risk_engineer_headers"]


@pytest.fixture
def risk_engineer_2_headers():
    return TEST_USERS["risk_engineer_2_headers"]


@pytest.fixture
def claim_adjuster_headers():
    return TEST_USERS["claim_adjuster_headers"]


@pytest.fixture
def claim_adjuster_2_headers():
    return TEST_USERS["claim_adjuster_2_headers"]
