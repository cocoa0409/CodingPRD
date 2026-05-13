"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is owned by prd-bench-local-runner; conftest only
wires up shared in-test infrastructure.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


# ===========================================================================
# Opaque-role header fixtures (PRD §2.1: ExamAdmin / Proctor / Marker /
# AppealOfficer / TestHarness identities are opaque operator ids).
# ===========================================================================
@pytest.fixture
def exam_admin_headers():
    return TEST_USERS["exam_admin_headers"]


@pytest.fixture
def exam_admin_headers_alt():
    return TEST_USERS["exam_admin_headers_alt"]


@pytest.fixture
def proctor_headers():
    return TEST_USERS["proctor_headers"]


@pytest.fixture
def proctor_headers_alt():
    return TEST_USERS["proctor_headers_alt"]


@pytest.fixture
def marker_headers():
    return TEST_USERS["marker_headers"]


@pytest.fixture
def marker_headers_alt():
    return TEST_USERS["marker_headers_alt"]


@pytest.fixture
def marker_headers_third():
    return TEST_USERS["marker_headers_third"]


@pytest.fixture
def appeal_officer_headers():
    return TEST_USERS["appeal_officer_headers"]


@pytest.fixture
def appeal_officer_headers_alt():
    return TEST_USERS["appeal_officer_headers_alt"]


@pytest.fixture
def test_harness_headers():
    return TEST_USERS["test_harness_headers"]


@pytest.fixture
def candidate_fallback_headers():
    """Non-ownership Candidate fallback. PRD §2.1 requires real
    candidate calls to use make_candidate_headers(candidate_id) — this
    fallback is for negative tests that don't traverse ownership."""
    return TEST_USERS["candidate_headers"]
