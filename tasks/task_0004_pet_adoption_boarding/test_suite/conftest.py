"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager_headers_2():
    return TEST_USERS["manager_headers_2"]


@pytest.fixture
def manager_headers_3():
    return TEST_USERS["manager_headers_3"]


@pytest.fixture
def case_worker_headers():
    return TEST_USERS["case_worker_headers"]


@pytest.fixture
def case_worker_headers_2():
    return TEST_USERS["case_worker_headers_2"]


@pytest.fixture
def case_worker_headers_3():
    return TEST_USERS["case_worker_headers_3"]


@pytest.fixture
def vet_headers():
    return TEST_USERS["vet_headers"]


@pytest.fixture
def vet_headers_2():
    return TEST_USERS["vet_headers_2"]
