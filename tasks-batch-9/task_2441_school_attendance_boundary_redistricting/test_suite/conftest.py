"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def planner_headers():
    """A DistrictPlanner caller."""
    return TEST_USERS["planner_headers"]


@pytest.fixture
def second_planner_headers():
    """A second DistrictPlanner caller, distinct from ``planner_headers``."""
    return TEST_USERS["second_planner_headers"]


@pytest.fixture
def coordinator_headers():
    """An EngagementCoordinator caller."""
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def board_headers():
    """A BoardMember caller."""
    return TEST_USERS["board_headers"]


@pytest.fixture
def second_board_headers():
    """A second BoardMember caller, distinct from ``board_headers``."""
    return TEST_USERS["second_board_headers"]


@pytest.fixture
def officer_headers():
    """A TransferOfficer caller."""
    return TEST_USERS["officer_headers"]


@pytest.fixture
def second_officer_headers():
    """A second TransferOfficer caller, distinct from ``officer_headers``."""
    return TEST_USERS["second_officer_headers"]


@pytest.fixture
def guardian_headers():
    """A Guardian caller."""
    return TEST_USERS["guardian_headers"]
