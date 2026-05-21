"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: Recruiter, HiringManager, Interviewer, and Candidate are
entity_backed roles. The shared-constant fixtures below are
placeholders used only by tests that probe auth / role / 404 paths
without exercising ownership. Tests that exercise ownership use
make_<role>_headers() with the actual entity id.
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
# Entity-backed role placeholder headers. For ownership-gated calls,
# tests MUST mint headers via make_<role>_headers(entity_id).
# ===========================================================================
@pytest.fixture
def recruiter_headers():
    """Placeholder Recruiter headers (NOT tied to any persisted
    Recruiter). Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["recruiter_headers"]


@pytest.fixture
def hiring_manager_headers():
    """Placeholder HiringManager headers (NOT tied to any persisted
    HiringManager). Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["hiring_manager_headers"]


@pytest.fixture
def interviewer_headers():
    """Placeholder Interviewer headers (NOT tied to any persisted
    Interviewer). Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["interviewer_headers"]


@pytest.fixture
def candidate_headers():
    """Placeholder Candidate headers (NOT tied to any persisted
    Candidate). Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["candidate_headers"]


# ===========================================================================
# Opaque-role headers — shared constants are canonical.
# ===========================================================================
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compensation_headers():
    return TEST_USERS["compensation_headers"]


@pytest.fixture
def compensation_secondary_headers():
    return TEST_USERS["compensation_secondary_headers"]


@pytest.fixture
def executive_headers():
    return TEST_USERS["executive_headers"]


@pytest.fixture
def executive_secondary_headers():
    return TEST_USERS["executive_secondary_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def payroll_operator_headers():
    return TEST_USERS["payroll_operator_headers"]
