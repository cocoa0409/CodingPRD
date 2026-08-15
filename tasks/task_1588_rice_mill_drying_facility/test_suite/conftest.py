"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def mill_admin_headers():
    return TEST_USERS["mill_admin_headers"]


@pytest.fixture
def merchandiser_headers():
    return TEST_USERS["merchandiser_headers"]


@pytest.fixture
def scale_operator_headers():
    return TEST_USERS["scale_operator_headers"]


@pytest.fixture
def quality_lab_tech_headers():
    return TEST_USERS["quality_lab_tech_headers"]


@pytest.fixture
def dryer_operator_headers():
    return TEST_USERS["dryer_operator_headers"]


@pytest.fixture
def mill_supervisor_headers():
    return TEST_USERS["mill_supervisor_headers"]


@pytest.fixture
def settlement_clerk_headers():
    return TEST_USERS["settlement_clerk_headers"]


@pytest.fixture
def settlement_clerk_2_headers():
    return TEST_USERS["settlement_clerk_2_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def fumigation_tech_headers():
    return TEST_USERS["fumigation_tech_headers"]


@pytest.fixture
def grower_rep_headers():
    return TEST_USERS["grower_rep_headers"]
