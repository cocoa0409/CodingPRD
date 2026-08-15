"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def surgeon_headers():
    return TEST_USERS["surgeon_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def cart_tech_headers():
    return TEST_USERS["cart_tech_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def officer_1_headers():
    return TEST_USERS["officer_1_headers"]


@pytest.fixture
def officer_2_headers():
    return TEST_USERS["officer_2_headers"]


@pytest.fixture
def materials_headers():
    return TEST_USERS["materials_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
