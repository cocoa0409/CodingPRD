"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server before every test. These fixtures only wire test_helpers
into pytest; they never start/stop or health-check the server.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clinic_admin_headers():
    return TEST_USERS["clinic_admin_headers"]


@pytest.fixture
def intake_nurse_headers():
    return TEST_USERS["intake_nurse_headers"]


@pytest.fixture
def medical_director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]
