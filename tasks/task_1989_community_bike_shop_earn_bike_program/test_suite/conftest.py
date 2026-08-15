"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator_2_headers():
    return TEST_USERS["coordinator_2_headers"]


@pytest.fixture
def coordinator_approver_headers():
    return TEST_USERS["coordinator_approver_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def director_2_headers():
    return TEST_USERS["director_2_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
