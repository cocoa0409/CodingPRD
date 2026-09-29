"""Shared pytest fixtures for the Hazard Mitigation Buyout Program compliance suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The API client. Importing test_helpers also registers the error status map."""
    return api_client


@pytest.fixture
def program_administrator_headers():
    return TEST_USERS["program_administrator_headers"]


@pytest.fixture
def bca_validator_headers():
    return TEST_USERS["bca_validator_headers"]


@pytest.fixture
def project_approver_headers():
    return TEST_USERS["project_approver_headers"]


@pytest.fixture
def staff_appraiser_headers():
    return TEST_USERS["staff_appraiser_headers"]


@pytest.fixture
def staff_appraiser_2_headers():
    return TEST_USERS["staff_appraiser_2_headers"]


@pytest.fixture
def review_appraiser_headers():
    return TEST_USERS["review_appraiser_headers"]


@pytest.fixture
def review_appraiser_2_headers():
    return TEST_USERS["review_appraiser_2_headers"]


@pytest.fixture
def relocation_specialist_headers():
    return TEST_USERS["relocation_specialist_headers"]


@pytest.fixture
def compliance_monitor_headers():
    return TEST_USERS["compliance_monitor_headers"]


@pytest.fixture
def compliance_monitor_2_headers():
    return TEST_USERS["compliance_monitor_2_headers"]


@pytest.fixture
def subrecipient_coordinator_headers():
    """The role-only coordinator identity, for calls that never resolve a project."""
    return TEST_USERS["subrecipient_coordinator_headers"]
