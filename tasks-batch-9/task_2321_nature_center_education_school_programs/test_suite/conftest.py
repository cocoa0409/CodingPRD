"""Shared pytest fixtures for the Nature Center Education & School Programs API."""

import os

import pytest
import requests

from test_helpers import TEST_USERS, api_client


@pytest.fixture(autouse=True)
def _fresh_http_session():
    """Give every test a brand-new HTTP session.

    The API process is restarted between tests, so pooled connections from a
    previous test would be dead. Rebuilding the session also re-reads the base
    URL in case the harness moved the port.
    """
    api_client.base_url = os.environ.get("API_BASE_URL", api_client.base_url)
    api_client.session = requests.Session()
    yield
    api_client.session.close()


@pytest.fixture
def api():
    """The API client, one method per endpoint declared in the PRD."""
    return api_client


# --- Role headers -------------------------------------------------------------------
# Five roles have opaque actor ids. The two entity-backed roles (Naturalist,
# TeacherContact) only get fallback identities here; ownership-sensitive tests must
# build their headers from a real Educator.id / SchoolPartner.id instead.

@pytest.fixture
def education_director_headers():
    return TEST_USERS["education_director_headers"]


@pytest.fixture
def education_director_alt_headers():
    return TEST_USERS["education_director_alt_headers"]


@pytest.fixture
def curriculum_specialist_headers():
    return TEST_USERS["curriculum_specialist_headers"]


@pytest.fixture
def curriculum_specialist_assessor_headers():
    return TEST_USERS["curriculum_specialist_assessor_headers"]


@pytest.fixture
def booking_coordinator_headers():
    return TEST_USERS["booking_coordinator_headers"]


@pytest.fixture
def stewardship_manager_headers():
    return TEST_USERS["stewardship_manager_headers"]


@pytest.fixture
def grants_officer_headers():
    return TEST_USERS["grants_officer_headers"]


@pytest.fixture
def naturalist_headers():
    return TEST_USERS["naturalist_headers"]


@pytest.fixture
def teacher_contact_headers():
    return TEST_USERS["teacher_contact_headers"]
