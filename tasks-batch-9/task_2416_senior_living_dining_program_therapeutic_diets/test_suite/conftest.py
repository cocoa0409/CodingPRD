"""Shared pytest fixtures for the senior-living dining program suite."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """One HTTP client for the whole session."""
    return ApiClient()


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def clinical_staff_headers():
    return TEST_USERS["clinical_staff_headers"]


@pytest.fixture
def clinical_staff_alt_headers():
    return TEST_USERS["clinical_staff_alt_headers"]


@pytest.fixture
def dietitian_headers():
    return TEST_USERS["dietitian_headers"]


@pytest.fixture
def dietitian_alt_headers():
    return TEST_USERS["dietitian_alt_headers"]


@pytest.fixture
def dining_manager_headers():
    return TEST_USERS["dining_manager_headers"]


@pytest.fixture
def kitchen_lead_headers():
    return TEST_USERS["kitchen_lead_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]
