"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def reader_headers():
    """Reader identity for calls that are not ownership-gated."""
    return TEST_USERS["reader_headers"]


@pytest.fixture
def group_admin_headers():
    """GroupAdmin identity for calls that are not ownership-gated."""
    return TEST_USERS["group_admin_headers"]


@pytest.fixture
def ops_agent_headers():
    return TEST_USERS["ops_agent_headers"]


@pytest.fixture
def revenue_manager_headers():
    return TEST_USERS["revenue_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_two_headers():
    return TEST_USERS["compliance_officer_two_headers"]


@pytest.fixture
def compliance_officer_nine_headers():
    return TEST_USERS["compliance_officer_nine_headers"]
