"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restarting it before every test against an empty database).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def homeowner_client_headers():
    return TEST_USERS["homeowner_client_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]
