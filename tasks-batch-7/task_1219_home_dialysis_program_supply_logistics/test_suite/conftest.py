"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client, ApiClient, TEST_USERS, make_patient_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def nurse_2_headers():
    return TEST_USERS["nurse_2_headers"]


@pytest.fixture
def nephrologist_headers():
    return TEST_USERS["nephrologist_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def biomed_headers():
    return TEST_USERS["biomed_headers"]


@pytest.fixture
def patient_headers():
    # Shared constant: only safe for tests that do NOT exercise ownership.
    return TEST_USERS["patient_headers"]
