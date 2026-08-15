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
def director2_headers():
    return TEST_USERS["director2_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def ops2_headers():
    return TEST_USERS["ops2_headers"]


@pytest.fixture
def juror_1_headers():
    return TEST_USERS["juror_1_headers"]


@pytest.fixture
def juror_2_headers():
    return TEST_USERS["juror_2_headers"]


@pytest.fixture
def juror_3_headers():
    return TEST_USERS["juror_3_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
