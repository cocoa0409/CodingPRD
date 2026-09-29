"""Shared pytest configuration for the Environmental Justice compliance suite.

The harness restarts the API server before each individual test, so no fixture
here is session-scoped: every test builds its own preconditions from scratch
through the endpoints the PRD declares.
"""

import os
import sys

# Make the sibling `test_helpers` package importable regardless of how pytest
# was invoked.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401  -- fixture registration
    api,
    app_a_assessment_accepted,
    app_a_issued,
    app_a_pending_decision,
    app_a_plan_open,
    app_a_plan_open_draft_assessment,
    app_a_screened,
    app_a_screening_assessment,
    area_a,
    area_a_facility,
    area_a_inspection_pending,
    area_b_two_applications,
    area_c_boundary_pair,
    area_d_standard_track,
    area_e_f_complaint_pool,
    area_g,
    area_g_facility,
    area_h,
    area_i_pending_decision,
    area_j_pending_decision,
    area_k_assessment_accepted,
    area_k_draft_application,
    area_k_screened,
    area_k_screened_with_venue,
    area_k_submitted_application,
    area_l_comment_scenario,
    area_m_facility,
    clock,
    venue_pair,
)
