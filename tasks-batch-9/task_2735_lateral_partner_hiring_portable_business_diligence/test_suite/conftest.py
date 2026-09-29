"""Pytest fixtures exposing the Lateral Partner Hiring test infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def recruiting_coordinator_headers():
    return TEST_USERS["recruiting_coordinator_headers"]


@pytest.fixture
def conflicts_counsel_headers():
    return TEST_USERS["conflicts_counsel_headers"]


@pytest.fixture
def committee_chair_headers():
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def peer_committee_chair_headers():
    return TEST_USERS["peer_committee_chair_headers"]


@pytest.fixture
def committee_member_headers():
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def practice_group_leader_headers():
    return TEST_USERS["practice_group_leader_headers"]


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]
