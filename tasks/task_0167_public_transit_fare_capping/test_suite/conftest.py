"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: Rider and EmployerAdmin are entity_backed roles. The
shared-constant fixtures below are placeholders used only by tests
that probe auth / role / 404 paths without exercising ownership.
Tests that exercise ownership use make_rider_headers /
make_employer_admin_headers with the actual entity id.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


# ===========================================================================
# Session-scoped API client — server lifecycle managed by the runner.
# ===========================================================================
@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


# ===========================================================================
# Shared-constant role headers. For ownership-gated calls, tests MUST
# mint headers via make_rider_headers(rider_id) or
# make_employer_admin_headers(employer_id).
# ===========================================================================
@pytest.fixture
def rider_headers():
    """Placeholder Rider headers (NOT tied to any persisted Rider).
    Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["rider_headers"]


@pytest.fixture
def employer_admin_headers():
    """Placeholder EmployerAdmin headers (NOT tied to any persisted
    Employer). Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["employer_admin_headers"]


@pytest.fixture
def agency_officer_headers():
    return TEST_USERS["agency_officer_headers"]


@pytest.fixture
def agency_officer_secondary_headers():
    return TEST_USERS["agency_officer_secondary_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
