"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def supervising_headers():
    return TEST_USERS["supervising_headers"]


@pytest.fixture
def judicial_headers():
    return TEST_USERS["judicial_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
