"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: Candidate is the sole entity_backed role. The shared-
constant `candidate_headers` fixture is a placeholder used only by
tests that probe auth / role / 404 paths without exercising ownership.
Tests that exercise ownership mint headers via
`make_candidate_headers(candidate_id)` with the actual id.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    ensure_all_default_policies,
)


# ===========================================================================
# Session-scoped API client — server lifecycle managed by the runner.
# ===========================================================================
@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


# ===========================================================================
# Session-scoped jurisdiction seeding.
# PRD §3.1: "a `JurisdictionPolicy` row must exist for the supplied
# code (registered separately by a `PlatformAdmin`)."
# Tests that need explicit jurisdiction config can re-upsert.
# ===========================================================================
@pytest.fixture(scope="session", autouse=True)
def _seed_default_jurisdictions(api: ApiClient) -> None:
    """Seed permissive defaults for every supported jurisdiction at the
    start of the session so candidate-creation tests aren't blocked by
    the JurisdictionPolicy precondition. Tests that probe jurisdiction-
    specific behavior re-upsert with the values they need.
    """
    ensure_all_default_policies()


# ===========================================================================
# Shared-constant role headers.
# ===========================================================================
@pytest.fixture
def recruiter_headers():
    return TEST_USERS["recruiter_headers"]


@pytest.fixture
def recruiter_secondary_headers():
    return TEST_USERS["recruiter_secondary_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def adjudicator_secondary_headers():
    return TEST_USERS["adjudicator_secondary_headers"]


@pytest.fixture
def verifier_headers():
    return TEST_USERS["verifier_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def candidate_headers():
    """Placeholder Candidate headers (NOT tied to any real candidate).
    Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["candidate_headers"]
