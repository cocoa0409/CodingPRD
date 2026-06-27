"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def screening_officer_headers():
    return TEST_USERS["screening_officer_headers"]


@pytest.fixture
def matchmaker_headers():
    return TEST_USERS["matchmaker_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
