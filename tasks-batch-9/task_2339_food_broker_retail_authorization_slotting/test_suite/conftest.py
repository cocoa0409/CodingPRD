"""Shared pytest fixtures for the Food Broker Authorization & Slotting suite.

The server is already running when these tests execute and its database is empty
at the start of every individual test, so each test builds the preconditions it
needs through the declared endpoints.
"""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    AUDIT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    ApiClient,
)


@pytest.fixture
def api() -> ApiClient:
    """One client per test, pointed at the running API by the runner's base URL."""
    return ApiClient()


@pytest.fixture
def admin_headers():
    return BROKER_ADMIN_HEADERS


@pytest.fixture
def manager_headers():
    return ACCOUNT_MANAGER_HEADERS


@pytest.fixture
def auditor_headers():
    return AUDIT_MANAGER_HEADERS
