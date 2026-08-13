"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def dio_headers():
    return TEST_USERS["dio_headers"]


@pytest.fixture
def pd_headers():
    return TEST_USERS["pd_headers"]


@pytest.fixture
def pc_headers():
    return TEST_USERS["pc_headers"]


@pytest.fixture
def faculty_headers():
    return TEST_USERS["faculty_headers"]


@pytest.fixture
def ccc_chair_headers():
    return TEST_USERS["ccc_chair_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]
