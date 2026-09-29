"""Pytest fixtures exposing the GIS test infrastructure.

The runner restarts the API server before every test, so each test begins
against an empty database and builds all of its own preconditions through the
documented endpoints.
"""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    PERMIT_HEADERS,
    PROV_HEADERS,
    QC_HEADERS,
    SYSADMIN_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def sysadmin_headers():
    return SYSADMIN_HEADERS


@pytest.fixture
def analyst_headers():
    return ANALYST_HEADERS


@pytest.fixture
def qc_headers():
    return QC_HEADERS


@pytest.fixture
def prov_headers():
    return PROV_HEADERS


@pytest.fixture
def permit_headers():
    return PERMIT_HEADERS
