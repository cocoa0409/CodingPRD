"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def guide_headers():
    return TEST_USERS["guide_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]
