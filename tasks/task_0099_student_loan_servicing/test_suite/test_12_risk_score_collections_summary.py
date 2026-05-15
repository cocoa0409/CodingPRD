"""Computed reads: IDR recertification drift risk score and
collections aging summary.

Anchors: PRD §3.10.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    api_client,
    create_borrower,
    create_borrower_with_loan_in_repayment,
    validate_success,
)


def test_risk_score_returns_integer_in_zero_to_hundred(api):
    """PRD §3.10: "It combines three subscores, each independently
    clamped to the integer range 0 through 100. ... The composite is
    then clamped again to the range 0 through 100 ... Finally the
    composite is rounded half-up to an integer."

    Claim: GET /risk-score returns an integer in [0, 100].
    """
    borrower = create_borrower(
        adjusted_gross_income_cents=4_000_000,
        agi_certified_at=TEST_DEFAULTS["INITIAL_CLOCK"],
    )
    res = api.get_risk_score(
        borrower["id"], TEST_USERS["servicer_admin_headers"],
    )
    body = validate_success(res, 200)
    # The PRD describes the response as a computed read; the data
    # payload likely contains a single integer key (e.g.
    # "idr_recertification_drift_score" or "score"). PRD only commits
    # to the formula and clamp range, not a specific field name. We
    # assert that some integer field in [0, 100] exists in data.
    int_scores = [v for v in body.values()
                  if isinstance(v, int) and not isinstance(v, bool)
                  and 0 <= v <= 100]
    assert int_scores, (
        "PRD §3.10: response data must carry an integer score in [0,100], "
        f"got payload {body!r}"
    )


def test_risk_score_zero_with_no_loans_and_fresh_agi(api):
    """PRD §3.10: "The delinquency subscore is the minimum of 100 and
    the maximum days_past_due across the borrower's loans. The
    forbearance-burden subscore is the minimum of 100 and the
    borrower's cumulative forbearance days divided by 1095 and
    multiplied by 100. The recertification-overdue subscore is
    computed from the elapsed days since agi_certified_at ...
    days-overdue figure is the maximum of 0 and elapsed-minus-365".

    Claim: a brand-new borrower with no loans, no forbearance, and
    agi_certified_at set fresh -> all subscores 0 -> composite 0.
    """
    borrower = create_borrower(
        adjusted_gross_income_cents=4_000_000,
        agi_certified_at=TEST_DEFAULTS["INITIAL_CLOCK"],
    )
    res = api.get_risk_score(
        borrower["id"], TEST_USERS["servicer_admin_headers"],
    )
    body = validate_success(res, 200)
    int_scores = [v for v in body.values()
                  if isinstance(v, int) and not isinstance(v, bool)]
    assert any(v == 0 for v in int_scores), (
        "PRD §3.10: a borrower with no loans, no forbearance, and a "
        "fresh AGI cert must score 0 on the composite drift score; "
        f"got payload {body!r}"
    )


def test_collections_summary_zeros_for_no_actions(api):
    """PRD §3.10: "The summary aggregates: the sum of amount_cents
    across actions whose kind is WAGE_GARNISHMENT_ORDER ... the sum
    of amount_cents across actions whose kind is
    TREASURY_OFFSET_APPLIED ... and the count of
    REHAB_PAYMENT_RECORDED actions whose occurred_at is at or after
    now minus 304 days".

    Claim: a borrower with no collections actions returns zeros (or
    empty equivalent) for all three aggregates.
    """
    borrower = create_borrower()
    res = api.get_collections_summary(
        borrower["id"], TEST_USERS["collections_officer_headers"],
        params={"start": "2020-01-01T00:00:00.000Z",
                "end": "2030-12-31T23:59:59.999Z"},
    )
    body = validate_success(res, 200)
    # Every integer value in the response should be 0 (no actions
    # recorded). The PRD does not pin specific field names so we
    # assert: no positive integer appears.
    positive = [
        (k, v) for k, v in body.items()
        if isinstance(v, int) and not isinstance(v, bool) and v > 0
    ]
    assert not positive, (
        f"PRD §3.10: empty borrower collections must aggregate to 0; "
        f"got non-zero values {positive}"
    )
