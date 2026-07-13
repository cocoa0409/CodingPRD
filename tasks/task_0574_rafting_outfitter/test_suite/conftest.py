"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def outfitter_manager_headers():
    return TEST_USERS["outfitter_manager_headers"]


@pytest.fixture
def reservationist_headers():
    return TEST_USERS["reservationist_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]
