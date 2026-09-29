"""Shared pytest fixtures for the D&O management-liability suite.

Every request must carry ``X-User-ID`` and ``X-User-Role``.  The three operator
roles carry opaque identifiers, so their headers can be shared; a
``RiskManager``'s ``X-User-ID`` is the ``id`` of the acting ``Insured``, so
ownership-gated calls build their headers per insured with
:func:`make_risk_manager_headers`.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_helpers import api_client  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """One client for the whole session; the harness restarts the API per test."""
    return api_client


@pytest.fixture
def underwriter_headers():
    """The insurer's underwriting authority."""
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def risk_manager_headers():
    """A RiskManager identity that owns no insured, for calls that never reach an
    ownership comparison."""
    return TEST_USERS["risk_manager_headers"]


@pytest.fixture
def claims_adjuster_headers():
    """The adjuster who handles the claim."""
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def second_claims_adjuster_headers():
    """A distinct adjuster identity: the adjuster who recommended a settlement may
    not be the adjuster who funds it."""
    return TEST_USERS["second_claims_adjuster_headers"]


@pytest.fixture
def compliance_officer_headers():
    """The portfolio administrator, who also owns the clock and the epoch."""
    return TEST_USERS["compliance_officer_headers"]
