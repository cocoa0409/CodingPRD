"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-before-each-test) is owned by
prd-bench-local-runner; these fixtures only expose the shared client and
pre-built role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner restarts the server before each test."""
    return api_client


@pytest.fixture
def caseworker_headers():
    return TEST_USERS["caseworker_headers"]


@pytest.fixture
def programadmin_headers():
    return TEST_USERS["programadmin_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def vendoragent_headers():
    return TEST_USERS["vendoragent_headers"]
