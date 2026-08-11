"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def event_director_headers():
    return TEST_USERS["event_director_headers"]


@pytest.fixture
def registration_officer_headers():
    return TEST_USERS["registration_officer_headers"]


@pytest.fixture
def screening_officer_headers():
    return TEST_USERS["screening_officer_headers"]


@pytest.fixture
def procurement_officer_headers():
    return TEST_USERS["procurement_officer_headers"]


@pytest.fixture
def queue_manager_headers():
    return TEST_USERS["queue_manager_headers"]


@pytest.fixture
def field_reset_crew_headers():
    return TEST_USERS["field_reset_crew_headers"]


@pytest.fixture
def judge_advisor_headers():
    return TEST_USERS["judge_advisor_headers"]


@pytest.fixture
def travel_officer_headers():
    return TEST_USERS["travel_officer_headers"]


@pytest.fixture
def team_lead_headers():
    return TEST_USERS["team_lead_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def lead_inspector_headers():
    return TEST_USERS["lead_inspector_headers"]


@pytest.fixture
def head_referee_headers():
    return TEST_USERS["head_referee_headers"]


@pytest.fixture
def scorekeeper_headers():
    return TEST_USERS["scorekeeper_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]
