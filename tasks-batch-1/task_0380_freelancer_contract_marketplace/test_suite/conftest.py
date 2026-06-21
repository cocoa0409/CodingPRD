"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def client_headers():
    """Shared Client headers — only for non-ownership tests (bad payload / missing resource)."""
    return TEST_USERS["client_headers"]


@pytest.fixture
def freelancer_headers():
    """Shared Freelancer headers — only for non-ownership tests."""
    return TEST_USERS["freelancer_headers"]


@pytest.fixture
def arbitrator_headers():
    return TEST_USERS["arbitrator_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
