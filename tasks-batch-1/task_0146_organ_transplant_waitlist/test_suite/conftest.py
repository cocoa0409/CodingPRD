"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages server
lifecycle (the server is restarted before every test). Tests assume an empty
database and build all preconditions from scratch.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """UNOSAdmin (opaque identity)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def center_headers():
    """Shared TransplantCenter headers — for non-ownership tests only."""
    return TEST_USERS["center_headers"]


@pytest.fixture
def opo_headers():
    """Shared OrganProcurementOrg headers — for non-ownership tests only."""
    return TEST_USERS["opo_headers"]
