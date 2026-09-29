"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import api_errors  # noqa: F401  (registers the error status map)
from test_helpers import (
    ApiClient,
    analyst_headers,
    caseworker_headers,
    fiscal_officer_headers,
    fraud_investigator_headers,
    supervisor_headers,
    work_specialist_headers,
)


@pytest.fixture
def api() -> ApiClient:
    """Client for the service under test.

    The server is restarted with an empty database before every test, so each
    test builds the state it needs through the public endpoints.
    """
    return ApiClient()


@pytest.fixture
def caseworker():
    return caseworker_headers()


@pytest.fixture
def supervisor():
    return supervisor_headers()


@pytest.fixture
def specialist():
    return work_specialist_headers()


@pytest.fixture
def fiscal_officer():
    return fiscal_officer_headers()


@pytest.fixture
def investigator():
    return fraud_investigator_headers()


@pytest.fixture
def analyst():
    return analyst_headers()
