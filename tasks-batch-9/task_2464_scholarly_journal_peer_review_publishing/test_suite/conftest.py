"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    """Headers for the opaque editorial-office operator role."""
    return TEST_USERS["system_admin"]


@pytest.fixture
def production_staff_headers():
    """Headers for the opaque production-desk role."""
    return TEST_USERS["production_staff"]
