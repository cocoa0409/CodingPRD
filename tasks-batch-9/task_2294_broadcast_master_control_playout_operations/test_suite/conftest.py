"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque roles: the identifier is never resolved against an entity, so a
# constant header set is correct for the whole session.
# ---------------------------------------------------------------------------

@pytest.fixture
def traffic_headers():
    return TEST_USERS["traffic_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Entity-backed roles: X-User-ID must be the id of a persisted Operator whose
# role_class matches. These constants deliberately do NOT resolve, so they are
# only for probes that assert the unresolved-operator behaviour; tests needing a
# real identity build headers from the operator they created (see
# test_helpers.fixtures.bootstrap_operators).
# ---------------------------------------------------------------------------

@pytest.fixture
def unresolved_master_control_headers():
    return TEST_USERS["master_control_headers"]


@pytest.fixture
def unresolved_qc_headers():
    return TEST_USERS["qc_headers"]


@pytest.fixture
def unresolved_program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def unresolved_engineer_headers():
    return TEST_USERS["engineer_headers"]
