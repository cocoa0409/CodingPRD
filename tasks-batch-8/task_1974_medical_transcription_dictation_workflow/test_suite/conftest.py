"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def vendor_admin_headers():
    return TEST_USERS["vendor_admin_headers"]


@pytest.fixture
def client_admin_headers():
    return TEST_USERS["client_admin_headers"]


@pytest.fixture
def qa_supervisor_headers():
    return TEST_USERS["qa_supervisor_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]


@pytest.fixture
def editor_headers():
    return TEST_USERS["editor_headers"]
