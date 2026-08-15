"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager2_headers():
    return TEST_USERS["manager2_headers"]


@pytest.fixture
def head_teller_headers():
    return TEST_USERS["head_teller_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
