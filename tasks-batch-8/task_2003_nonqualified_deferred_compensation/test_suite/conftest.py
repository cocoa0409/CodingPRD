"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-per-test) is managed by
prd-bench-local-runner; tests assume the API is reachable at API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plan_sponsor_headers():
    return TEST_USERS["plan_sponsor_headers"]


@pytest.fixture
def benefits_admin_headers():
    return TEST_USERS["benefits_admin_headers"]


@pytest.fixture
def benefits_admin_2_headers():
    return TEST_USERS["benefits_admin_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_2_headers():
    return TEST_USERS["compliance_officer_2_headers"]


@pytest.fixture
def trust_officer_headers():
    return TEST_USERS["trust_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]
