"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    AUDITOR_HEADERS,
    BREWER_HEADERS,
    DISPATCH_HEADERS,
    SECOND_AUDITOR_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the harness."""
    return api_client


@pytest.fixture
def dispatch_headers():
    """A DispatchCoordinator, whose identity is opaque."""
    return DISPATCH_HEADERS


@pytest.fixture
def auditor_headers():
    """A QualityAuditor, whose identity is recorded on the rows it touches."""
    return AUDITOR_HEADERS


@pytest.fixture
def second_auditor_headers():
    """A second QualityAuditor, for rules that compare two auditor identities."""
    return SECOND_AUDITOR_HEADERS


@pytest.fixture
def brewer_headers():
    """A BrewerRep, whose identity is opaque."""
    return BREWER_HEADERS
