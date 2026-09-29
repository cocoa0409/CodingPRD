"""Pytest fixtures exposing the shared test infrastructure.

Every test in this suite runs against an empty database, so the fixtures below
hand back the client and the role headers rather than any seeded data; the
preconditions each test needs are built through the endpoints the PRD declares.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def training_coordinator_headers():
    return TEST_USERS["training_coordinator_headers"]


@pytest.fixture
def development_coordinator_headers():
    return TEST_USERS["development_coordinator_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def committee_member_headers():
    return TEST_USERS["committee_member_headers"]
