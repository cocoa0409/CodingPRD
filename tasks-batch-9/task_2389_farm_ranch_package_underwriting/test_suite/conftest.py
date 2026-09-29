"""Shared pytest fixtures for the farm and ranch package underwriting suite.

The API server is restarted before each individual test, so every fixture here
is function scoped: each test builds all of its preconditions from an empty
database through the routes the PRD declares.
"""

import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture
def api():
    """The typed API client."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def underwriter_alt_headers():
    return TEST_USERS["underwriter_headers_alt"]


@pytest.fixture
def senior_underwriter_headers():
    return TEST_USERS["senior_underwriter_headers"]


@pytest.fixture
def senior_underwriter_alt_headers():
    return TEST_USERS["senior_underwriter_headers_alt"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
