"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_technician_headers,
    make_client_contact_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def service_manager_headers():
    return TEST_USERS["service_manager_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def technician_headers():
    """Shared Technician header constant. Use ONLY for calls that do not
    exercise the entity_backed:Technician ownership check. Ownership-gated
    calls MUST use make_technician_headers(<Technician.id>)."""
    return TEST_USERS["technician_headers"]


@pytest.fixture
def client_contact_headers():
    """Shared ClientContact fallback. Use ONLY for non-ownership-gated calls.
    Ownership-gated calls MUST use make_client_contact_headers(<Client.id>)."""
    return TEST_USERS["client_contact_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing per-identity header builders for entity_backed roles."""
    return {
        "technician": make_technician_headers,
        "client_contact": make_client_contact_headers,
    }
