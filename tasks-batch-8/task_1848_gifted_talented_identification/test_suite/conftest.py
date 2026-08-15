"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def gifted_coordinator_headers():
    return TEST_USERS["gifted_coordinator_headers"]


@pytest.fixture
def referring_educator_headers():
    return TEST_USERS["referring_educator_headers"]


@pytest.fixture
def parent_guardian_headers():
    return TEST_USERS["parent_guardian_headers"]


@pytest.fixture
def committee_member_headers():
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def special_ed_coordinator_headers():
    return TEST_USERS["special_ed_coordinator_headers"]
