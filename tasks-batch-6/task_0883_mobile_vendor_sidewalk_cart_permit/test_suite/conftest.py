"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH so `test_helpers` is importable and
manages server lifecycle (restart before each test, so every test starts against
an empty database).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def permit_officer_headers():
    return TEST_USERS["permit_officer_headers"]


@pytest.fixture
def health_inspector_headers():
    return TEST_USERS["health_inspector_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def enforcement_officer_2_headers():
    return TEST_USERS["enforcement_officer_2_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]
