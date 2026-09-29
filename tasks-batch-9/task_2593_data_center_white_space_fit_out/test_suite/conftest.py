"""Shared pytest fixtures for the white space fit-out suite.

The server is restarted before every test, so each test builds all of its own
preconditions from an empty database.
"""
import pytest

from test_helpers import api_client
from test_helpers.api_errors import HTTP_STATUS_CODES  # registers the status map
from test_helpers.test_users import TEST_USERS


@pytest.fixture(scope="session")
def api():
    """The API client, pointed at API_BASE_URL."""
    return api_client


@pytest.fixture(scope="session")
def error_status_map():
    """The PRD error-identifier to HTTP-status mapping."""
    return HTTP_STATUS_CODES


@pytest.fixture
def facility_planner():
    return TEST_USERS["facility_planner_headers"]


@pytest.fixture
def electrical_contractor():
    return TEST_USERS["electrical_contractor_headers"]


@pytest.fixture
def mechanical_contractor():
    return TEST_USERS["mechanical_contractor_headers"]


@pytest.fixture
def commissioning_agent():
    return TEST_USERS["commissioning_agent_headers"]


@pytest.fixture
def commissioning_agent_2():
    return TEST_USERS["commissioning_agent_2_headers"]


@pytest.fixture
def witness_authority():
    return TEST_USERS["witness_authority_headers"]


@pytest.fixture
def change_manager():
    return TEST_USERS["change_manager_headers"]


@pytest.fixture
def change_manager_2():
    return TEST_USERS["change_manager_2_headers"]


@pytest.fixture
def operations_manager():
    return TEST_USERS["operations_manager_headers"]


@pytest.fixture
def security_administrator():
    return TEST_USERS["security_administrator_headers"]
