"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["elections_admin_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["elections_clerk_headers"]


@pytest.fixture
def reviewer_headers():
    """Shared SignatureReviewer identity. Ownership-gated calls must instead use
    make_signature_reviewer_headers with the assigned reviewer's own id."""
    return TEST_USERS["signature_reviewer_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["canvass_supervisor_headers"]


@pytest.fixture
def observer_headers():
    """Shared Observer identity. Session-gated calls must instead use
    make_observer_headers with the session's own observer_user_id."""
    return TEST_USERS["observer_headers"]
