"""Shared pytest fixtures for the Sterile Fill-Finish CMO API test suite.

The harness restarts the server and empties the database before every single
test, so nothing here may assume state survives between tests. Every composite
fixture rebuilds its world from scratch through the endpoints of PRD section 4.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import api_client, fixtures
from test_helpers.test_users import (
    MICROBIOLOGY_ANALYST,
    PRODUCTION_SUPERVISOR,
    PROGRAM_MANAGER,
    QA_REVIEWER,
    QA_REVIEWER_SECOND,
    QA_REVIEWER_THIRD,
    QUALIFIED_PERSON,
    QUALIFIED_PERSON_SECOND,
    make_client_representative_headers,
)

Json = Dict[str, Any]


@pytest.fixture(scope="session")
def api():
    """The shared HTTP client for the API under test."""
    return api_client


# ---------------------------------------------------------------------------
# One header set per role of PRD 2.1
# ---------------------------------------------------------------------------
@pytest.fixture
def program_manager_headers() -> Dict[str, str]:
    return dict(PROGRAM_MANAGER)


@pytest.fixture
def production_supervisor_headers() -> Dict[str, str]:
    return dict(PRODUCTION_SUPERVISOR)


@pytest.fixture
def microbiology_analyst_headers() -> Dict[str, str]:
    return dict(MICROBIOLOGY_ANALYST)


@pytest.fixture
def qa_reviewer_headers() -> Dict[str, str]:
    return dict(QA_REVIEWER)


@pytest.fixture
def qa_reviewer_second_headers() -> Dict[str, str]:
    return dict(QA_REVIEWER_SECOND)


@pytest.fixture
def qa_reviewer_third_headers() -> Dict[str, str]:
    return dict(QA_REVIEWER_THIRD)


@pytest.fixture
def qualified_person_headers() -> Dict[str, str]:
    return dict(QUALIFIED_PERSON)


@pytest.fixture
def qualified_person_second_headers() -> Dict[str, str]:
    return dict(QUALIFIED_PERSON_SECOND)


@pytest.fixture
def client_representative_headers():
    """A builder, because a ClientRepresentative's X-User-ID is a project id."""
    return make_client_representative_headers


# ---------------------------------------------------------------------------
# Composite worlds, each assembled only through published endpoints
# ---------------------------------------------------------------------------
@pytest.fixture
def qualified_suite(api) -> Json:
    """A grade B suite aseptically qualified with two effective operators."""
    return fixtures.build_qualified_suite(api)


@pytest.fixture
def scheduled_program(api) -> Json:
    """A programme walked as far as a SCHEDULED batch order."""
    return fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)


@pytest.fixture
def filling_program(api) -> Json:
    """A programme walked as far as a FILLING batch order."""
    return fixtures.build_program(api, stage=fixtures.STAGE_FILLING)


@pytest.fixture
def qp_review_program(api) -> Json:
    """The worked example of PRD 3.8: a batch sitting in QP_REVIEW."""
    return fixtures.build_program(api, stage=fixtures.STAGE_QP_REVIEW)
