"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (test_helpers importable) and server lifecycle.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def flow_admin_headers():
    return TEST_USERS["flow_admin_headers"]


@pytest.fixture
def bed_control_headers():
    return TEST_USERS["bed_control_headers"]


@pytest.fixture
def charge_nurse_headers():
    return TEST_USERS["charge_nurse_headers"]


@pytest.fixture
def transfer_agent_headers():
    return TEST_USERS["transfer_agent_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def evs_tech_headers():
    return TEST_USERS["evs_tech_headers"]
