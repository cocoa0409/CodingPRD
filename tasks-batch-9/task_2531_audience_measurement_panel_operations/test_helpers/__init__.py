"""Test infrastructure for the Audience Measurement Panel Operations API.

Import surface:

* ``types``      -- role and status enums plus one TypedDict per entity family.
* ``api_errors`` -- every error id with its HTTP status, registered with the framework.
* ``api_client`` -- one method per endpoint, plus the shared ``api_client`` instance.
* ``constants``  -- PRD literals: thresholds, credit factors, tier table, boundaries.
* ``factories``  -- payload builders with PRD-valid defaults and keyword overrides.
* ``test_users`` -- header builders for the seven roles, one of which is entity-backed.
* ``assertions`` -- shape assertions, conserved-quantity checks and reference calculators.
* ``fixtures``   -- ``PanelHarness`` setup orchestration and the pytest fixtures.
"""

from test_helpers import (  # noqa: F401
    api_client,
    api_errors,
    assertions,
    constants,
    factories,
    fixtures,
    test_users,
    types,
)
