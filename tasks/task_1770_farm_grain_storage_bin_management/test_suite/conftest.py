"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def site_manager_headers():
    return TEST_USERS["site_manager_headers"]


@pytest.fixture
def farm_owner_headers():
    return TEST_USERS["farm_owner_headers"]


@pytest.fixture
def certified_applicator_headers():
    return TEST_USERS["certified_applicator_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]
