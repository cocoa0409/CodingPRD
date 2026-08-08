"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def permittee_headers():
    return TEST_USERS["permittee_headers"]


@pytest.fixture
def curb_planner_headers():
    return TEST_USERS["curb_planner_headers"]


@pytest.fixture
def permit_approver_headers():
    return TEST_USERS["permit_approver_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
