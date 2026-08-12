"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already running at API_BASE_URL and is restarted (empty database) before
every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def educator_headers():
    return TEST_USERS["educator_headers"]


@pytest.fixture
def funder_analyst_headers():
    return TEST_USERS["funder_analyst_headers"]


@pytest.fixture
def clinic_staff_headers():
    return TEST_USERS["clinic_staff_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def retailer_staff_headers():
    return TEST_USERS["retailer_staff_headers"]
