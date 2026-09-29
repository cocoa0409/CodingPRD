"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def practice_admin_headers():
    return TEST_USERS["practice_admin_headers"]


@pytest.fixture
def referral_coordinator_headers():
    return TEST_USERS["referral_coordinator_headers"]


@pytest.fixture
def patient_navigator_headers():
    return TEST_USERS["patient_navigator_headers"]


@pytest.fixture
def pathologist_headers():
    return TEST_USERS["pathologist_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def quality_officer_headers():
    return TEST_USERS["quality_officer_headers"]


@pytest.fixture
def endoscopist_headers():
    """Fallback `Endoscopist` headers. Ownership-gated calls must instead use
    `make_endoscopist_headers()` with the acting Clinician's real id."""
    return TEST_USERS["endoscopist_headers"]


@pytest.fixture
def patient_headers():
    """Fallback `Patient` headers. Ownership-gated calls must instead use
    `make_patient_headers()` with the acting Patient's real id."""
    return TEST_USERS["patient_headers"]
