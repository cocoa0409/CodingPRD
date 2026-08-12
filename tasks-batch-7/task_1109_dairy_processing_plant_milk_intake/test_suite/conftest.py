"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart per test) is managed by
prd-bench-local-runner; these fixtures only wire up the client and roles.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is guaranteed reachable."""
    return api_client


@pytest.fixture
def plant_controller_headers():
    return TEST_USERS["plant_controller_headers"]


@pytest.fixture
def qa_manager_headers():
    return TEST_USERS["qa_manager_headers"]


@pytest.fixture
def lab_technician_headers():
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def pasteurizer_operator_headers():
    return TEST_USERS["pasteurizer_operator_headers"]


@pytest.fixture
def state_inspector_headers():
    return TEST_USERS["state_inspector_headers"]
