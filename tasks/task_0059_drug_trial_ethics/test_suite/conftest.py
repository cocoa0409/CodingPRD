"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.

Per PRD §2.1:
- Secretary and RegulatoryWatcher are OPAQUE — shared constants OK.
- Applicant is opaque BUT X-User-ID is recorded as Application.
  applicant_id and used for ownership; per-call builder is required.
- Chairperson and CommitteeMember are entity_backed — tests that
  exercise ownership MUST use make_chair_headers(member['id']) /
  make_committee_member_headers(member['id']).
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def secretary_headers():
    return TEST_USERS["secretary_headers"]


@pytest.fixture
def secretary_headers_alt():
    return TEST_USERS["secretary_headers_alt"]


@pytest.fixture
def regulatory_watcher_headers():
    return TEST_USERS["regulatory_watcher_headers"]


@pytest.fixture
def applicant_headers_fallback():
    """Fallback Applicant headers — opaque X-User-ID 'applicant-fallback'.

    Per PRD §2.1 ownership checks compare X-User-ID to the resource's
    applicant_id; this constant matches no real Application.applicant_id,
    so use it ONLY for tests that do not exercise ownership (missing-
    auth, wrong-role, missing-resource)."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def chairperson_headers_fallback():
    return TEST_USERS["chairperson_headers"]


@pytest.fixture
def committee_member_headers_fallback():
    return TEST_USERS["committee_member_headers"]
