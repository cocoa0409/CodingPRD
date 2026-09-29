"""Pytest fixtures exposing the ``test_helpers`` infrastructure.

The runner owns the server lifecycle and the ``PYTHONPATH``, so ``test_helpers``
imports without any path manipulation. The server is relaunched against an empty
store before each test, so every helper that builds data constructs its state
from scratch through the API's own endpoints.
"""

import pytest

from test_helpers import (
    ARCHIVE_RESEARCHER,
    CLEARANCE_SUPERVISOR,
    LEGAL_COUNSEL,
    PRODUCTION_ADMIN,
    REVIEWING_COUNSEL,
    SECOND_SUPERVISOR,
    ApiClient,
    api_client,
)

__all__ = [
    "api",
    "archive_researcher_headers",
    "clearance_supervisor_headers",
    "legal_counsel_headers",
    "production_admin_headers",
    "reviewing_counsel_headers",
    "second_supervisor_headers",
]


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def production_admin_headers():
    """`ProductionAdmin` headers; the acting id is an opaque operator id."""
    return PRODUCTION_ADMIN


@pytest.fixture
def archive_researcher_headers():
    """`ArchiveResearcher` headers; the acting id is an opaque operator id."""
    return ARCHIVE_RESEARCHER


@pytest.fixture
def clearance_supervisor_headers():
    """`ClearanceSupervisor` headers; the acting id is an opaque operator id."""
    return CLEARANCE_SUPERVISOR


@pytest.fixture
def legal_counsel_headers():
    """`LegalCounsel` headers for the lawyer who issues opinion letters."""
    return LEGAL_COUNSEL


@pytest.fixture
def reviewing_counsel_headers():
    """A second `LegalCounsel` operator, distinct from the issuing lawyer, so the
    E&O legal review can be recorded without violating segregation of duties."""
    return REVIEWING_COUNSEL


@pytest.fixture
def second_supervisor_headers():
    """A second `ClearanceSupervisor` operator, for cases where the operator that
    recorded one review branch may not record the other."""
    return SECOND_SUPERVISOR
