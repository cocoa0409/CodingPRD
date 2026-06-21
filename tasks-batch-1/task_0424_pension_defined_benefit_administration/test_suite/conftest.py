"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plan_sponsor_headers():
    return TEST_USERS["plan_sponsor_headers"]


@pytest.fixture
def plan_actuary_headers():
    return TEST_USERS["plan_actuary_headers"]


@pytest.fixture
def benefits_admin_headers():
    return TEST_USERS["benefits_admin_headers"]


@pytest.fixture
def benefits_admin_a_headers():
    return TEST_USERS["benefits_admin_a_headers"]


@pytest.fixture
def benefits_admin_b_headers():
    return TEST_USERS["benefits_admin_b_headers"]
