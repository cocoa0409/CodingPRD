"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable at
API_BASE_URL with an empty database at the start of every test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def model_owner_a_headers():
    return TEST_USERS["model_owner_a_headers"]


@pytest.fixture
def model_owner_b_headers():
    return TEST_USERS["model_owner_b_headers"]


@pytest.fixture
def model_validator_headers():
    return TEST_USERS["model_validator_headers"]


@pytest.fixture
def model_validator_b_headers():
    return TEST_USERS["model_validator_b_headers"]


@pytest.fixture
def risk_officer_headers():
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def reporter_headers():
    return TEST_USERS["reporter_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
