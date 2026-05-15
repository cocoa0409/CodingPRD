"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped api client.

PRD §2.1 identity rules:
- PlatformAdmin is OPAQUE → shared constant is canonical.
- Author, EditorInChief, SectionEditor, AssociateEditor, Reviewer are
  entity-backed → ownership-gated tests MUST mint headers via
  make_<role>_headers(entity['id']).
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque-role headers (canonical via shared constants)
# ---------------------------------------------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    """A second PlatformAdmin id for tests that need a distinct opaque
    operator identifier."""
    return TEST_USERS["platform_admin_headers_alt"]


# ---------------------------------------------------------------------------
# Entity-backed fallback headers — for use ONLY by tests that don't
# exercise ownership (missing-auth, wrong-role, missing-resource probes).
# PRD §2.1 ownership-gated calls must build per-instance headers via
# the make_<role>_headers(entity_id) builders.
# ---------------------------------------------------------------------------
@pytest.fixture
def author_fallback_headers():
    return TEST_USERS["author_headers"]


@pytest.fixture
def editor_in_chief_fallback_headers():
    return TEST_USERS["editor_in_chief_headers"]


@pytest.fixture
def section_editor_fallback_headers():
    return TEST_USERS["section_editor_headers"]


@pytest.fixture
def associate_editor_fallback_headers():
    return TEST_USERS["associate_editor_headers"]


@pytest.fixture
def reviewer_fallback_headers():
    return TEST_USERS["reviewer_headers"]
