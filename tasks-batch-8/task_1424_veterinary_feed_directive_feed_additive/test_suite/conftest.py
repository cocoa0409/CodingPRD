"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, readiness, API_BASE_URL, PYTHONPATH) is managed
by prd-bench-local-runner; these fixtures only bridge test_helpers into tests.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def veterinarian_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def feed_mill_operator_headers():
    return TEST_USERS["feed_mill_operator_headers"]


@pytest.fixture
def producer_headers():
    return TEST_USERS["producer_headers"]
