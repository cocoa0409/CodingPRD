"""Shared pytest fixtures.

Thin bridge onto ``test_helpers``: the client and one fixture per declared role.
Every test starts against a freshly launched server with an empty database and a
logical clock reading its startup default, so no cleanup fixture is needed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import TEST_USERS, ApiClient  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The API client used by every test."""
    return ApiClient()


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def property_manager_2_headers():
    return TEST_USERS["property_manager_2_headers"]


@pytest.fixture
def maintenance_tech_headers():
    return TEST_USERS["maintenance_tech_headers"]


@pytest.fixture
def environmental_specialist_headers():
    return TEST_USERS["environmental_specialist_headers"]


@pytest.fixture
def environmental_specialist_2_headers():
    return TEST_USERS["environmental_specialist_2_headers"]


@pytest.fixture
def installation_housing_office_headers():
    return TEST_USERS["installation_housing_office_headers"]


@pytest.fixture
def installation_housing_office_2_headers():
    return TEST_USERS["installation_housing_office_2_headers"]


@pytest.fixture
def service_member_headers():
    """Placeholder sponsor headers — never use where an ownership check runs."""
    return TEST_USERS["service_member_headers"]
