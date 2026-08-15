"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def quality_director_headers():
    return TEST_USERS["quality_director_headers"]


@pytest.fixture
def peer_review_coordinator_headers():
    return TEST_USERS["peer_review_coordinator_headers"]


@pytest.fixture
def committee_member_headers():
    """Shared fallback for the entity-backed CommitteeMember role — only for
    calls that are not ownership-gated."""
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def provider_headers():
    """Shared fallback for the entity-backed Provider role — only for calls
    that are not ownership-gated."""
    return TEST_USERS["provider_headers"]
