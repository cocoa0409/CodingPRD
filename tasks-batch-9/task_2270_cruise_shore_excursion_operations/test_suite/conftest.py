"""Shared pytest fixtures for the Cruise Shore Excursions suite.

The harness restarts the API server before each test, so no state survives from
one test to the next and nothing here needs to clean up.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.test_users import TEST_USERS


@pytest.fixture
def api():
    """The API client every test drives the service through.

    Function-scoped on purpose: the harness restarts the API server before every
    test, so a client whose connection pool outlived the previous server would
    hand the next test a dead keep-alive socket.  A fresh client per test always
    dials the live server.
    """
    client = ApiClient()
    try:
        yield client
    finally:
        client.session.close()


@pytest.fixture
def guest_headers():
    """Fallback Guest identity — only for calls that never touch ownership.
    Ownership-gated calls must use make_guest_headers(guest["id"])."""
    return TEST_USERS["guest_headers"]


@pytest.fixture
def desk_headers():
    return TEST_USERS["desk_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def vetting_officer_headers():
    return TEST_USERS["vetting_officer_headers"]


@pytest.fixture
def auditor_headers():
    """The officer who conducts audits; barred from approving that operator."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def second_auditor_headers():
    return TEST_USERS["second_auditor_headers"]


@pytest.fixture
def port_agent_headers():
    return TEST_USERS["port_agent_headers"]


@pytest.fixture
def risk_officer_headers():
    """The officer who opens claims; barred from adjudicating them."""
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def second_risk_officer_headers():
    return TEST_USERS["second_risk_officer_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]
