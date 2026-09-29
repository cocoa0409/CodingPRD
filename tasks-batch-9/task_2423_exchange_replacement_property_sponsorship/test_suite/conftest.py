"""Shared pytest fixtures for the suite.

The harness restarts the API and empties the database before every individual
test, so nothing here may assume state written by an earlier test.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api():
    """The single API client used by every test."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def trustee_headers():
    return TEST_USERS["trustee_headers"]


@pytest.fixture
def investor_headers():
    return TEST_USERS["investor_headers"]


@pytest.fixture
def master_tenant_headers():
    return TEST_USERS["master_tenant_headers"]


@pytest.fixture
def qi_headers():
    return TEST_USERS["qi_headers"]
