"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_policy_holder_headers,
    make_underwriter_headers,
    make_adjuster_headers,
    make_fema_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def policy_holder_headers():
    """Shared PolicyHolder header constant. Use ONLY for non-ownership-gated calls.
    For ownership-gated calls, mint per-holder headers with
    make_policy_holder_headers(owner_id)."""
    return TEST_USERS["policy_holder_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def fema_admin_headers():
    return TEST_USERS["fema_admin_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing builder functions so tests can mint per-identity headers."""
    return {
        "policy_holder": make_policy_holder_headers,
        "underwriter": make_underwriter_headers,
        "adjuster": make_adjuster_headers,
        "fema_admin": make_fema_admin_headers,
    }
