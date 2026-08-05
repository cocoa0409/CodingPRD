"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sc_headers():
    return TEST_USERS["state_coordinator_headers"]


@pytest.fixture
def liaison_headers():
    return TEST_USERS["liaison_headers"]


@pytest.fixture
def transport_coordinator_headers():
    return TEST_USERS["transport_coordinator_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]
