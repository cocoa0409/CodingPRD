"""Shared pytest fixtures for the Farmland Preservation Easement Purchase suite.

Every test runs against a freshly restarted server with an empty database and a
logical clock reading its unset default of 2026-08-01T00:00:00Z (PRD §2.5), so
each test builds all of its own preconditions through the public endpoints.
"""

import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The API client, one method per endpoint in the PRD's endpoint table."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def program_admin_alt_headers():
    return TEST_USERS["program_admin_alt_headers"]


@pytest.fixture
def acquisition_officer_headers():
    return TEST_USERS["acquisition_officer_headers"]


@pytest.fixture
def acquisition_officer_alt_headers():
    return TEST_USERS["acquisition_officer_alt_headers"]


@pytest.fixture
def appraisal_reviewer_headers():
    return TEST_USERS["appraisal_reviewer_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def appraiser_alt_headers():
    return TEST_USERS["appraiser_alt_headers"]


@pytest.fixture
def stewardship_monitor_headers():
    return TEST_USERS["stewardship_monitor_headers"]


@pytest.fixture
def unbound_landowner_headers():
    """Landowner headers whose X-User-ID names no Landowner row.

    Usable only by tests that never reach an ownership check.
    """
    return TEST_USERS["landowner_headers"]
