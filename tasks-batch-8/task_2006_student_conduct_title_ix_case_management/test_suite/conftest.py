"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def case_admin_headers():
    """CaseAdministrator is the only opaque role; the shared constant is safe."""
    return TEST_USERS["case_admin_headers"]
