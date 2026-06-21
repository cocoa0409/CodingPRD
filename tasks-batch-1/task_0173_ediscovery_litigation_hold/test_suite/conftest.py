"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def legalops_headers():
    return TEST_USERS["legalops_headers"]


@pytest.fixture
def reviewlead_headers():
    return TEST_USERS["reviewlead_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def producer_headers():
    return TEST_USERS["producer_headers"]


@pytest.fixture
def custodian_headers():
    return TEST_USERS["custodian_headers"]
