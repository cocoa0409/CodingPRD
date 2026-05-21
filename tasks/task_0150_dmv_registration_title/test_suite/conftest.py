"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1: only Applicant is entity_backed (entity_backed:Owner). The
shared *_headers constants are appropriate for tests that probe
auth/RBAC failure modes; tests that need a real Owner.id must build
headers via make_applicant_headers(owner_id) from test_helpers.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    parse_iso,
    reset_clock_tracker_to,
    utcnow,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of the implementation's in-memory store between
    tests. Implementations that do not expose /__test__/reset are
    tolerated; tests still pass as long as they create unique entities.

    After a reset the test-process's logical-clock tracker is also
    reset so absolute timestamps are anchored to wall-clock now.
    """
    impl_now = None
    try:
        resp = api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["platform_admin_headers"],
        )
        try:
            body = resp.json()
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and data.get("now"):
                impl_now = parse_iso(data["now"])
        except Exception:
            impl_now = None
    except Exception:
        pass
    reset_clock_tracker_to(impl_now if impl_now is not None else utcnow())
    yield


# ---------------------------------------------------------------------------
# Per-role shared-constant headers — PRD §2.1
# ---------------------------------------------------------------------------
@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def vin_verifier_headers():
    return TEST_USERS["vin_verifier_headers"]


@pytest.fixture
def tax_assessor_headers():
    return TEST_USERS["tax_assessor_headers"]


@pytest.fixture
def plate_issuer_headers():
    return TEST_USERS["plate_issuer_headers"]


@pytest.fixture
def salvage_officer_headers():
    return TEST_USERS["salvage_officer_headers"]


@pytest.fixture
def emissions_inspector_headers():
    return TEST_USERS["emissions_inspector_headers"]


@pytest.fixture
def lien_clerk_headers():
    return TEST_USERS["lien_clerk_headers"]


@pytest.fixture
def real_id_reviewer_headers():
    return TEST_USERS["real_id_reviewer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
