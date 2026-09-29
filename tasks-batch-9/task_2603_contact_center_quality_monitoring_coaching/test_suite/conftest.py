"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_agent_headers,
    make_compliance_auditor_headers,
    make_evaluator_headers,
    make_quality_manager_headers,
    make_supervisor_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared HTTP client for the service under test."""
    return api_client


@pytest.fixture(scope="session")
def qm_headers():
    """Headers for the opaque QualityManager operator."""
    return make_quality_manager_headers()


@pytest.fixture(scope="session")
def supervisor_headers():
    """Headers for the opaque Supervisor operator."""
    return make_supervisor_headers()


@pytest.fixture(scope="session")
def auditor_headers():
    """Headers for the opaque ComplianceAuditor operator."""
    return make_compliance_auditor_headers()


@pytest.fixture(scope="session")
def evaluator_headers_for():
    """Builder for entity-backed QualityEvaluator headers."""
    return make_evaluator_headers


@pytest.fixture(scope="session")
def agent_headers_for():
    """Builder for entity-backed Agent headers."""
    return make_agent_headers
