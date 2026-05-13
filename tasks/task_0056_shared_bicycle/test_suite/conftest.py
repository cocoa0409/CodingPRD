"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures.
#
# Per PRD §2.1: Admin / Operator / FieldStaff are OPAQUE — shared
# constants are canonical and may be used directly.
#
# Rider is entity_backed: tests that exercise ownership MUST use the
# per-instance builder make_rider_headers(rider['id']). The shared
# constant fixture below is a fallback for missing-auth / wrong-role /
# missing-resource tests only.
# ---------------------------------------------------------------------------
@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator_headers_alt():
    return TEST_USERS["operator_headers_alt"]


@pytest.fixture
def field_staff_headers():
    return TEST_USERS["field_staff_headers"]


@pytest.fixture
def rider_headers():
    """Fallback Rider headers — opaque X-User-ID 'rider-fallback'.

    PRD §2.1: ownership-gated Rider-role endpoints compare X-User-ID to
    the resource's rider foreign-key field; this constant matches no
    real Rider.id, so use it only for tests that do NOT exercise
    ownership (missing-auth, wrong-role, missing-resource scenarios).
    """
    return TEST_USERS["rider_headers"]
