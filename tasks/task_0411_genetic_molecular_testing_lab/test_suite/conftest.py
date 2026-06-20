"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restarting via start.sh before each test). These fixtures
never start/stop/health-check the server.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def accessioning_headers():
    return TEST_USERS["accessioning_headers"]


@pytest.fixture
def molecular_headers():
    return TEST_USERS["molecular_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]
