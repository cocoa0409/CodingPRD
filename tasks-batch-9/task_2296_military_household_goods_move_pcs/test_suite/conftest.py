"""Shared pytest fixtures for the household-goods move suite.

Every test in this suite runs against a freshly started server with an empty
database, so all state a test needs is built through published endpoints.
"""

import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The endpoint surface of the API under test."""
    return api_client


@pytest.fixture(scope="session")
def service_member_headers():
    return TEST_USERS["service_member_headers"]


@pytest.fixture(scope="session")
def move_counselor_headers():
    return TEST_USERS["move_counselor_headers"]


@pytest.fixture(scope="session")
def move_counselor_alt_headers():
    return TEST_USERS["move_counselor_alt_headers"]


@pytest.fixture(scope="session")
def tsp_coordinator_headers():
    return TEST_USERS["tsp_coordinator_headers"]


@pytest.fixture(scope="session")
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture(scope="session")
def claims_examiner_alt_headers():
    return TEST_USERS["claims_examiner_alt_headers"]


@pytest.fixture(scope="session")
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture(scope="session")
def program_admin_alt_headers():
    return TEST_USERS["program_admin_alt_headers"]
