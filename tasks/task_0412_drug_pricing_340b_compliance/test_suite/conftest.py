"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH, so test_helpers is importable
directly. The server database is empty at the start of every test (the server is
restarted before each test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def hrsa_auditor_headers():
    return TEST_USERS["hrsa_auditor_headers"]


@pytest.fixture
def pharmacy_operator_headers():
    return TEST_USERS["pharmacy_operator_headers"]
