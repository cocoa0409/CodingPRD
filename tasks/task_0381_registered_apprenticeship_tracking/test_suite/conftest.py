"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so `test_helpers` is importable) and the server
lifecycle; this file only wires up fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registration_agency_headers():
    return TEST_USERS["registration_agency_headers"]


@pytest.fixture
def training_coordinator_headers():
    return TEST_USERS["training_coordinator_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_headers"]


@pytest.fixture
def apprentice_headers():
    return TEST_USERS["apprentice_headers"]
