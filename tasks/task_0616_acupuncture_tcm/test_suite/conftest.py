"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, sets API_BASE_URL, and
restarts the server before every test. These tests assume the server is already up.
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
def practitioner_headers():
    return TEST_USERS["practitioner_headers"]


@pytest.fixture
def pharmacist_headers():
    return TEST_USERS["pharmacist_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]
