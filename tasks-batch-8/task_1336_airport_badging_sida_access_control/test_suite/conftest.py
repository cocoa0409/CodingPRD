"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def sponsor_signatory_headers():
    return TEST_USERS["sponsor_signatory_headers"]


@pytest.fixture
def badging_officer_headers():
    return TEST_USERS["badging_officer_headers"]


@pytest.fixture
def security_manager_headers():
    return TEST_USERS["security_manager_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def access_control_headers():
    return TEST_USERS["access_control_headers"]
