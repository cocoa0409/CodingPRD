"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def compliance_headers() -> dict:
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_2_headers() -> dict:
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
