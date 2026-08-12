"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def rights_admin_headers():
    return TEST_USERS["rights_admin_headers"]


@pytest.fixture
def licensing_officer_headers():
    return TEST_USERS["licensing_officer_headers"]


@pytest.fixture
def materials_clerk_headers():
    return TEST_USERS["materials_clerk_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]
