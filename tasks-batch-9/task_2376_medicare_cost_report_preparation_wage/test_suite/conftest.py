"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, api_client
from test_helpers.test_users import (
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    CLERK_HEADERS,
    MANAGER_HEADERS,
    SYSTEM_ADMIN_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return SYSTEM_ADMIN_HEADERS


@pytest.fixture
def analyst_headers():
    return ANALYST_HEADERS


@pytest.fixture
def manager_headers():
    return MANAGER_HEADERS


@pytest.fixture
def auditor_headers():
    return AUDITOR_HEADERS


@pytest.fixture
def clerk_headers():
    return CLERK_HEADERS
