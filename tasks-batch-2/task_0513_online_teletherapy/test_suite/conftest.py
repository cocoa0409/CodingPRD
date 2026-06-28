"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; these fixtures only wire
test_helpers into pytest.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def therapist_headers():
    return TEST_USERS["therapist_headers"]


@pytest.fixture
def clinical_admin_headers():
    return TEST_USERS["clinical_admin_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]
