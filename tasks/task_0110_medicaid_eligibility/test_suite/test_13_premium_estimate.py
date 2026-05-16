"""Redetermination premium estimate — per-member-first rounding pinned
by PRD §3.7.

This file targets the combinatorial_formula/
redetermination_premium_round_order_pinned difficulty instance: the
PRD pins "per-member values are rounded first, then summed" and
explicitly rejects the alternative ordering.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    advance_to_redetermination_due,
    get_redetermination,
    iso_offset,
    parse_iso,
    random_state_code,
    run_redetermination_sweep,
    server_now_dt,
    setup_approved_application,
    setup_redetermination_pending,
    submit_redetermination_payload,
    validate_success,
)


def _extract_premium_value(redet_data: dict) -> float:
    """PRD §3.7 names the value the 'premium estimate'. The PRD does
    not pin a specific JSON field name on the GET response — readers
    may legitimately serialize it as `premium_estimate`,
    `enrollment_redetermination_premium`, or `premium`. Surface
    whichever the response carries.

    Returns the numeric premium value or raises AssertionError if no
    plausible field is present.
    """
    candidates = (
        "premium_estimate",
        "enrollment_redetermination_premium",
        "redetermination_premium",
        "premium",
    )
    for key in candidates:
        if key in redet_data and redet_data[key] is not None:
            return float(redet_data[key])
    raise AssertionError(
        f"PRD §3.7 requires the redetermination read endpoint to "
        f"expose a premium estimate; no recognized field present. "
        f"Looked for: {candidates}; got keys: {list(redet_data)}"
    )


class TestPremiumEstimateRounding:
    """PRD §3.7 pins per-member-first rounding for the premium estimate,
    but the formula it specifies uses Redetermination.new_snapshot_fpl_
    percent — a field that PRD §3.4 sets only on /submit, by which time
    the Redetermination is no longer PENDING. PRD §3.7 also says the
    estimate is exposed only when status is PENDING. The two statements
    leave the premium read unreachable for any PRD-faithful
    implementation: a PRD-only reader cannot construct a setup that
    surfaces a non-null premium on a PENDING Redetermination, so the
    per-member-first rounding rule cannot be exercised from PRD prose
    alone. The original test acknowledged this by ending in an
    unconditional pytest.skip; per the benchmark's "treat skipped as
    failed" cardinal rule, the test is removed (PRD-silence /
    unique-derivability category).
    """
    pass
