"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def court_clerk_headers():
    return TEST_USERS["court_clerk_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def probation_officer_headers():
    return TEST_USERS["probation_officer_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def court_admin_headers():
    return TEST_USERS["court_admin_headers"]


@pytest.fixture
def defendant_headers():
    return TEST_USERS["defendant_headers"]
