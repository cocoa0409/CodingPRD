"""Shared pytest fixtures for the busy-season resource scheduling suite.

The service is relaunched against an empty store before every individual test,
so each test builds every precondition it needs through the public endpoints.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    api_client,
    firm_admin_headers,
    independence_officer_headers,
    make_engagement_partner_headers,
    make_engagement_staff_headers,
    scheduling_manager_headers,
)


@pytest.fixture(scope="session")
def api():
    """The endpoint-per-method HTTP client for the scheduling service."""

    return api_client


@pytest.fixture
def admin_headers():
    """Back-office identity: reference data and the logical clock."""

    return firm_admin_headers()


@pytest.fixture
def manager_headers():
    """Resource management office identity: inventory and booking writes."""

    return scheduling_manager_headers()


@pytest.fixture
def officer_headers():
    """Independence and ethics function identity."""

    return independence_officer_headers()


@pytest.fixture
def partner_headers_for():
    """Builds a signing-partner identity bound to a specific staff row."""

    return make_engagement_partner_headers


@pytest.fixture
def staff_headers_for():
    """Builds a charging-staff identity bound to a specific staff row."""

    return make_engagement_staff_headers
