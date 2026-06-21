"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages server
lifecycle (restart before every test) — conftest only wires up fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def league_admin_headers():
    return TEST_USERS["league_admin_headers"]


@pytest.fixture
def assignor_headers():
    return TEST_USERS["assignor_headers"]


@pytest.fixture
def evaluator_headers():
    return TEST_USERS["evaluator_headers"]


@pytest.fixture
def official_headers():
    return TEST_USERS["official_headers"]
