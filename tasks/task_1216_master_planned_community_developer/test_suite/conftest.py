"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def declarant_executive_headers():
    return TEST_USERS["declarant_executive_headers"]


@pytest.fixture
def declarant_controller_headers():
    return TEST_USERS["declarant_controller_headers"]


@pytest.fixture
def association_director_headers():
    return TEST_USERS["association_director_headers"]


@pytest.fixture
def design_reviewer_headers():
    return TEST_USERS["design_reviewer_headers"]


@pytest.fixture
def lifestyle_coordinator_headers():
    return TEST_USERS["lifestyle_coordinator_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def builder_rep_headers():
    return TEST_USERS["builder_rep_headers"]


@pytest.fixture
def homeowner_resident_headers():
    return TEST_USERS["homeowner_resident_headers"]


@pytest.fixture
def owner_director_headers():
    return TEST_USERS["owner_director_headers"]
