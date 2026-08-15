"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def yard_admin_headers():
    return TEST_USERS["yard_admin_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def commercial_approver_headers():
    return TEST_USERS["commercial_approver_headers"]


@pytest.fixture
def shipowner_rep_headers():
    return TEST_USERS["shipowner_rep_headers"]


@pytest.fixture
def class_surveyor_headers():
    return TEST_USERS["class_surveyor_headers"]


@pytest.fixture
def environmental_officer_headers():
    return TEST_USERS["environmental_officer_headers"]


@pytest.fixture
def subcontractor_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["subcontractor_headers"]
