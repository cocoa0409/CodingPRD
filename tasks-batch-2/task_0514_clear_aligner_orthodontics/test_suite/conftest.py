"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def manufacturing_headers():
    return TEST_USERS["manufacturing_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]
