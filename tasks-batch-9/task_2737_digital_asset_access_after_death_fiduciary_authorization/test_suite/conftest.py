"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    COURT_REGISTRAR_HEADERS,
    ESTATE_ADMIN_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """API client. The server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def court_registrar_headers():
    return COURT_REGISTRAR_HEADERS


@pytest.fixture
def estate_admin_headers():
    return ESTATE_ADMIN_HEADERS
