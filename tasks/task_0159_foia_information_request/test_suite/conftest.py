"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.
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
# Shared-constant role headers. For ownership-gated Requester calls, tests
# MUST mint headers via make_requester_headers(requester_id) — the
# requester_headers fixture below is a placeholder used only for
# RBAC / 401 / 404 probes.
# ===========================================================================
@pytest.fixture
def requester_headers():
    """Placeholder Requester headers (NOT tied to any persisted Requester).
    Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["requester_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_secondary_headers():
    return TEST_USERS["officer_secondary_headers"]


@pytest.fixture
def appeal_authority_headers():
    return TEST_USERS["appeal_authority_headers"]


@pytest.fixture
def appeal_authority_secondary_headers():
    return TEST_USERS["appeal_authority_secondary_headers"]


@pytest.fixture
def third_party_headers():
    return TEST_USERS["third_party_headers"]


@pytest.fixture
def third_party_secondary_headers():
    return TEST_USERS["third_party_secondary_headers"]


@pytest.fixture
def clock_operator_headers():
    return TEST_USERS["clock_operator_headers"]
