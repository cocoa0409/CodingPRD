"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_audit_observer_headers,
    make_cycle_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def cycle_admin_headers():
    """The opaque CycleAdmin operator identity."""
    return make_cycle_admin_headers()


@pytest.fixture
def audit_observer_headers():
    """The opaque, read-only AuditObserver identity."""
    return make_audit_observer_headers()


@pytest.fixture
def partner_headers():
    """Partner role header whose X-User-ID resolves to no partner row."""
    return TEST_USERS["partner_headers"]


@pytest.fixture
def committee_member_headers():
    """CommitteeMember role header whose X-User-ID resolves to no partner row."""
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def credit_arbiter_headers():
    """CreditArbiter role header whose X-User-ID resolves to no partner row."""
    return TEST_USERS["credit_arbiter_headers"]
