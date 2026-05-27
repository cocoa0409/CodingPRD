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
def examiner_headers():
    """USPTOExaminer (opaque identity — shared constant is canonical per PRD §2.1)."""
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def admin_headers():
    """USPTOAdmin (opaque identity — shared constant is canonical per PRD §2.1)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def applicant_headers():
    """Fallback Applicant headers. PRD §2.1: Applicant is entity_backed — for
    ownership-gated calls, USE make_applicant_headers(applicant['id']) with
    the real applicant id rather than this fallback."""
    return TEST_USERS["applicant_headers"]
