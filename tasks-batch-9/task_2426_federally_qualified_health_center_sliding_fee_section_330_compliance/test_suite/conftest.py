"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle and the empty store each test starts from are owned by the
runner; these fixtures only hand out the shared client and the pre-built role
headers.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def board_chair_headers():
    """A chair identity that holds no seated seat anywhere."""
    return TEST_USERS["board_chair_headers"]


@pytest.fixture
def eligibility_verifier_headers():
    return TEST_USERS["eligibility_verifier_headers"]


@pytest.fixture
def patient_services_rep_headers():
    return TEST_USERS["patient_services_rep_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def project_officer_headers():
    return TEST_USERS["project_officer_headers"]
