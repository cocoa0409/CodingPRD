"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def farm_manager_headers():
    return TEST_USERS["farm_manager_headers"]


@pytest.fixture
def compost_supervisor_headers():
    return TEST_USERS["compost_supervisor_headers"]


@pytest.fixture
def grading_inspector_headers():
    return TEST_USERS["grading_inspector_headers"]


@pytest.fixture
def harvest_crew_lead_headers():
    return TEST_USERS["harvest_crew_lead_headers"]


@pytest.fixture
def payroll_clerk_headers():
    return TEST_USERS["payroll_clerk_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def buyer_portal_headers():
    return TEST_USERS["buyer_portal_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
