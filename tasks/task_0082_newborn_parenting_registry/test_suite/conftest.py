"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (test_helpers importable) and the server lifecycle:
the API server is killed and relaunched before every individual test, so every test
starts against an empty database.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_clerk_headers():
    return TEST_USERS["intake_clerk_headers"]


@pytest.fixture
def attending_nurse_headers():
    return TEST_USERS["attending_nurse_headers"]


@pytest.fixture
def neonatologist_headers():
    return TEST_USERS["neonatologist_headers"]


@pytest.fixture
def benefits_coordinator_headers():
    return TEST_USERS["benefits_coordinator_headers"]


@pytest.fixture
def vital_records_officer_headers():
    return TEST_USERS["vital_records_officer_headers"]


@pytest.fixture
def registry_supervisor_headers():
    return TEST_USERS["registry_supervisor_headers"]
