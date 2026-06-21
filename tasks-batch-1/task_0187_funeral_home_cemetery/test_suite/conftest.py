"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, readiness, per-test restart) is owned by the
prd-bench-local-runner. These fixtures only expose the API client and the
pre-built role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def arranger_headers():
    return TEST_USERS["arranger_headers"]


@pytest.fixture
def trust_officer_headers():
    return TEST_USERS["trust_officer_headers"]


@pytest.fixture
def cemetery_clerk_headers():
    return TEST_USERS["cemetery_clerk_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]
