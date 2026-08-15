"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def desk_admin_headers():
    return TEST_USERS["desk_admin_headers"]


@pytest.fixture
def trader_headers():
    return TEST_USERS["trader_headers"]


@pytest.fixture
def risk_officer_headers():
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def quality_grader_headers():
    return TEST_USERS["quality_grader_headers"]


@pytest.fixture
def warehouse_operator_headers():
    return TEST_USERS["warehouse_operator_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]
