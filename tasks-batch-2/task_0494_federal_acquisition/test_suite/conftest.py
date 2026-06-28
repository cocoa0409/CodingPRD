"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def co_headers():
    """ContractingOfficer (opaque operator)."""
    return TEST_USERS["co_headers"]


@pytest.fixture
def auditor_headers():
    """Auditor (opaque, read-only)."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def vendor_headers():
    """Vendor fallback headers — for non-ownership tests only (bad payload / auth)."""
    return TEST_USERS["vendor_headers"]
