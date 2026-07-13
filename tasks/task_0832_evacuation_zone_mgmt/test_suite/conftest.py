"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def commander_headers():
    return TEST_USERS["commander_headers"]


@pytest.fixture
def shelter_headers():
    return TEST_USERS["shelter_headers"]


@pytest.fixture
def traffic_headers():
    return TEST_USERS["traffic_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def pio_headers():
    return TEST_USERS["pio_headers"]
