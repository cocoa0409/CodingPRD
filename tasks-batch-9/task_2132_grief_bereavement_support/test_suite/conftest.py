"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_counselor_headers,
    make_participant_headers,
    make_volunteer_companion_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def referral_source_headers():
    return TEST_USERS["referral_source_headers"]


@pytest.fixture
def grant_officer_headers():
    return TEST_USERS["grant_officer_headers"]


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def volunteer_companion_headers():
    return TEST_USERS["volunteer_companion_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def participant_headers_for():
    """Builder for ownership-gated calls made as a specific Participant."""
    return make_participant_headers


@pytest.fixture
def counselor_headers_for():
    """Builder for ownership-gated calls made as a specific Counselor."""
    return make_counselor_headers


@pytest.fixture
def volunteer_headers_for():
    """Builder for ownership-gated calls made as a specific VolunteerCompanion."""
    return make_volunteer_companion_headers
