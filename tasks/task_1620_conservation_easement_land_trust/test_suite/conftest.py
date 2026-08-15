"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the server is already
running and reachable at API_BASE_URL when these tests execute.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner owns server start/stop."""
    return api_client


@pytest.fixture
def trust_admin_headers():
    return TEST_USERS["trust_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def field_monitor_headers():
    return TEST_USERS["field_monitor_headers"]


@pytest.fixture
def board_reviewer_headers():
    return TEST_USERS["board_reviewer_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def landowner_headers():
    # Fallback shared identity; ownership-gated landowner calls must build
    # per-instance headers with make_landowner_headers(<landowner id>).
    return TEST_USERS["landowner_headers"]
