"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable without sys.path
manipulation. The runner also restarts the API server (via start.sh) before
every individual pytest test, so each test starts against an empty database.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# ─── One fixture per role from TEST_USERS ──────────────────────────────

@pytest.fixture
def caseworker_headers():
    return TEST_USERS["caseworker_headers"]


@pytest.fixture
def benefit_issuer_headers():
    return TEST_USERS["benefit_issuer_headers"]


@pytest.fixture
def fraud_investigator_headers():
    return TEST_USERS["fraud_investigator_headers"]


@pytest.fixture
def fraud_investigator_b_headers():
    return TEST_USERS["fraud_investigator_b_headers"]


@pytest.fixture
def merchant_headers():
    return TEST_USERS["merchant_headers"]


@pytest.fixture
def policy_admin_headers():
    return TEST_USERS["policy_admin_headers"]


@pytest.fixture
def applicant_headers():
    """Fallback Applicant headers (PRD §2.1: Applicant is entity_backed:Household).
    DO NOT use for ownership-gated calls; use make_applicant_headers(hh['id'])."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def cardholder_headers():
    """Fallback Cardholder headers (PRD §2.1: Cardholder is entity_backed:Household).
    DO NOT use for ownership-gated calls; use make_cardholder_headers(hh['id'])."""
    return TEST_USERS["cardholder_headers"]
