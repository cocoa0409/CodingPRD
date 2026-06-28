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
def gallery_admin_headers():
    return TEST_USERS["gallery_admin_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def sales_associate_headers():
    return TEST_USERS["sales_associate_headers"]


@pytest.fixture
def artist_headers():
    return TEST_USERS["artist_headers"]
