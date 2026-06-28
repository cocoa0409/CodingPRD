"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable and manages server
lifecycle (restarting the server before every test against an empty database).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def studio_admin_headers():
    return TEST_USERS["studio_admin_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
