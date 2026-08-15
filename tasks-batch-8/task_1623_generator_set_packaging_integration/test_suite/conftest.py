"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, reset_clock


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture(autouse=True)
def _restore_clock():
    """Return the logical clock to its startup default after each test that moved it."""
    yield
    try:
        reset_clock()
    except Exception:
        pass


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def sales_engineer_headers():
    return TEST_USERS["sales_engineer_headers"]


@pytest.fixture
def application_engineer_headers():
    return TEST_USERS["application_engineer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def test_engineer_headers():
    return TEST_USERS["test_engineer_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def field_service_manager_headers():
    return TEST_USERS["field_service_manager_headers"]


@pytest.fixture
def customer_contact_headers():
    return TEST_USERS["customer_contact_headers"]
