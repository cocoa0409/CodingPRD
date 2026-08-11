"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def funding_officer_headers():
    return TEST_USERS["funding_officer_headers"]


@pytest.fixture
def funding_officer_two_headers():
    return TEST_USERS["funding_officer_two_headers"]


@pytest.fixture
def transport_dispatcher_headers():
    return TEST_USERS["transport_dispatcher_headers"]
