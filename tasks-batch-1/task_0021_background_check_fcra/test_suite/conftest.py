"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable without sys.path
hacks. The runner also restarts the API server (via start.sh) before every
individual pytest test, so each test starts against an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# ─── One fixture per role from TEST_USERS ──────────────────────────────

@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def recruiter_headers():
    return TEST_USERS["recruiter_headers"]


@pytest.fixture
def recruiter_b_headers():
    return TEST_USERS["recruiter_b_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_b_headers():
    return TEST_USERS["compliance_officer_b_headers"]


@pytest.fixture
def verification_provider_headers():
    return TEST_USERS["verification_provider_headers"]


@pytest.fixture
def applicant_headers():
    """Fallback Applicant headers (PRD §2.1: Applicant is entity_backed:Applicant).
    DO NOT use for ownership-gated calls; use make_applicant_headers(applicant['id'])."""
    return TEST_USERS["applicant_headers"]
