"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle and PYTHONPATH are managed by prd-bench-local-runner.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def catalog_admin_headers():
    return TEST_USERS["catalog_admin_headers"]


@pytest.fixture
def grading_agent_headers():
    return TEST_USERS["grading_agent_headers"]


@pytest.fixture
def finance_operator_headers():
    return TEST_USERS["finance_operator_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
