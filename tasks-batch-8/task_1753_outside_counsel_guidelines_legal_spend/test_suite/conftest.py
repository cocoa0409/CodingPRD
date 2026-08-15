"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL; these tests
assume the server is already running and freshly restarted (empty database)
before every test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def legal_ops_headers():
    """Opaque LegalOpsReviewer identity (not tied to any persisted entity)."""
    return TEST_USERS["legal_ops_headers"]


@pytest.fixture
def panel_firm_headers():
    """Fallback PanelFirmUser identity for tests that never exercise ownership."""
    return TEST_USERS["panel_firm_headers"]
