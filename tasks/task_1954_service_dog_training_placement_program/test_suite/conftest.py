"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable
at API_BASE_URL and each test starts against an empty database.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator_b_headers():
    return TEST_USERS["coordinator_b_headers"]


@pytest.fixture
def coordinator_c_headers():
    return TEST_USERS["coordinator_c_headers"]


@pytest.fixture
def training_director_headers():
    return TEST_USERS["training_director_headers"]


@pytest.fixture
def veterinarian_headers():
    return TEST_USERS["veterinarian_headers"]


@pytest.fixture
def trainer_headers():
    return TEST_USERS["trainer_headers"]


@pytest.fixture
def evaluator_headers():
    return TEST_USERS["evaluator_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def puppy_raiser_headers():
    return TEST_USERS["puppy_raiser_headers"]
