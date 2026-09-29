"""Pytest configuration exposing the domain helper fixtures to every test file.

The server is restarted with an empty store before each test, so every fixture
here is function-scoped and rebuilds whatever state it needs from scratch.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402
    ReviewLadder,
    REVIEWER_ADA,
    REVIEWER_BEN,
    REVIEWER_CLEO,
    REVIEWER_DANA,
    REVIEWER_DARA,
    REVIEWER_ELENA,
    api,
    assigned_batch,
    batched_matter,
    capped_matter,
    closed_matter,
    drawn_sample,
    failed_sample,
    hourly_matter,
    ladder,
    matter_in_intake,
    matter_in_staffing,
    matter_with_draft_protocol,
    partially_batched_closeout,
    passed_sample,
    qc_validator,
    registered_client,
    released_batch,
    score_gap_pool,
    second_level_matter,
    staffed_matter,
    standard_tier_matter,
    started_assignment,
    submitted_assignment,
    tie_break_pool,
    tightly_capped_matter,
    two_batch_engagement,
    two_reviewer_matter,
)

__all__ = [
    "ReviewLadder",
    "REVIEWER_ADA",
    "REVIEWER_BEN",
    "REVIEWER_CLEO",
    "REVIEWER_DANA",
    "REVIEWER_DARA",
    "REVIEWER_ELENA",
    "api",
    "assigned_batch",
    "batched_matter",
    "capped_matter",
    "closed_matter",
    "drawn_sample",
    "failed_sample",
    "hourly_matter",
    "ladder",
    "matter_in_intake",
    "matter_in_staffing",
    "matter_with_draft_protocol",
    "partially_batched_closeout",
    "passed_sample",
    "qc_validator",
    "registered_client",
    "released_batch",
    "score_gap_pool",
    "second_level_matter",
    "staffed_matter",
    "standard_tier_matter",
    "started_assignment",
    "submitted_assignment",
    "tie_break_pool",
    "tightly_capped_matter",
    "two_batch_engagement",
    "two_reviewer_matter",
]
