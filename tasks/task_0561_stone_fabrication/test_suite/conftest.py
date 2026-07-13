"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def shopmanager_headers():
    return TEST_USERS["shopmanager_headers"]


@pytest.fixture
def salesrep_headers():
    return TEST_USERS["salesrep_headers"]


@pytest.fixture
def fabricator_headers():
    return TEST_USERS["fabricator_headers"]


@pytest.fixture
def installer_headers():
    return TEST_USERS["installer_headers"]
