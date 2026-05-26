"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle, API_BASE_URL injection, and per-test database reset
are all handled by `prd-bench-local-runner --isolation per-test-server`.
"""
import pytest
from test_helpers import api_client as _api_client_instance, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return _api_client_instance


@pytest.fixture
def custodian_agent_headers():
    return TEST_USERS["custodian_agent_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def system_tax_authority_headers():
    return TEST_USERS["system_tax_authority_headers"]


@pytest.fixture
def account_owner_shared_headers():
    """Shared AccountOwner constant — only safe for tests that do NOT exercise
    ownership semantics (e.g. 400-on-bad-payload). For ownership-gated calls
    use `make_account_owner_headers(donor['id'])`."""
    return TEST_USERS["account_owner_headers"]
