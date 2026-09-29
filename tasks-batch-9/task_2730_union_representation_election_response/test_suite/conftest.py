"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def director_two_headers():
    return TEST_USERS["director_two_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def counsel_headers():
    return TEST_USERS["counsel_headers"]


@pytest.fixture
def counsel_two_headers():
    return TEST_USERS["counsel_two_headers"]


@pytest.fixture
def trainer_headers():
    return TEST_USERS["trainer_headers"]


@pytest.fixture
def board_headers():
    return TEST_USERS["board_headers"]


@pytest.fixture
def union_headers():
    return TEST_USERS["union_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]
