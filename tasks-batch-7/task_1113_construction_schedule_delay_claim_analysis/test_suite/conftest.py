"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_scheduler_headers"]


@pytest.fixture
def pce_headers():
    return TEST_USERS["project_controls_engineer_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_representative_headers"]


@pytest.fixture
def claims_headers():
    return TEST_USERS["claims_consultant_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["system_admin_headers"]
