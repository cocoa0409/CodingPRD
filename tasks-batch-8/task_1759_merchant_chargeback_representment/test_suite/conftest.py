"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def acquirer_ops_headers():
    return TEST_USERS["acquirer_ops_headers"]


@pytest.fixture
def risk_officer_headers():
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def finance_ops_headers():
    return TEST_USERS["finance_ops_headers"]


@pytest.fixture
def merchant_user_headers():
    return TEST_USERS["merchant_user_headers"]
