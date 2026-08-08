"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def vradmin_headers():
    return TEST_USERS["vradmin_headers"]


@pytest.fixture
def fiscal_officer_headers():
    return TEST_USERS["fiscal_officer_headers"]


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]
