"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts against
a freshly-restarted (empty-database) API per the per-test-server isolation
contract (PRD §3.10 clock state also resets each test).
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


@pytest.fixture
def case_manager_headers() -> dict:
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def evaluator_headers() -> dict:
    return TEST_USERS["evaluator_headers"]


@pytest.fixture
def parent_headers() -> dict:
    return TEST_USERS["parent_headers"]
