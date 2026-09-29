"""Shared pytest fixtures for the Sports Performance Facility API suite.

The harness restarts the API server before every individual test, so each test
below starts against an empty database and builds whatever state it needs
through the endpoints of §4.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The shared HTTP client for the API under test."""
    return api_client


@pytest.fixture
def performance_director_headers():
    """`PerformanceDirector` headers; its `X-User-ID` is an opaque operator id."""
    return TEST_USERS["performance_director_headers"]


@pytest.fixture
def medical_provider_headers():
    """`MedicalProvider` headers; its `X-User-ID` is an opaque operator id that the
    segregation-of-duties checks compare against `administered_by_staff_id`."""
    return TEST_USERS["medical_provider_headers"]


@pytest.fixture
def front_desk_headers():
    """`FrontDesk` headers; its `X-User-ID` is never compared to an entity id."""
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def coach_headers():
    """`Coach` headers carrying an id that resolves to no staff member.

    A `Coach`'s `X-User-ID` must be the id of the acting `StaffMember`, so tests
    that exercise a real coach action build their headers from the staff member
    they created; this fixture is only for checks that never resolve an identity.
    """
    return TEST_USERS["coach_headers"]


@pytest.fixture
def athlete_headers():
    """`Athlete` headers carrying an id that resolves to no athlete."""
    return TEST_USERS["athlete_headers"]


@pytest.fixture
def guardian_headers():
    """`Guardian` headers carrying an id that resolves to no athlete."""
    return TEST_USERS["guardian_headers"]
