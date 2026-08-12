"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def retailer_admin_headers():
    return TEST_USERS["retailer_admin_headers"]


@pytest.fixture
def category_manager_headers():
    return TEST_USERS["category_manager_headers"]


@pytest.fixture
def category_captain_headers():
    return TEST_USERS["category_captain_headers"]


@pytest.fixture
def field_auditor_headers():
    return TEST_USERS["field_auditor_headers"]


@pytest.fixture
def audit_reviewer_headers():
    return TEST_USERS["audit_reviewer_headers"]


@pytest.fixture
def reset_coordinator_headers():
    return TEST_USERS["reset_coordinator_headers"]
