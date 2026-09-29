"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    build_active_determination,
    build_contractor,
    build_portal,
    make_agency_officer_headers,
    make_auditor_headers,
    make_portal_admin_headers,
    setup_env,
    setup_env_with_worker,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# --- One fixture per role ------------------------------------------------
@pytest.fixture
def portal_admin_headers() -> dict:
    return TEST_USERS["portal_admin_headers"]


@pytest.fixture
def agency_officer_headers() -> dict:
    return TEST_USERS["agency_officer_headers"]


@pytest.fixture
def agency_officer_2_headers() -> dict:
    return TEST_USERS["agency_officer_2_headers"]


@pytest.fixture
def auditor_headers() -> dict:
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def auditor_2_headers() -> dict:
    return TEST_USERS["auditor_2_headers"]


@pytest.fixture
def preparer_headers() -> dict:
    """PayrollPreparer whose X-User-ID resolves to no ContractorStaff row."""
    return TEST_USERS["preparer_headers"]


@pytest.fixture
def certifier_headers() -> dict:
    """CertifyingOfficial whose X-User-ID resolves to no ContractorStaff row."""
    return TEST_USERS["certifier_headers"]


# --- Named operator identities used by the design recipes ----------------
@pytest.fixture
def admin_headers() -> dict:
    return make_portal_admin_headers()


@pytest.fixture
def officer_headers() -> dict:
    return make_agency_officer_headers("officer-anna")


@pytest.fixture
def officer_2_headers() -> dict:
    return make_agency_officer_headers("officer-bram")


@pytest.fixture
def cruz_headers() -> dict:
    return make_auditor_headers("auditor-cruz")


# --- Composite domain state ----------------------------------------------
@pytest.fixture
def portal(api) -> dict:
    return build_portal(api)


@pytest.fixture
def active_determination(api):
    """(determination, [wage_rate]) with the determination in ACTIVE."""
    return build_active_determination(api)


@pytest.fixture
def contractor(api) -> dict:
    return build_contractor(api)


@pytest.fixture
def env(api) -> dict:
    """ACTIVE project in CA-ALAMEDA on an ACTIVE determination, prime tier ACTIVE."""
    return setup_env(api)


@pytest.fixture
def env_with_worker(api) -> dict:
    """``env`` plus one journeyworker registered under the tier's contractor."""
    return setup_env_with_worker(api)
