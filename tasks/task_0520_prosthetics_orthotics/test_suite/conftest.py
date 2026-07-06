"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable without sys.path hacks,
and manages server lifecycle (the server is killed and relaunched before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def practitioner_headers():
    return TEST_USERS["practitioner_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]
