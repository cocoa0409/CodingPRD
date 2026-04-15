"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def professor_headers():
    return TEST_USERS["professor_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]


@pytest.fixture
def registrar_2_headers():
    return TEST_USERS["registrar_2_headers"]


@pytest.fixture
def professor_2_headers():
    return TEST_USERS["professor_2_headers"]


@pytest.fixture
def student_2_headers():
    return TEST_USERS["student_2_headers"]
