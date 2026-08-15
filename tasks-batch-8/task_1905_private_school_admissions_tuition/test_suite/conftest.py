"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def fao_1_headers():
    return TEST_USERS["fao_1_headers"]


@pytest.fixture
def fao_2_headers():
    return TEST_USERS["fao_2_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]
