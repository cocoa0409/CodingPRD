"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner handles PYTHONPATH so `test_helpers` is importable,
and supplies API_BASE_URL + a fresh server before every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def motorist_headers():
    return TEST_USERS["motorist_headers"]


@pytest.fixture
def merchant_headers():
    return TEST_USERS["merchant_headers"]
