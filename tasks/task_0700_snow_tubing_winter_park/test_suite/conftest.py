"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable directly. The server
lifecycle (start/stop/health) is owned by prd-bench-local-runner; these fixtures
only expose the API client and pre-built role headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["park_operator_headers"]


@pytest.fixture
def marshal_headers():
    return TEST_USERS["safety_marshal_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def guest_patron_headers():
    return TEST_USERS["guest_patron_headers"]


@pytest.fixture
def group_host_headers():
    return TEST_USERS["group_host_headers"]
