"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is owned by the runner; this file only wires pytest fixtures.
Per per-test-server isolation, every test begins against an empty database, so
each test pins the clock and constructs its own preconditions.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def school_staff_headers():
    return TEST_USERS["school_staff_headers"]


@pytest.fixture
def district_reviewer_headers():
    return TEST_USERS["district_reviewer_headers"]


@pytest.fixture
def usda_auditor_headers():
    return TEST_USERS["usda_auditor_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def parent_headers():
    """Generic Parent headers (X-User-ID = fallback). Do NOT use for
    ownership-gated calls — use make_parent_headers(household_id) instead."""
    return TEST_USERS["parent_headers"]
