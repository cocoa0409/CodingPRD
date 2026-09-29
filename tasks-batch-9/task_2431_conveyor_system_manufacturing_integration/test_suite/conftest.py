"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def project_director_headers():
    return TEST_USERS["project_director_headers"]


@pytest.fixture
def design_engineer_headers():
    return TEST_USERS["design_engineer_headers"]


@pytest.fixture
def shop_supervisor_headers():
    return TEST_USERS["shop_supervisor_headers"]


@pytest.fixture
def site_manager_headers():
    return TEST_USERS["site_manager_headers"]


@pytest.fixture
def customer_rep_headers():
    return TEST_USERS["customer_rep_headers"]
