"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file just wires the
PRD-specific helpers into pytest fixtures.
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
def proctor_headers():
    return TEST_USERS["proctor_headers"]


@pytest.fixture
def review_officer_headers():
    return TEST_USERS["review_officer_headers"]


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]
