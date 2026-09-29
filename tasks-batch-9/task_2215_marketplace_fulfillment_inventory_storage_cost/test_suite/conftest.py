"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def seller_operator_headers():
    """Shared `SellerOperator` headers — for calls that never reach an ownership check."""
    return TEST_USERS["seller_operator_headers"]


@pytest.fixture
def fc_operator_headers():
    """Shared `FcOperator` headers — for calls that never reach an ownership check."""
    return TEST_USERS["fc_operator_headers"]


@pytest.fixture
def claims_adjudicator_headers():
    return TEST_USERS["claims_adjudicator_headers"]


@pytest.fixture
def marketplace_admin_headers():
    return TEST_USERS["marketplace_admin_headers"]
