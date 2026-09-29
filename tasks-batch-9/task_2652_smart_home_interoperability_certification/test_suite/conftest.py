"""pytest configuration for the Smart Home Interoperability Certification suite.

The task root is put on ``sys.path`` so ``test_helpers`` imports cleanly, and the
shared composite fixtures are re-exported here so any test module can request one
by name.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    authorized_laboratory,
    clock_at_programme_start,
    funded_member,
    program_certified,
    program_draft_submission,
    program_in_execution,
    program_in_review,
    program_listed,
    program_published,
    program_review_complete,
    program_submitted,
    program_with_completed_plan,
    program_with_draft_plan,
    program_with_issued_plan,
    program_with_scheduled_session,
    ratified_specification,
)
