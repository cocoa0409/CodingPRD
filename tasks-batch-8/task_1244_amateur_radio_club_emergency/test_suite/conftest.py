"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers.fixtures import reset_clock_floor


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture(autouse=True)
def _fresh_server_clock_floor():
    """Per-test-server isolation boots a fresh server (logical clock back at
    the PRD §2.5 startup default) before every test; keep the fixture-side
    clock floor in sync."""
    reset_clock_floor()
    yield


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def netcontrol_headers():
    return TEST_USERS["netcontrol_headers"]


@pytest.fixture
def ec_headers():
    return TEST_USERS["ec_headers"]


@pytest.fixture
def liaison_headers():
    return TEST_USERS["liaison_headers"]
