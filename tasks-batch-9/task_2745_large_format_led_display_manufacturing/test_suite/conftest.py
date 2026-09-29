"""Shared pytest configuration for the LED Display Manufacturing API test suite.

The service under test is restarted before every test, so each test opens
against an empty database and builds all of its own preconditions through the
declared endpoints. The composite workspace and the scenario fixtures live in
``test_helpers`` and are re-exported here so every test module can request them
by name.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401
    admin_headers,
    api,
    approved_project,
    burn_in_passed_cabinet,
    chamber,
    commissioned_project,
    commissioned_without_contract,
    contract_with_spare,
    crew,
    engineer_headers,
    fp10_model,
    mounted_project,
    operator_headers,
    plant,
    populated_cabinet,
    qa_headers,
    responded_degradation_case,
    reviewer_headers,
    service_headers,
)
