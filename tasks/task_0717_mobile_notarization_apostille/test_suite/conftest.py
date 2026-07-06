"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and manages the server lifecycle (restart before every test). These fixtures just
wire the helpers into pytest.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def apostille_clerk_headers():
    return TEST_USERS["apostille_clerk_headers"]


@pytest.fixture
def viewer_headers():
    return TEST_USERS["viewer_headers"]


@pytest.fixture
def notary_headers():
    return TEST_USERS["notary_headers"]
