"""Pytest fixtures exposing test_helpers infrastructure for the Wine-Storage Cellar suite."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["cellar_manager_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["cellar_member_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def appraiser_alpha_headers():
    return TEST_USERS["appraiser_alpha_headers"]


@pytest.fixture
def appraiser_beta_headers():
    return TEST_USERS["appraiser_beta_headers"]


@pytest.fixture
def insurance_agent_headers():
    return TEST_USERS["insurance_agent_headers"]


@pytest.fixture
def auction_broker_headers():
    return TEST_USERS["auction_broker_headers"]
