"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and injects the
API base URL into the shared client. Tests get a session-scoped api client and
ready-made role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def clerk2_headers():
    return TEST_USERS["clerk2_headers"]


@pytest.fixture
def cpa_headers():
    return TEST_USERS["cpa_headers"]


@pytest.fixture
def cpa2_headers():
    return TEST_USERS["cpa2_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]
