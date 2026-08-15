"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def safety_manager_headers():
    return TEST_USERS["safety_manager_headers"]


@pytest.fixture
def site_superintendent_headers():
    return TEST_USERS["site_superintendent_headers"]


@pytest.fixture
def safety_inspector_headers():
    return TEST_USERS["safety_inspector_headers"]


@pytest.fixture
def safety_inspector_two_headers():
    return TEST_USERS["safety_inspector_two_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def subcontractor_rep_headers():
    return TEST_USERS["subcontractor_rep_headers"]
