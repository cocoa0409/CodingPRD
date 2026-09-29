"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def finance_admin_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def transplant_coordinator_headers():
    return TEST_USERS["transplant_coordinator_headers"]


@pytest.fixture
def donor_advocate_headers():
    return TEST_USERS["donor_advocate_headers"]


@pytest.fixture
def evaluation_reviewer_headers():
    return TEST_USERS["evaluation_reviewer_headers"]


@pytest.fixture
def quality_officer_headers():
    return TEST_USERS["quality_officer_headers"]
