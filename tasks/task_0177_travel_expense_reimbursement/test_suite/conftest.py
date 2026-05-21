"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: TRAVELER, MANAGER, FINANCE_REVIEWER, and OOP_APPROVER are
entity_backed. The shared-constant `*_headers` fixtures resolve to a
placeholder UUID that does NOT correspond to any real Employee; they
are appropriate only for tests that probe auth / role / 404 paths
WITHOUT exercising ownership. Tests that exercise ownership must mint
headers via `make_{role}_headers(employee_id)` after creating the
underlying Employee.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_finance_reviewer_headers,
    make_manager_headers,
    make_oop_approver_headers,
    make_traveler_headers,
    seed_finance_reviewer,
    seed_manager,
    seed_oop_approver,
    seed_traveler,
)


# ===========================================================================
# Session-scoped API client — server lifecycle is the runner's job.
# ===========================================================================
@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


# ===========================================================================
# Shared-constant role headers.
#
# PRD §2.1: entity-backed roles (TRAVELER, MANAGER, FINANCE_REVIEWER,
# OOP_APPROVER) must resolve `X-User-ID` to an actual Employee row of
# that role; otherwise the impl returns ERR_INVALID_ROLE before doing
# anything else (see §2.7 priority order). The shared `*_headers`
# fixtures therefore SEED a real Employee on demand and emit headers
# carrying that employee's real id, so that tests probing 404 / path
# resolution actually reach the path-resolution stage.
# ===========================================================================
@pytest.fixture
def admin_headers():
    # ADMIN is opaque per PRD §2.1 — the canonical shared constant is fine.
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_secondary_headers():
    return TEST_USERS["admin_secondary_headers"]


@pytest.fixture
def traveler_headers():
    """Real TRAVELER headers — backed by a freshly-seeded Employee.

    PRD §2.1 requires `X-User-ID` to resolve to an Employee carrying the
    declared role; otherwise ERR_INVALID_ROLE pre-empts every downstream
    check. Tests using this fixture probe auth-pass paths (e.g. 404 path
    resolution) and therefore need a real backing employee.
    """
    manager = seed_manager()
    traveler = seed_traveler(manager_id=manager["id"])
    return make_traveler_headers(traveler["id"])


@pytest.fixture
def manager_headers():
    """Real MANAGER headers — backed by a freshly-seeded Employee."""
    manager = seed_manager()
    return make_manager_headers(manager["id"])


@pytest.fixture
def finance_reviewer_headers():
    """Real FINANCE_REVIEWER headers — backed by a freshly-seeded Employee."""
    finance = seed_finance_reviewer()
    return make_finance_reviewer_headers(finance["id"])


@pytest.fixture
def oop_approver_headers():
    """Real OOP_APPROVER headers — backed by a freshly-seeded Employee."""
    oop = seed_oop_approver()
    return make_oop_approver_headers(oop["id"])
