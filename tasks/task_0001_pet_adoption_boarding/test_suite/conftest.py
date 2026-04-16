"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def shelter_admin_headers():
    return TEST_USERS["shelter_admin_headers"]


@pytest.fixture
def veterinarian_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def adoption_reviewer_headers():
    return TEST_USERS["adoption_reviewer_headers"]


@pytest.fixture
def adoption_approver_headers():
    return TEST_USERS["adoption_approver_headers"]


@pytest.fixture
def home_visit_inspector_headers():
    return TEST_USERS["home_visit_inspector_headers"]


@pytest.fixture
def boarding_coordinator_headers():
    return TEST_USERS["boarding_coordinator_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def adopter_headers():
    return TEST_USERS["adopter_headers"]
