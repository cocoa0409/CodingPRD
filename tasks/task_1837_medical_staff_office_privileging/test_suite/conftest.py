"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def committee_chair_headers():
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def mec_chair_headers():
    return TEST_USERS["mec_chair_headers"]


@pytest.fixture
def board_member_headers():
    return TEST_USERS["board_member_headers"]


@pytest.fixture
def hearing_officer_headers():
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def department_chief_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["department_chief_headers"]


@pytest.fixture
def practitioner_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["practitioner_headers"]
