"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def enrollment_specialist_headers():
    return TEST_USERS["enrollment_specialist_headers"]


@pytest.fixture
def payer_representative_headers():
    return TEST_USERS["payer_representative_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]
