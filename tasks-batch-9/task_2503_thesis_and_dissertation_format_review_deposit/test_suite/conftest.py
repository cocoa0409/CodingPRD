"""Shared fixtures for the graduate-school format review and deposit suite.

The harness restarts the API and empties the database before every individual
test, so every fixture below builds its state from scratch through documented
endpoints. Only the client is session-scoped; nothing else may be shared.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient, api_client  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The client every helper shares, pointed at the API under test."""
    api_client.base_url = os.environ.get("API_BASE_URL", api_client.base_url)
    return api_client


@pytest.fixture
def registrar_headers() -> dict:
    """Registrar: terms, rosters, rooms, the clock and the term-level runs."""
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def analyst_headers() -> dict:
    """The first graduate-school analyst identity."""
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_two_headers() -> dict:
    """A second analyst identity, required wherever duties are segregated."""
    return TEST_USERS["analyst_two_headers"]


@pytest.fixture
def dean_headers() -> dict:
    """The first graduate dean identity."""
    return TEST_USERS["dean_headers"]


@pytest.fixture
def dean_two_headers() -> dict:
    """A second dean identity, required wherever duties are segregated."""
    return TEST_USERS["dean_two_headers"]


@pytest.fixture
def integrity_officer_headers() -> dict:
    """The first integrity officer identity."""
    return TEST_USERS["integrity_officer_headers"]


@pytest.fixture
def integrity_officer_two_headers() -> dict:
    """A second integrity officer identity."""
    return TEST_USERS["integrity_officer_two_headers"]


@pytest.fixture
def student_headers() -> dict:
    """A Student identity not bound to any persisted candidate."""
    return TEST_USERS["student_headers"]


@pytest.fixture
def faculty_member_headers() -> dict:
    """A FacultyMember identity not bound to any persisted faculty row."""
    return TEST_USERS["faculty_member_headers"]
