"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the harness."""
    return api_client


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]


@pytest.fixture
def hearing_professional_headers():
    return TEST_USERS["hearing_professional_headers"]


@pytest.fixture
def licensed_audiologist_headers():
    return TEST_USERS["licensed_audiologist_headers"]


@pytest.fixture
def care_ops_headers():
    return TEST_USERS["care_ops_headers"]


@pytest.fixture
def reimbursement_headers():
    return TEST_USERS["reimbursement_headers"]


@pytest.fixture
def repair_tech_headers():
    return TEST_USERS["repair_tech_headers"]


@pytest.fixture
def firmware_engineer_headers():
    return TEST_USERS["firmware_engineer_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
