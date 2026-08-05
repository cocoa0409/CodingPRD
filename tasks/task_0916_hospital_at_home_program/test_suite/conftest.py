"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle is owned by the runner: it relaunches the API before every
individual test, so each test starts against an empty database and builds all of
its own state through the declared endpoints.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers.test_users import NO_AUTH_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """API client pointed at the running server."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def admitting_physician_headers():
    return TEST_USERS["admitting_physician_headers"]


@pytest.fixture
def field_nurse_headers():
    return TEST_USERS["field_nurse_headers"]


@pytest.fixture
def community_paramedic_headers():
    return TEST_USERS["community_paramedic_headers"]


@pytest.fixture
def pharmacy_authorizer_headers():
    return TEST_USERS["pharmacy_authorizer_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def billing_analyst_headers():
    return TEST_USERS["billing_analyst_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
