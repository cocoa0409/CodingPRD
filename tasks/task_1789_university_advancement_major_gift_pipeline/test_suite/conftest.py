"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def gift_officer_headers():
    return TEST_USERS["gift_officer_headers"]


@pytest.fixture
def researcher_headers():
    return TEST_USERS["researcher_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def vp_headers():
    return TEST_USERS["vp_headers"]


@pytest.fixture
def dro_headers():
    return TEST_USERS["dro_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]
