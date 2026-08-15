"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests start against an empty
database at the default logical clock 2026-08-01T00:00:00Z (PRD §2.4).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def responder_headers():
    return TEST_USERS["responder_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]
