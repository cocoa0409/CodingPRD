"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def sponsor_admin_headers():
    return TEST_USERS["sponsor_admin_headers"]


@pytest.fixture
def sponsor_admin_2_headers():
    return TEST_USERS["sponsor_admin_2_headers"]


@pytest.fixture
def tpa_specialist_headers():
    return TEST_USERS["tpa_specialist_headers"]


@pytest.fixture
def plan_auditor_headers():
    return TEST_USERS["plan_auditor_headers"]


@pytest.fixture
def engagement_manager_headers():
    return TEST_USERS["engagement_manager_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]
