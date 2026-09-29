"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers.fixtures import (  # noqa: F401  (re-exported as pytest fixtures)
    away_regatta,
    cast,
    confirmed_entry,
    coxed_four_shell,
    declared_entry,
    draft_entry,
    filed_protest,
    home_regatta,
    open_reading,
    open_trailer,
    provisional_heat,
    racing_heat,
    sealed_trailer,
    single_shell,
    submitted_entry,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def club_admin_headers():
    """The club office. `ClubAdmin` acts under an opaque operator identifier."""
    return TEST_USERS["club_admin_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def equipment_manager_headers():
    return TEST_USERS["equipment_manager_headers"]


@pytest.fixture
def race_official_headers():
    return TEST_USERS["race_official_headers"]


@pytest.fixture
def jury_chair_headers():
    return TEST_USERS["jury_chair_headers"]
