"""Pytest fixtures exposing test_helpers infrastructure for the Public Rental Housing API.

Server lifecycle, PYTHONPATH, and base URL are managed by prd-bench-local-runner; this
file just wires test_helpers into pytest fixtures.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    create_program,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner guarantees the server is up at API_BASE_URL."""
    return api_client


# ──────────────────────────────────────────────────────────
# Opaque-role headers (per PRD §2.1, X-User-ID is not compared to any entity).
# ──────────────────────────────────────────────────────────


@pytest.fixture
def director_headers():
    return TEST_USERS["housing_director_headers"]


@pytest.fixture
def director_headers_alt():
    return TEST_USERS["housing_director_headers_alt"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["housing_officer_headers"]


@pytest.fixture
def officer_headers_alt():
    return TEST_USERS["housing_officer_headers_alt"]


@pytest.fixture
def citizen_headers():
    return TEST_USERS["citizen_headers"]


@pytest.fixture
def integration_headers():
    return TEST_USERS["integration_gateway_headers"]


@pytest.fixture
def applicant_headers_fallback():
    """Fallback Applicant headers — safe ONLY for tests that do not exercise ownership
    (RBAC probes, header-missing probes). Tests that hit ownership-gated endpoints must
    mint headers via make_applicant_headers(<applicant_id>) instead.
    """
    return TEST_USERS["applicant_headers_fallback"]


# ──────────────────────────────────────────────────────────
# Function-scoped HousingProgram so each test gets a clean program with its own clock,
# its own housing stock, and no cross-test contamination.
# ──────────────────────────────────────────────────────────


@pytest.fixture
def program():
    """Fresh HousingProgram with default thresholds. Each test gets a brand-new one."""
    return create_program()
