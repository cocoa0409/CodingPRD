"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and restarts the API before every test, so each
test starts against an empty database with the logical clock at 2026-08-01T00:00:00Z.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]
