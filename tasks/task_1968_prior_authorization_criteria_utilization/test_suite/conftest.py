"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def um_admin_headers():
    return TEST_USERS["um_admin_headers"]


@pytest.fixture
def policy_editor_headers():
    return TEST_USERS["policy_editor_headers"]


@pytest.fixture
def intake_specialist_headers():
    return TEST_USERS["intake_specialist_headers"]


@pytest.fixture
def clinical_reviewer_headers():
    return TEST_USERS["clinical_reviewer_headers"]


@pytest.fixture
def medical_director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def appeals_clerk_headers():
    return TEST_USERS["appeals_clerk_headers"]


@pytest.fixture
def appeals_reviewer_headers():
    return TEST_USERS["appeals_reviewer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
