"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL into the environment and adds the project
root to PYTHONPATH before invoking pytest, so test_helpers imports cleanly.
Server lifecycle (start/stop/health) is the runner's job, not the tests'.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


# ─── One thin fixture per role from TEST_USERS (PRD §2.1) ───


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def arborist_headers():
    return TEST_USERS["arborist_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
