"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and puts the task directory on PYTHONPATH,
so ``test_helpers`` imports without any path manipulation. The database is empty
at the start of every test, so each test builds its own world through the
setup-macro helpers in ``test_helpers.fixtures``.
"""

import pytest

from test_helpers import (
    GRANT_ANALYST_HEADERS,
    PROGRAM_DIRECTOR_HEADERS,
    ApiClient,
    api_client,
)
from test_helpers.test_users import (
    make_case_representative_headers,
    make_client_portal_headers,
    make_intake_screener_headers,
    make_supervising_attorney_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque role identities: no row has to exist for these to be usable.
# ---------------------------------------------------------------------------


@pytest.fixture
def director_headers():
    """ProgramDirector -- an opaque program-level identity."""
    return dict(PROGRAM_DIRECTOR_HEADERS)


@pytest.fixture
def analyst_headers():
    """GrantAnalyst -- an opaque, read-only-on-case-substance identity."""
    return dict(GRANT_ANALYST_HEADERS)


# ---------------------------------------------------------------------------
# Entity-backed role identities: builders, because the id must be a real row.
# ---------------------------------------------------------------------------


@pytest.fixture
def screener_headers():
    """Builder for IntakeScreener headers bound to a Representative id."""
    return make_intake_screener_headers


@pytest.fixture
def attorney_headers():
    """Builder for SupervisingAttorney headers bound to a Representative id."""
    return make_supervising_attorney_headers


@pytest.fixture
def representative_headers():
    """Builder for CaseRepresentative headers bound to a Representative id."""
    return make_case_representative_headers


@pytest.fixture
def portal_headers():
    """Builder for ClientPortalUser headers bound to a Client id."""
    return make_client_portal_headers
