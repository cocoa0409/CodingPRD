"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle belongs to the runner: it relaunches the API before every
individual test, so each test starts against an empty database and builds all
of its own state through the declared endpoints.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """API client pointed at the running server."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor_two_headers():
    return TEST_USERS["supervisor_two_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def chw_headers():
    return TEST_USERS["chw_headers"]


@pytest.fixture
def resource_partner_headers():
    return TEST_USERS["resource_partner_headers"]


@pytest.fixture
def no_auth_headers():
    return TEST_USERS["no_auth_headers"]
