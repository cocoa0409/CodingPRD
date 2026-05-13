"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest only
wires per-role headers and the session-scoped api client.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures. PRD §2.1:
#   - PlatformAdmin, RegistrationReviewer, FinanceOps, DisputeOfficer,
#     PlaybackSource are OPAQUE — shared constants OK.
#   - RightsHolder is entity_backed — tests that exercise ownership MUST
#     use make_rights_holder_headers(holder['id']).
# ---------------------------------------------------------------------------
@pytest.fixture
def pa_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def pa_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["registration_reviewer_headers"]


@pytest.fixture
def reviewer_headers_alt():
    return TEST_USERS["registration_reviewer_headers_alt"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_ops_headers"]


@pytest.fixture
def finance_headers_alt():
    return TEST_USERS["finance_ops_headers_alt"]


@pytest.fixture
def dispute_officer_headers():
    return TEST_USERS["dispute_officer_headers"]


@pytest.fixture
def playback_source_headers():
    return TEST_USERS["playback_source_headers"]


@pytest.fixture
def rights_holder_headers_fallback():
    """Fallback entity-backed headers.

    PRD §2.1: 'When X-User-Role is RightsHolder, X-User-ID is the id of
    the acting RightsHolder; ownership checks ... compare the resource's
    foreign-key field to X-User-ID.' This constant matches no real
    RightsHolder.id, so use it ONLY for tests that do not exercise
    ownership (missing-auth, wrong-role, missing-resource negatives).
    """
    return TEST_USERS["rights_holder_headers"]
