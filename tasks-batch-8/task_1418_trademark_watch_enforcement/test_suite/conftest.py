"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def paralegal_headers():
    return TEST_USERS["paralegal_headers"]


@pytest.fixture
def associate_headers():
    return TEST_USERS["associate_headers"]


@pytest.fixture
def partner_headers():
    return TEST_USERS["partner_headers"]


@pytest.fixture
def watch_service_headers():
    return TEST_USERS["watch_service_headers"]


@pytest.fixture
def client_contact_headers():
    return TEST_USERS["client_contact_headers"]
