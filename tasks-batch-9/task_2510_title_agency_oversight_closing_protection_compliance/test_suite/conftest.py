"""Pytest wiring for the Title Agency Oversight suite.

Everything reusable lives in `test_helpers`; this file only exposes it to
pytest. Importing `test_helpers` also registers the error-identifier to
HTTP-status map that the response validators cross-check.
"""

from test_helpers import ApiClient, api_client  # noqa: F401

# The setup helpers' module-level fixtures, made available to every test file
# in this directory.
from test_helpers.fixtures import (  # noqa: F401
    api,
    compliance_officer_headers,
    env,
    escrow_auditor_headers,
    escrow_env,
    licensing_analyst_headers,
    second_compliance_officer_headers,
    second_escrow_auditor_headers,
    second_underwriting_counsel_headers,
    state_program,
    underwriting_counsel_headers,
    unowned_agency_principal_headers,
)
