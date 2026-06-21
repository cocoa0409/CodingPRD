"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def designer_headers():
    return TEST_USERS["frame_designer_headers"]


@pytest.fixture
def tech_headers():
    return TEST_USERS["frame_production_tech_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["front_desk_clerk_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]
