import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers.test_users import NO_ROLE_HEADERS, UNKNOWN_ROLE_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared API client. Base URL comes from ``API_BASE_URL``."""
    return api_client


@pytest.fixture
def provisioning_engineer_headers():
    return TEST_USERS["provisioning_engineer_headers"]


@pytest.fixture
def provisioning_engineer_2_headers():
    return TEST_USERS["provisioning_engineer_2_headers"]


@pytest.fixture
def provisioning_engineer_3_headers():
    return TEST_USERS["provisioning_engineer_3_headers"]


@pytest.fixture
def facility_manager_headers():
    return TEST_USERS["facility_manager_headers"]


@pytest.fixture
def facility_manager_2_headers():
    return TEST_USERS["facility_manager_2_headers"]


@pytest.fixture
def security_officer_headers():
    return TEST_USERS["security_officer_headers"]


@pytest.fixture
def security_officer_2_headers():
    return TEST_USERS["security_officer_2_headers"]


@pytest.fixture
def billing_operator_headers():
    return TEST_USERS["billing_operator_headers"]


@pytest.fixture
def billing_operator_2_headers():
    return TEST_USERS["billing_operator_2_headers"]


@pytest.fixture
def customer_admin_headers():
    """A ``CustomerAdmin`` whose ``X-User-ID`` owns no customer record, for the
    role-gate and scope-violation cases. Ownership-gated calls must instead build
    headers from the customer under test."""
    return TEST_USERS["customer_admin_headers"]


@pytest.fixture
def no_role_headers():
    return NO_ROLE_HEADERS


@pytest.fixture
def unknown_role_headers():
    return UNKNOWN_ROLE_HEADERS
