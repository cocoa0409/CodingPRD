"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def merchandiser_headers():
    return TEST_USERS["merchandiser_headers"]


@pytest.fixture
def grade_clerk_headers():
    return TEST_USERS["grade_clerk_headers"]


@pytest.fixture
def settlement_officer_headers():
    return TEST_USERS["settlement_officer_headers"]


@pytest.fixture
def shipping_clerk_headers():
    return TEST_USERS["shipping_clerk_headers"]


@pytest.fixture
def risk_manager_headers():
    return TEST_USERS["risk_manager_headers"]
