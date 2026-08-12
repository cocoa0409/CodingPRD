"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_institution_officer_headers, make_participant_headers,
    make_financial_coach_headers, make_coalition_admin_headers,
    make_agency_navigator_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def coalition_admin_headers():
    return TEST_USERS["coalition_admin_headers"]


@pytest.fixture
def agency_navigator_headers():
    return TEST_USERS["agency_navigator_headers"]


@pytest.fixture
def financial_coach_headers():
    return TEST_USERS["financial_coach_headers"]


@pytest.fixture
def institution_officer_headers():
    return TEST_USERS["institution_officer_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]
