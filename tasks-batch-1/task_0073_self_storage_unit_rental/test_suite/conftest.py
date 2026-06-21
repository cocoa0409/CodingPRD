"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fm_headers():
    return TEST_USERS["facility_manager_headers"]


@pytest.fixture
def lien_headers():
    return TEST_USERS["lien_administrator_headers"]


@pytest.fixture
def tenant_headers():
    return TEST_USERS["tenant_headers"]
