"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets API_BASE_URL and PYTHONPATH; test_helpers is importable directly.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def landlord_headers():
    return TEST_USERS["landlord_headers"]


@pytest.fixture
def tenant_headers():
    return TEST_USERS["tenant_headers"]


@pytest.fixture
def hearing_officer_headers():
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
