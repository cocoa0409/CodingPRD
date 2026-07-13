"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the
server lifecycle (restarting via start.sh before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def enrollment_specialist_headers():
    return TEST_USERS["enrollment_specialist_headers"]


@pytest.fixture
def family_services_worker_headers():
    return TEST_USERS["family_services_worker_headers"]


@pytest.fixture
def family_headers():
    return TEST_USERS["family_headers"]
