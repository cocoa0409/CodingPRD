"""Optimistic concurrency control and explicit-PRD race outcomes.

Anchors: PRD §2.4, §2.10.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    api_client,
    assert_exactly_one_succeeds,
    create_borrower,
    create_borrower_with_loan_in_repayment,
    create_plan,
    make_borrower_headers,
    run_race,
    submit_hardship_request,
    update_hardship_request_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import _fmt_iso, _parse_iso  # type: ignore


# ---------------------------------------------------------------------------
# 1. OCC stale-version rejection on PATCH (PRD §2.4 + §2.10)
# ---------------------------------------------------------------------------
def test_stale_version_on_hardship_patch_rejected(api):
    """PRD §2.10: "When two PATCH calls update the same
    HardshipRequest, the OCC check applies: a stale version value
    loses with ERR_VERSION_CONFLICT."

    Claim: PATCH with a stale version on a HardshipRequest →
    ERR_VERSION_CONFLICT.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment()
    req_from = current
    req_to = _fmt_iso(_parse_iso(current) + timedelta(days=30))
    req = submit_hardship_request(
        borrower["id"], "FORBEARANCE_GENERAL",
        requested_from=req_from, requested_to=req_to,
        applied_loan_ids=[loan["id"]],
    )
    stale_version = req["version"]
    # First PATCH (REJECTED) advances version.
    validate_success(
        api.update_hardship_request(
            borrower["id"], req["id"],
            {"status": "REJECTED", "rejection_reason": "needs review"},
            TEST_USERS["servicer_certifier_headers"],
        ),
        200,
    )
    # Second PATCH with the stale version.
    res = api.update_hardship_request(
        borrower["id"], req["id"],
        {"status": "REJECTED", "rejection_reason": "duplicate",
         "version": stale_version},
        TEST_USERS["servicer_certifier_headers"],
    )
    validate_error(res, "ERR_VERSION_CONFLICT")


def test_stale_version_on_borrower_patch_rejected(api):
    """PRD §2.10: "The same OCC rule governs every other PATCH
    endpoint that accepts version? in its body."

    Claim: PATCH /borrowers with stale version → ERR_VERSION_CONFLICT.
    """
    b = create_borrower()
    stale = b["version"]
    validate_success(
        api.update_borrower(
            b["id"], {"family_size": 2},
            TEST_USERS["servicer_admin_headers"],
        ),
        200,
    )
    res = api.update_borrower(
        b["id"], {"family_size": 3, "version": stale},
        TEST_USERS["servicer_admin_headers"],
    )
    validate_error(res, "ERR_VERSION_CONFLICT")


def test_omitting_version_skips_occ_check(api):
    """PRD §2.4: "When version is omitted the optimistic-concurrency
    check is skipped and the latest stored version is used."

    Claim: PATCH without a version field succeeds even when a prior
    PATCH has advanced the version.
    """
    b = create_borrower()
    validate_success(
        api.update_borrower(
            b["id"], {"family_size": 2},
            TEST_USERS["servicer_admin_headers"],
        ),
        200,
    )
    # No version field — server uses latest.
    res = api.update_borrower(
        b["id"], {"family_size": 5},
        TEST_USERS["servicer_admin_headers"],
    )
    updated = validate_success(res, 200)
    assert updated["family_size"] == 5


# ---------------------------------------------------------------------------
# 2. Plan-conflict race (PRD §2.10 + §3.7)
# ---------------------------------------------------------------------------
def test_two_plans_overlapping_loan_serialize_to_one_active(api):
    """PRD §2.10: "When two activate calls land at nearly the same
    time on two different plans whose included_loan_ids overlap on
    at least one loan for the same borrower, the server preserves
    the invariant that at most one ACTIVE plan covers any given
    loan."

    Sequential (not concurrent) variant: activating two overlapping
    plans yields exactly one ACTIVE plan and one SUPERSEDED plan.
    """
    borrower, loan, _ = create_borrower_with_loan_in_repayment()
    plan_a = create_plan(borrower["id"], "STANDARD_10", [loan["id"]])
    plan_b = create_plan(borrower["id"], "SAVE", [loan["id"]])
    validate_success(
        api.activate_plan(borrower["id"], plan_a["id"],
                          TEST_USERS["servicer_admin_headers"]),
        200,
    )
    validate_success(
        api.activate_plan(borrower["id"], plan_b["id"],
                          TEST_USERS["servicer_admin_headers"]),
        200,
    )
    after_a = validate_success(
        api.get_plan(borrower["id"], plan_a["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    after_b = validate_success(
        api.get_plan(borrower["id"], plan_b["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    actives = [p for p in (after_a, after_b) if p["status"] == "ACTIVE"]
    assert len(actives) == 1, (
        "PRD §3.7 / §2.10: at most one ACTIVE plan must cover the loan"
    )
