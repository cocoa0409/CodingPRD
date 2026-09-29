"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client, one method per declared endpoint (PRD §4)."""
    return api_client


@pytest.fixture
def program_admin_headers():
    """Headers for the opaque ProgramAdmin operator identity (PRD §2.1)."""
    return TEST_USERS["program_admin_headers"]
