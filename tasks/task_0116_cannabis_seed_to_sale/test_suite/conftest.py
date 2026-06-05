"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and starts a fresh
server (empty database) before every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def state_regulator_headers():
    return TEST_USERS["state_regulator_headers"]


@pytest.fixture
def cultivator_headers():
    return TEST_USERS["cultivator_headers"]


@pytest.fixture
def qa_lab_headers():
    return TEST_USERS["qa_lab_headers"]


@pytest.fixture
def compliance_manager_headers():
    return TEST_USERS["compliance_manager_headers"]


@pytest.fixture
def distribution_agent_headers():
    return TEST_USERS["distribution_agent_headers"]


@pytest.fixture
def budtender_headers():
    return TEST_USERS["budtender_headers"]


@pytest.fixture
def inventory_auditor_headers():
    return TEST_USERS["inventory_auditor_headers"]
