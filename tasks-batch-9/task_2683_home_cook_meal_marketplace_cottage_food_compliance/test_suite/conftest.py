"""Shared pytest fixtures for the home-cook meal marketplace API suite.

The harness restarts the API server before every test, so no fixture may assume
data created by another test. Every fixture below is either a stateless client
or a header dictionary.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The shared API client. Stateless, so a session scope is safe."""
    return api_client


@pytest.fixture
def cook_headers():
    return TEST_USERS["cook_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def diner_headers():
    return TEST_USERS["diner_headers"]


@pytest.fixture
def diner_two_headers():
    return TEST_USERS["diner_two_headers"]


@pytest.fixture
def diner_three_headers():
    return TEST_USERS["diner_three_headers"]


@pytest.fixture
def diner_four_headers():
    return TEST_USERS["diner_four_headers"]


@pytest.fixture
def compliance_reviewer_headers():
    return TEST_USERS["compliance_reviewer_headers"]


@pytest.fixture
def compliance_reviewer_two_headers():
    return TEST_USERS["compliance_reviewer_two_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def safety_officer_two_headers():
    return TEST_USERS["safety_officer_two_headers"]


@pytest.fixture
def finance_operator_headers():
    return TEST_USERS["finance_operator_headers"]


@pytest.fixture
def finance_operator_two_headers():
    return TEST_USERS["finance_operator_two_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
