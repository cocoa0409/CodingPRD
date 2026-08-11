"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def recruiter_headers():
    return TEST_USERS["recruiter_headers"]


@pytest.fixture
def contract_admin_headers():
    return TEST_USERS["contract_admin_headers"]


@pytest.fixture
def credentialing_specialist_headers():
    return TEST_USERS["credentialing_specialist_headers"]


@pytest.fixture
def credentialing_specialist_2_headers():
    return TEST_USERS["credentialing_specialist_2_headers"]


@pytest.fixture
def practice_manager_headers():
    return TEST_USERS["practice_manager_headers"]


@pytest.fixture
def finance_analyst_headers():
    return TEST_USERS["finance_analyst_headers"]


@pytest.fixture
def onboarding_director_headers():
    return TEST_USERS["onboarding_director_headers"]


@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]
