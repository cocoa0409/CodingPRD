"""Shared pytest fixtures for the Pro Bono Matching API test suite."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client, TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The HTTP client for the service under test."""
    return api_client


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def program_manager_2_headers():
    return TEST_USERS["program_manager_2_headers"]


@pytest.fixture
def scoping_specialist_headers():
    return TEST_USERS["scoping_specialist_headers"]


@pytest.fixture
def scoping_specialist_2_headers():
    return TEST_USERS["scoping_specialist_2_headers"]


@pytest.fixture
def quality_reviewer_headers():
    return TEST_USERS["quality_reviewer_headers"]


@pytest.fixture
def quality_reviewer_2_headers():
    return TEST_USERS["quality_reviewer_2_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def partner_contact_headers():
    return TEST_USERS["partner_contact_headers"]
