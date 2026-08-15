"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def claims_headers():
    return TEST_USERS["claims_headers"]


@pytest.fixture
def quality_reporter_headers():
    return TEST_USERS["quality_reporter_headers"]


@pytest.fixture
def quality_auditor_headers():
    return TEST_USERS["quality_auditor_headers"]


@pytest.fixture
def actuary_headers():
    return TEST_USERS["actuary_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def review_officer_headers():
    return TEST_USERS["review_officer_headers"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
