"""Shared pytest fixtures for the Flood Zone Determination API suite.

The harness restarts the API server with an empty database before every test, so
no fixture may assume state left behind by an earlier test.  Each fixture below
therefore builds only headers or a client; every row a test needs is created by
that test through the endpoints the PRD declares.

PRD 2.1 makes identity semantics role-dependent: a ``Lender`` caller's
``X-User-ID`` is the ``id`` of the acting ``Lender`` row and a ``Borrower``
caller's ``X-User-ID`` is the opaque ``borrower_user_id`` recorded on the folio,
so ownership-sensitive tests build their headers from the row they just created
rather than from a shared constant.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import TEST_USERS  # noqa: E402


@pytest.fixture
def client():
    """A fresh API client bound to the server the harness just started."""
    return ApiClient()


@pytest.fixture
def analyst_headers():
    """A `ProviderAnalyst` acting with an opaque operator identity (PRD 2.1)."""
    return TEST_USERS["provider_analyst_headers"]


@pytest.fixture
def second_analyst_headers():
    """A second `ProviderAnalyst` identity, for segregation-of-duties scenarios."""
    return TEST_USERS["provider_analyst_2_headers"]


@pytest.fixture
def reviewer_headers():
    """A `ProviderReviewer` acting with an opaque operator identity (PRD 2.1)."""
    return TEST_USERS["provider_reviewer_headers"]


@pytest.fixture
def second_reviewer_headers():
    """A second `ProviderReviewer` identity, for segregation-of-duties scenarios."""
    return TEST_USERS["provider_reviewer_2_headers"]


@pytest.fixture
def agency_headers():
    """An `AgencyOfficer` acting with an opaque operator identity (PRD 2.1)."""
    return TEST_USERS["agency_officer_headers"]


@pytest.fixture
def second_agency_headers():
    """A second `AgencyOfficer` identity, for segregation-of-duties scenarios."""
    return TEST_USERS["agency_officer_2_headers"]


@pytest.fixture
def foreign_lender_headers():
    """A `Lender` identity that owns no folio, for ownership-failure scenarios."""
    return TEST_USERS["lender_headers"]


@pytest.fixture
def borrower_headers():
    """The canonical `Borrower` opaque identifier used by the default folio."""
    return TEST_USERS["borrower_headers"]
