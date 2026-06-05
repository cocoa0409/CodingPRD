"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and injects
API_BASE_URL. The server lifecycle (restart-before-each-test, empty DB) is the
runner's responsibility; tests assume the server is already running.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def rider_headers():
    """Shared (non-ownership) Rider headers. Ownership-gated tests build their own
    via make_rider_headers(rider['id'])."""
    return TEST_USERS["rider_headers"]


@pytest.fixture
def technician_headers():
    """Shared (non-ownership) Technician headers. Ownership-gated tests build their
    own via make_technician_headers(tech['id'])."""
    return TEST_USERS["technician_headers"]
