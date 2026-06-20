"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restarting it via start.sh before each test).
"""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_caregiver_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def caregiver_headers():
    """Fallback caregiver headers (entity_backed). Use only for non-ownership
    tests; ownership-gated caregiver calls must use make_caregiver_headers(id)."""
    return TEST_USERS["caregiver_headers"]


@pytest.fixture
def caregiver_headers_factory():
    return make_caregiver_headers
