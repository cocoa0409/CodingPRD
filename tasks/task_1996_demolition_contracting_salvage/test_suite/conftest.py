"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def contractor_admin_headers():
    return TEST_USERS["contractor_admin_headers"]


@pytest.fixture
def site_supervisor_headers():
    return TEST_USERS["site_supervisor_headers"]


@pytest.fixture
def surveyor_headers():
    return TEST_USERS["surveyor_headers"]


@pytest.fixture
def abatement_supervisor_headers():
    return TEST_USERS["abatement_supervisor_headers"]


@pytest.fixture
def clearance_officer_headers():
    return TEST_USERS["clearance_officer_headers"]


@pytest.fixture
def utility_coordinator_headers():
    return TEST_USERS["utility_coordinator_headers"]


@pytest.fixture
def permit_coordinator_headers():
    return TEST_USERS["permit_coordinator_headers"]


@pytest.fixture
def authority_reviewer_headers():
    return TEST_USERS["authority_reviewer_headers"]


@pytest.fixture
def structural_engineer_headers():
    return TEST_USERS["structural_engineer_headers"]


@pytest.fixture
def peer_review_engineer_headers():
    return TEST_USERS["peer_review_engineer_headers"]


@pytest.fixture
def salvage_estimator_headers():
    return TEST_USERS["salvage_estimator_headers"]


@pytest.fixture
def environmental_monitor_headers():
    return TEST_USERS["environmental_monitor_headers"]


@pytest.fixture
def hauling_dispatcher_headers():
    return TEST_USERS["hauling_dispatcher_headers"]


@pytest.fixture
def municipal_inspector_headers():
    return TEST_USERS["municipal_inspector_headers"]
