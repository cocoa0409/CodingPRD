"""Shared pytest configuration for the deployment-and-monitoring suite.

The fixtures themselves live beside the other infrastructure in
``test_helpers.fixtures``; re-exporting them here is what makes them visible to
every test module without an explicit import in each file.
"""

from test_helpers.fixtures import (  # noqa: F401
    api,
    approved_dataset,
    approved_version,
    clock_at_default,
    draft_dataset,
    evaluation_arms,
    live_stack,
    model,
    open_endpoint,
    pending_stack,
    ramping_stack,
)
