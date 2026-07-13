"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner restarts the API server (empty database) before
every individual test, so all fixtures below are function-scoped and build
their own state from scratch.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
