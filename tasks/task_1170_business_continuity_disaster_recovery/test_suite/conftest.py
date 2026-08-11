"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def resilience_admin_headers():
    return TEST_USERS["resilience_admin_headers"]


@pytest.fixture
def bia_analyst_headers():
    return TEST_USERS["bia_analyst_headers"]


@pytest.fixture
def plan_author_headers():
    return TEST_USERS["plan_author_headers"]


@pytest.fixture
def plan_approver_headers():
    return TEST_USERS["plan_approver_headers"]


@pytest.fixture
def risk_committee_headers():
    return TEST_USERS["risk_committee_headers"]


@pytest.fixture
def exercise_officer_headers():
    return TEST_USERS["exercise_officer_headers"]


@pytest.fixture
def site_coordinator_headers():
    return TEST_USERS["site_coordinator_headers"]


@pytest.fixture
def vendor_manager_headers():
    return TEST_USERS["vendor_manager_headers"]


@pytest.fixture
def crisis_officer_headers():
    return TEST_USERS["crisis_officer_headers"]


@pytest.fixture
def attestation_signer_headers():
    return TEST_USERS["attestation_signer_headers"]
