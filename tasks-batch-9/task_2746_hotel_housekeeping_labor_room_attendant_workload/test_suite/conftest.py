"""Shared pytest fixtures for the Hotel Housekeeping Labor & Workload suite."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client pointed at the implementation under test."""
    return api_client


@pytest.fixture(scope="session")
def users() -> dict:
    """Pre-built identity headers keyed by role name (PRD 2.1)."""
    return TEST_USERS
