"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; these fixtures just hand the
shared API client and role headers to tests.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def practice_admin_headers():
    return TEST_USERS["practice_admin_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def consultant_headers():
    return TEST_USERS["consultant_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
