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
def intake_counselor_headers():
    return TEST_USERS["intake_counselor_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def recovery_officer_headers():
    return TEST_USERS["recovery_officer_headers"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer_headers"]
