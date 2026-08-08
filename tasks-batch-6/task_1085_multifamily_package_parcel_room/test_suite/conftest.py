"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner manages PYTHONPATH and the server lifecycle (it restarts the
server, resetting DB + logical clock, before every individual test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    """PropertyManager (opaque)."""
    return TEST_USERS["pm_headers"]


@pytest.fixture
def concierge_headers():
    """ConciergeStaff (opaque)."""
    return TEST_USERS["concierge_headers"]


@pytest.fixture
def pms_headers():
    """PmsIntegration (opaque)."""
    return TEST_USERS["pms_headers"]


@pytest.fixture
def resident_headers():
    """Resident (entity_backed) shared fallback — non-ownership tests only."""
    return TEST_USERS["resident_headers"]


@pytest.fixture
def carrier_headers():
    """Carrier (entity_backed) shared fallback — non-ownership tests only."""
    return TEST_USERS["carrier_headers"]
