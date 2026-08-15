"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def collections_headers():
    return TEST_USERS["collections_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def patient_headers():
    """Shared Patient headers — only for calls that are not ownership-gated.
    For ownership-gated calls use make_patient_headers(patient["id"])."""
    return TEST_USERS["patient_headers"]
