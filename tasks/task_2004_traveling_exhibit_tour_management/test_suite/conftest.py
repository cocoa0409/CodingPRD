"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def tour_manager_headers():
    return TEST_USERS["tour_manager_headers"]


@pytest.fixture
def venue_registrar_headers():
    return TEST_USERS["venue_registrar_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def shipper_headers():
    return TEST_USERS["shipper_headers"]


@pytest.fixture
def insurer_headers():
    return TEST_USERS["insurer_headers"]
