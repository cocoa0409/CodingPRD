"""Excess correction boundaries: executing a correction when there is no excess.

(The depth-3 correction cascade and the amount-mismatch corner live in
test_03_contribution_limit.py alongside the limit-recompute that drives the excess.)
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
)
from test_helpers.fixtures import (
    ADMIN, setup_active_account, create_and_post_contribution, account_version,
    create_correction,
)
from test_helpers.api_client import api_client

ADMIN_HDR = ADMIN


# ── correction_zero_excess_no_excess_boundary (Difficulty/boundary_precision) ─

def _correction_then_clear_excess(api):
    """Build the no-excess-at-execution precondition through a PRD-faithful path.

    PRD §2.9 requires every monetary amount to be a positive integer, so a
    correction can never be created with requested_amount_cents == 0. Instead we
    drive the account into excess, create a correction matching that positive
    excess (passing the create-time OCC and positive-integer checks), then raise
    the applicable limit above the posted contributions so the account's
    excess_contribution_cents recomputes to 0 before the correction is executed.

    PRD §3.3: superseding a coverage period and attesting a new one each trigger a
    recomputation of applicable_limit_cents / excess_contribution_cents. Replacing
    the full-year SELF_ONLY coverage (limit 432000) with full-year FAMILY coverage
    (limit 862500) lifts the limit above the posted 500000, so excess -> 0.

    Returns (account_id, correction).
    """
    account, holder = setup_active_account(coverage_tier="SELF_ONLY",
                                           date_of_birth="1988-08-18",
                                           clock="2026-03-01T00:00:00Z")
    # Overshoot the 432000 SELF_ONLY limit -> excess 68000, posture LOCKED.
    create_and_post_contribution(account["id"], "INDIVIDUAL", 500000)
    v = account_version(account["id"])
    # Correction created for the real positive excess (68000), OCC version current.
    corr = create_correction(account["id"], 68000, v)
    # Raise the limit so excess recomputes to 0 before execution.
    cps, _m = validate_paginated(api.list_coverage_periods(account["id"], ADMIN_HDR))
    self_cp = next(cp for cp in cps if cp["status"] == "ATTESTED")
    validate_success(
        api.supersede_coverage_period(account["id"], self_cp["id"], ADMIN_HDR), 200)
    validate_success(api.create_coverage_period(
        account["id"], {"coverage_tier": "FAMILY", "effective_month": 1,
                        "end_month": 12}, ADMIN_HDR), 201)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["excess_contribution_cents"] == 0
    return account["id"], corr


def test_execute_correction_with_zero_excess_rejected(api):
    """PRD §3.9: "Execution requires the account's `lifecycle_status` to be `ACTIVE`
    (else `ERR_INVALID_STATE`), requires that `excess_contribution_cents` is greater than
    zero at execution (else `ERR_NO_EXCESS`)".

    With excess recomputed to 0 before execution, executing the still-REQUESTED
    correction is rejected ERR_NO_EXCESS.

    Design: Difficulty/boundary_precision_check/correction_zero_excess_no_excess_boundary
    """
    account_id, corr = _correction_then_clear_excess(api)
    res = api.execute_correction(account_id, corr["id"], ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_NO_EXCESS)


def test_execute_zero_excess_leaves_correction_requested(api):
    """PRD §3.9: "Execution requires the account's `lifecycle_status` to be `ACTIVE`
    (else `ERR_INVALID_STATE`), requires that `excess_contribution_cents` is greater than
    zero at execution (else `ERR_NO_EXCESS`), and requires that the correction's
    `requested_amount_cents` equals the current `excess_contribution_cents` at execution
    (else `ERR_CORRECTION_AMOUNT_MISMATCH`)."

    A correction whose execution is rejected for no-excess does not transition; it stays
    REQUESTED.

    Design: Difficulty/boundary_precision_check/correction_zero_excess_no_excess_boundary
    """
    account_id, corr = _correction_then_clear_excess(api)
    validate_error(api.execute_correction(account_id, corr["id"], ADMIN_HDR),
                   ApiErrorId.ERR_NO_EXCESS)
    listed, _meta = validate_paginated(api.list_corrections(account_id, ADMIN_HDR))
    target = next(c for c in listed if c["id"] == corr["id"])
    assert target["status"] == "REQUESTED"
