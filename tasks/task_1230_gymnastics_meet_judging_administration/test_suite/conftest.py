"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def meet_director_headers():
    return TEST_USERS["meet_director_headers"]


@pytest.fixture
def meet_referee_headers():
    return TEST_USERS["meet_referee_headers"]


@pytest.fixture
def judge_panel_chief_headers():
    return TEST_USERS["judge_panel_chief_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def gate_attendant_headers():
    return TEST_USERS["gate_attendant_headers"]


@pytest.fixture
def spectator_headers():
    return TEST_USERS["spectator_headers"]
