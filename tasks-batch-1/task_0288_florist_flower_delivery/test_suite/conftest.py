"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, readiness, per-test restart) is owned by
prd-bench-local-runner; these fixtures only wire test_helpers into pytest.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def catalog_admin_headers():
    return TEST_USERS["catalog_admin_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def florist_headers():
    return TEST_USERS["florist_headers"]
