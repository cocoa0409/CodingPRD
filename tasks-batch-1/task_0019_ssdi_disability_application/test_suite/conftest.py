"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ssa_admin_headers():
    return TEST_USERS["ssa_admin_headers"]


@pytest.fixture
def ssa_admin_2_headers():
    return TEST_USERS["ssa_admin_2_headers"]


@pytest.fixture
def dds_examiner_headers():
    return TEST_USERS["dds_examiner_headers"]


@pytest.fixture
def dds_examiner_2_headers():
    return TEST_USERS["dds_examiner_2_headers"]


@pytest.fixture
def alj_headers():
    return TEST_USERS["alj_headers"]


@pytest.fixture
def alj_2_headers():
    return TEST_USERS["alj_2_headers"]


@pytest.fixture
def benefits_admin_headers():
    return TEST_USERS["benefits_admin_headers"]


@pytest.fixture
def benefits_admin_2_headers():
    return TEST_USERS["benefits_admin_2_headers"]


@pytest.fixture
def claimant_headers():
    """Shared Claimant constant — usable ONLY where ownership is not checked
    (RBAC denial tests, unauthenticated tests). For ownership-gated calls,
    construct headers via make_claimant_headers(claimant['id'])."""
    return TEST_USERS["claimant_headers"]
