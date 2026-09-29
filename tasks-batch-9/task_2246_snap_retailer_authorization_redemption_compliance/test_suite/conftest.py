"""Shared pytest fixtures for the SNAP retailer authorization suite.

The harness restarts the API before every test, so each test begins against an
empty database on the default logical clock of 2026-08-01T00:00:00Z and builds
every precondition it needs through the published endpoints.
"""
import pytest

from test_helpers import (
    ADMIN,
    ADMIN_ALT,
    ANALYST,
    ANALYST_ALT,
    ANON,
    REVIEWER,
    REVIEWER_ALT,
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client for the service under test."""
    return api_client


@pytest.fixture
def anon_headers():
    """Anonymous: owner registration only."""
    return ANON


@pytest.fixture
def admin_headers():
    """FnsAdmin: the clock, decisions, determinations, enforcement, equipment."""
    return ADMIN


@pytest.fixture
def admin_alt_headers():
    """A second FnsAdmin, for the segregation-of-duties pairings."""
    return ADMIN_ALT


@pytest.fixture
def analyst_headers():
    """FnsAnalyst: visits, monitoring periods, investigations."""
    return ANALYST


@pytest.fixture
def analyst_alt_headers():
    """A second FnsAnalyst, who is the one allowed to conclude."""
    return ANALYST_ALT


@pytest.fixture
def reviewer_headers():
    """AdminReviewOfficer: administrative-review decisions."""
    return REVIEWER


@pytest.fixture
def reviewer_alt_headers():
    """A second AdminReviewOfficer, for the review segregation rule."""
    return REVIEWER_ALT


@pytest.fixture
def role_headers():
    """Every opaque-identity role header set, keyed by role."""
    return TEST_USERS
