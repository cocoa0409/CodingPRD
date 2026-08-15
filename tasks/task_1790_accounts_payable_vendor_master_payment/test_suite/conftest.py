"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def vendor_specialist_headers():
    return TEST_USERS["vendor_specialist_headers"]


@pytest.fixture
def vendor_specialist_2_headers():
    return TEST_USERS["vendor_specialist_2_headers"]


@pytest.fixture
def vendor_manager_headers():
    return TEST_USERS["vendor_manager_headers"]


@pytest.fixture
def vendor_manager_2_headers():
    return TEST_USERS["vendor_manager_2_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def ap_clerk_headers():
    return TEST_USERS["ap_clerk_headers"]


@pytest.fixture
def ap_supervisor_headers():
    return TEST_USERS["ap_supervisor_headers"]


@pytest.fixture
def ap_supervisor_2_headers():
    return TEST_USERS["ap_supervisor_2_headers"]


@pytest.fixture
def ap_manager_headers():
    return TEST_USERS["ap_manager_headers"]


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]


@pytest.fixture
def treasury_analyst_headers():
    return TEST_USERS["treasury_analyst_headers"]


@pytest.fixture
def treasury_manager_headers():
    return TEST_USERS["treasury_manager_headers"]


@pytest.fixture
def treasury_manager_2_headers():
    return TEST_USERS["treasury_manager_2_headers"]


@pytest.fixture
def bank_file_processor_headers():
    return TEST_USERS["bank_file_processor_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
