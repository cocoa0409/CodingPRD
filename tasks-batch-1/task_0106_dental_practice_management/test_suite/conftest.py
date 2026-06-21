"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, and kills/relaunches
the server before every test, so each test starts against an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]
