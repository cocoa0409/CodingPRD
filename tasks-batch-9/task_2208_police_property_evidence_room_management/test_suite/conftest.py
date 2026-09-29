"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def manager_headers():
    """PropertyRoomManager — an opaque operator identifier (PRD section 2.1)."""
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager_alt_headers():
    """A second PropertyRoomManager operator identifier."""
    return TEST_USERS["manager_alt_headers"]


@pytest.fixture
def court_clerk_headers():
    """CourtClerk — also an opaque operator identifier (PRD section 2.1)."""
    return TEST_USERS["court_clerk_headers"]
