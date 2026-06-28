"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restarting it before every test against an empty database).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]
