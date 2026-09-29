"""Shared pytest fixtures for the research security disclosure suite.

The harness restarts the API server before every individual test, so each test
begins against an empty database and a logical clock sitting at its mandatory
startup default of 2026-08-01T00:00:00Z. Every precondition is therefore built
from scratch through the documented endpoints.
"""

import pytest

from test_helpers import TEST_USERS, api_client, make_investigator_headers


@pytest.fixture
def api():
    """The API client bound to the running server."""
    return api_client


@pytest.fixture
def admin_headers():
    """SystemAdmin caller: registers investigators, projects, personnel and the award."""
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def rso_headers():
    """ResearchSecurityOfficer caller: the research security office proper."""
    return TEST_USERS["rso_headers"]


@pytest.fixture
def rso_second_headers():
    """A second ResearchSecurityOfficer, for checks that bind a user rather than a role."""
    return TEST_USERS["rso_second_headers"]


@pytest.fixture
def cro_headers():
    """ConflictReviewOfficial caller: adjudicates items and manages plans."""
    return TEST_USERS["cro_headers"]


@pytest.fixture
def cro_second_headers():
    """A second ConflictReviewOfficial."""
    return TEST_USERS["cro_second_headers"]


@pytest.fixture
def liaison_headers():
    """AgencyLiaison caller: transmits incident notifications and nothing else."""
    return TEST_USERS["liaison_headers"]


@pytest.fixture
def liaison_second_headers():
    """A second AgencyLiaison."""
    return TEST_USERS["liaison_second_headers"]


@pytest.fixture
def investigator_headers_factory():
    """Build Investigator headers whose X-User-ID is a real investigator id."""
    return make_investigator_headers
