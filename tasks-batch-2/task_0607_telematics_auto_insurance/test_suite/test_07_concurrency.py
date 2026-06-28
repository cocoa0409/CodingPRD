"""Optimistic-concurrency (OCC) stale-version tests.

Translated from SCAFFOLD_CORNER_DESIGN.yaml queue B section
`cross_cutting_complexity_layers`.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    create_statement_payload,
    create_renewal_payload,
    TEST_USERS,
    setup_bound_policy,
    add_policy_trip,
    get_policy,
)

UW = TEST_USERS["underwriting_headers"]


def test_stale_policy_version_on_statement_create_rejected(api):
    """PRD §3.6: "The statement-creation request also carries `policy_id` and an
    `expected_policy_version` that must match the policy's current `version`; if a
    concurrent writer has accepted or voided a trip (advancing the policy version and
    changing the multiplier), the snapshot inputs are stale and the create is rejected
    with `ERR_STALE_VERSION` at HTTP 412."
    PRD §3.6: "Creating the statement transitions the policy's billing dimension from
    `PERIOD_OPEN` to `PERIOD_CLOSING` and increments the policy's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_policy_version_on_statement_create
    """
    ctx = setup_bound_policy(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    # one accepted policy trip in the period (its accept already advanced the version)
    add_policy_trip(ctx, "2026-02-05T01:00:00Z", "2026-02-05T02:00:00Z", 10.0, accept=True)
    stale_version = get_policy(ctx)["version"]
    # first statement create succeeds and advances the policy version
    get_success_data(api.create_statement(
        create_statement_payload(ctx["policy"]["id"], stale_version), UW))
    # second create still carrying the pre-bump expected version -> stale
    res = api.create_statement(
        create_statement_payload(ctx["policy"]["id"], stale_version), UW)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_stale_policy_version_on_renewal_create_rejected(api):
    """PRD §3.9: "Opening a renewal supplies the `policy_id` and an
    `expected_policy_version` that must match the policy's current `version`; if another
    writer has since accepted a prior renewal or settled a statement (legitimately
    advancing the baseline), the current writer's view is stale and the open is rejected
    with `ERR_STALE_VERSION` at HTTP 412."
    PRD §3.9: "Opening also increments the policy's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_policy_version_on_renewal_create
    """
    ctx = setup_bound_policy(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    stale_version = get_policy(ctx)["version"]
    # first renewal open succeeds and advances the policy version
    get_success_data(api.create_renewal(
        create_renewal_payload(ctx["policy"]["id"], stale_version), UW))
    # second open still carrying the pre-bump expected version -> stale
    res = api.create_renewal(
        create_renewal_payload(ctx["policy"]["id"], stale_version), UW)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
