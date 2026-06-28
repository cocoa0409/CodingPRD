"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def frontdesk_headers():
    return TEST_USERS["frontdesk_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def orthodontist_headers():
    return TEST_USERS["orthodontist_headers"]


@pytest.fixture
def guardian_headers():
    return TEST_USERS["guardian_headers"]
