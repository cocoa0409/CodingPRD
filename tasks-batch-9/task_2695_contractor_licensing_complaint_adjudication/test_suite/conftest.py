"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def board_admin_headers():
    """Headers for the board administrator who drives the logical clock."""
    return TEST_USERS["board_admin_headers"]


@pytest.fixture
def licensing_analyst_headers():
    """Headers for the licensing analyst who decides applications and coverage."""
    return TEST_USERS["licensing_analyst_headers"]


@pytest.fixture
def investigator_headers():
    """Headers for the investigator who opens, closes and cites cases."""
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def second_investigator_headers():
    """Headers for a second investigator, used for assigned-investigator checks."""
    return TEST_USERS["second_investigator_headers"]


@pytest.fixture
def hearing_officer_headers():
    """Headers for the hearing officer who presides over appeals."""
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def second_hearing_officer_headers():
    """Headers for a second hearing officer, used for calendar-conflict checks."""
    return TEST_USERS["second_hearing_officer_headers"]


@pytest.fixture
def fund_adjudicator_headers():
    """Headers for the adjudicator who approves and disburses fund claims."""
    return TEST_USERS["fund_adjudicator_headers"]
