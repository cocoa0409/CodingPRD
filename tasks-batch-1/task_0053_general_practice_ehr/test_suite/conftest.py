"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires up
fixtures. The database is empty at the start of every test (the runner restarts
the server before each test), so every test builds its own preconditions.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def frontdesk_headers():
    return TEST_USERS["frontdesk_headers"]


@pytest.fixture
def biller_headers():
    return TEST_USERS["biller_headers"]


@pytest.fixture
def quality_headers():
    return TEST_USERS["quality_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]
