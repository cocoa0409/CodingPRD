"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def release_manager_headers():
    return TEST_USERS["release_manager_headers"]


@pytest.fixture
def qa_lead_headers():
    return TEST_USERS["qa_lead_headers"]


@pytest.fixture
def vendor_manager_headers():
    return TEST_USERS["vendor_manager_headers"]


@pytest.fixture
def certification_lead_headers():
    return TEST_USERS["certification_lead_headers"]


@pytest.fixture
def platform_reviewer_headers():
    return TEST_USERS["platform_reviewer_headers"]


@pytest.fixture
def compliance_manager_headers():
    return TEST_USERS["compliance_manager_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def reader_headers():
    return TEST_USERS["reader_headers"]
