"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def nm_headers():
    return TEST_USERS["network_manager_headers"]


@pytest.fixture
def co_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def reg_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def provider_rep_headers():
    return TEST_USERS["provider_rep_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
