"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def benefit_payment_officer_headers():
    return TEST_USERS["benefit_payment_officer_headers"]


@pytest.fixture
def appeals_clerk_headers():
    return TEST_USERS["appeals_clerk_headers"]


@pytest.fixture
def referee_headers():
    return TEST_USERS["referee_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
