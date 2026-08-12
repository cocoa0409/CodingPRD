"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def airport_manager_headers():
    return TEST_USERS["airport_manager_headers"]


@pytest.fixture
def airport_manager_2_headers():
    return TEST_USERS["airport_manager_2_headers"]


@pytest.fixture
def arff_chief_headers():
    return TEST_USERS["arff_chief_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def safety_officer_2_headers():
    return TEST_USERS["safety_officer_2_headers"]


@pytest.fixture
def faa_inspector_headers():
    return TEST_USERS["faa_inspector_headers"]


@pytest.fixture
def firefighter_headers():
    return TEST_USERS["firefighter_headers"]
