"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """A platform administrator: the brand catalogue, registries and clock."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def analyst_headers():
    """A settlement analyst identity used for proposals and reconciliation."""
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def second_analyst_headers():
    """A second settlement analyst, for the segregation-of-duties counterparty."""
    return TEST_USERS["second_analyst_headers"]


@pytest.fixture
def store_operator_headers():
    """A store operator identity not tied to any registered store."""
    return TEST_USERS["store_operator_headers"]


@pytest.fixture
def channel_partner_headers():
    """A channel partner identity not tied to any registered channel."""
    return TEST_USERS["channel_partner_headers"]


@pytest.fixture
def courier_agent_headers():
    """A courier network agent identity not tied to any registered network."""
    return TEST_USERS["courier_agent_headers"]
