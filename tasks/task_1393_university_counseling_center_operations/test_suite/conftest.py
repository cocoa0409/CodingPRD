"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def referral_coordinator_headers():
    return TEST_USERS["referral_coordinator_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def clinical_director_headers():
    return TEST_USERS["clinical_director_headers"]


@pytest.fixture
def counselor_headers():
    return TEST_USERS["counselor_headers"]


@pytest.fixture
def triage_screener_headers():
    return TEST_USERS["triage_screener_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]
