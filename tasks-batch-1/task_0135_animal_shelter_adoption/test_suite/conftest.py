"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def shelter_admin_headers():
    return TEST_USERS["shelter_admin_headers"]


@pytest.fixture
def intake_officer_headers():
    return TEST_USERS["intake_officer_headers"]


@pytest.fixture
def veterinarian_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def adoption_counselor_headers():
    return TEST_USERS["adoption_counselor_headers"]


@pytest.fixture
def foster_coordinator_headers():
    return TEST_USERS["foster_coordinator_headers"]


@pytest.fixture
def adopter_headers():
    return TEST_USERS["adopter_headers"]
