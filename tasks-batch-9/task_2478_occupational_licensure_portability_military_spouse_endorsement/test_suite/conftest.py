"""Shared pytest fixtures for the licensure portability compliance suite.

The harness restarts the server before every individual test, so each test starts
against an empty database and builds every precondition it needs by calling the
endpoints the requirements declare.
"""

import pytest

from test_helpers.api_client import ApiClient, api_client
from test_helpers.fixtures import (  # noqa: F401  - re-exported as fixtures
    LicensureSetup,
    approvable_application,
    civilian_applicant,
    endorsement_draft,
    endorsement_evaluation_complete,
    endorsement_settled,
    endorsement_submitted,
    endorsement_under_review,
    endorsement_with_assignment,
    make_verified_training_record,
    military_spouse_applicant,
    military_spouse_submitted,
    rn_evaluator,
    rn_profession,
    universal_recognition_under_review,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client every test drives the system through."""
    return api_client


@pytest.fixture
def setup(api: ApiClient) -> LicensureSetup:
    """Setup driver that builds preconditions through the public endpoints."""
    return LicensureSetup(api)
