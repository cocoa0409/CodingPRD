"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# --------------------------------------------------------------------------
# One fixture per role. The four operator roles carry opaque X-User-ID values.
# --------------------------------------------------------------------------
@pytest.fixture
def catastrophe_manager_headers():
    return TEST_USERS["catastrophe_manager_headers"]


@pytest.fixture
def catastrophe_manager_alt_headers():
    return TEST_USERS["catastrophe_manager_alt_headers"]


@pytest.fixture
def deployment_coordinator_headers():
    return TEST_USERS["deployment_coordinator_headers"]


@pytest.fixture
def deployment_coordinator_alt_headers():
    return TEST_USERS["deployment_coordinator_alt_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def claims_examiner_alt_headers():
    return TEST_USERS["claims_examiner_alt_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


# --------------------------------------------------------------------------
# The two entity-backed roles. These placeholder identities are only valid for
# tests that never reach an ownership check; ownership-gated calls must build
# headers from the real row id with make_adjuster_headers /
# make_vendor_coordinator_headers.
# --------------------------------------------------------------------------
@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def vendor_coordinator_headers():
    return TEST_USERS["vendor_coordinator_headers"]
