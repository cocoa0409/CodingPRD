"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, restart between tests) is managed by
prd-bench-local-runner; conftest just wires test_helpers into pytest.
"""
import pytest

from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    admissions_headers as _admissions_headers,
    fa_officer_headers as _fa_headers,
    admin_headers as _admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


# --- Opaque-role header fixtures ----------------------------------------

@pytest.fixture
def admin_headers():
    return _admin_headers()


@pytest.fixture
def admissions_officer_headers():
    return _admissions_headers()


@pytest.fixture
def fa_officer_headers():
    return _fa_headers()
