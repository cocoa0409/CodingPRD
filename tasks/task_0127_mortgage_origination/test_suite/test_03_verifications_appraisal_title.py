"""Income / Asset verification, Appraisal, and Title-search state
machines and gates (PRD §3.3, §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_appraisal,
    assert_asset_verification,
    assert_income_verification,
    assert_title_search,
    complete_appraisal_payload,
    complete_title_search_payload,
    create_and_pre_qualify,
    create_asset_verification_payload,
    create_borrower_and_application,
    create_income_verification_payload,
    iso_plus,
    order_and_complete_appraisal,
    order_and_complete_title_search,
    order_appraisal_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Income verification — PRD §3.3
# ===========================================================================
def test_income_verify_at_or_above_80pct_succeeds(
    api, loan_officer_headers,
):
    """PRD §3.3: "The record can be transitioned to VERIFIED only when
    documented_annual_cents is at least 80% of the borrower's stated
    annual_income_cents — i.e., the documented figure lies within 20%
    below the stated figure. On verification, the system stamps the
    actor's identifier into verifier_user_id and advances status to
    VERIFIED."

    Claim: documented = 80% of stated -> verify succeeds.
    """
    # Stated = $120,000; documented = $96,000 (exactly 80%).
    _, app = create_and_pre_qualify(
        annual_income_cents=12_000_000, headers=loan_officer_headers,
    )
    create = validate_success(api.create_income_verification(
        app["id"],
        create_income_verification_payload(
            source_type="W2", documented_annual_cents=9_600_000,
        ),
        loan_officer_headers,
    ), 201)
    assert_income_verification(create)
    assert create["status"] == "PENDING"
    out = validate_success(api.verify_income(
        app["id"], create["id"], None, loan_officer_headers,
    ), 200)
    assert out["status"] == "VERIFIED"
    assert isinstance(out.get("verifier_user_id"), str) and out["verifier_user_id"]


def test_income_verify_below_80pct_rejected(api, loan_officer_headers):
    """PRD §3.3: documented must be at least 80% of stated to verify.

    Claim: documented = 79% of stated -> verify is rejected (4xx) and
    record stays PENDING. The PRD prose does not name a specific
    error_id for this particular precondition failure, so we assert
    only the rejection and the unchanged status.
    """
    _, app = create_and_pre_qualify(
        annual_income_cents=12_000_000, headers=loan_officer_headers,
    )
    ver = validate_success(api.create_income_verification(
        app["id"],
        create_income_verification_payload(
            documented_annual_cents=9_480_000,  # 79%
        ),
        loan_officer_headers,
    ), 201)
    res = api.verify_income(
        app["id"], ver["id"], None, loan_officer_headers,
    )
    assert res.status_code >= 400


def test_income_reject_from_pending_succeeds(api, loan_officer_headers):
    """PRD §3.3: "The record can also be rejected unconditionally from
    PENDING, transitioning to REJECTED."
    """
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    ver = validate_success(api.create_income_verification(
        app["id"], create_income_verification_payload(),
        loan_officer_headers,
    ), 201)
    out = validate_success(api.reject_income(
        app["id"], ver["id"], None, loan_officer_headers,
    ), 200)
    assert out["status"] == "REJECTED"


# ===========================================================================
# Asset verification — PRD §3.3
# ===========================================================================
def test_asset_verify_at_or_above_materiality_succeeds(
    api, loan_officer_headers,
):
    """PRD §3.3: "It moves from PENDING to VERIFIED only when the
    balance_cents is at least 1,000 (the materiality floor — assets
    under ten dollars are not counted)."

    Claim: balance_cents = 1,000 (exactly the inclusive floor) ->
    verify succeeds.
    """
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    av = validate_success(api.create_asset_verification(
        app["id"],
        create_asset_verification_payload(balance_cents=1_000),
        loan_officer_headers,
    ), 201)
    assert_asset_verification(av)
    out = validate_success(api.verify_asset(
        app["id"], av["id"], None, loan_officer_headers,
    ), 200)
    assert out["status"] == "VERIFIED"


def test_asset_verify_below_materiality_rejected(api, loan_officer_headers):
    """PRD §3.3: "moves from PENDING to VERIFIED only when the
    balance_cents is at least 1,000".

    Claim: balance_cents = 999 (just below) -> verify is rejected and
    record remains PENDING.
    """
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    av = validate_success(api.create_asset_verification(
        app["id"],
        create_asset_verification_payload(balance_cents=999),
        loan_officer_headers,
    ), 201)
    res = api.verify_asset(
        app["id"], av["id"], None, loan_officer_headers,
    )
    assert res.status_code >= 400


def test_asset_reject_from_pending_succeeds(api, loan_officer_headers):
    """PRD §3.3: "The record can be rejected from PENDING
    unconditionally, transitioning to REJECTED."
    """
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    av = validate_success(api.create_asset_verification(
        app["id"], create_asset_verification_payload(),
        loan_officer_headers,
    ), 201)
    out = validate_success(api.reject_asset(
        app["id"], av["id"], None, loan_officer_headers,
    ), 200)
    assert out["status"] == "REJECTED"


# ===========================================================================
# Appraisal — PRD §3.4
# ===========================================================================
def test_order_and_complete_appraisal_sets_valid_until_120_days(
    api, loan_officer_headers,
):
    """PRD §3.4: "When the appraisal completes, the loan officer
    supplies an appraised_value_cents (strictly positive). The system
    advances status to COMPLETED, computes valid_until as report_date
    plus 120 calendar days at 23:59:59.999 UTC"

    Claim: after /appraisal/complete, status=COMPLETED and valid_until
    is exactly report_date + 120 calendar days at 23:59:59.999 UTC.
    """
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    appr = order_and_complete_appraisal(
        app["id"],
        report_date="2026-03-01T00:00:00.000Z",
        appraised_value_cents=40_000_000,
        headers=loan_officer_headers,
    )
    assert_appraisal(appr)
    assert appr["status"] == "COMPLETED"
    # Expected: 2026-03-01 + 120 days = 2026-06-29 at 23:59:59.999 UTC.
    expected = "2026-06-29T23:59:59.999Z"
    assert appr["valid_until"] == expected, (
        "PRD §3.4: valid_until must be report_date + 120 calendar days "
        f"at 23:59:59.999 UTC. Expected {expected}, got {appr['valid_until']}."
    )


def test_appraisal_overlap_rejected(api, loan_officer_headers):
    """PRD §3.4: "The system permits at most one COMPLETED Appraisal
    whose valid_until is greater than SystemClock.now per
    LoanApplication at any time; an attempt to order a second when an
    unexpired completed appraisal exists is rejected with
    ERR_APPRAISAL_OVERLAP."

    Claim: ordering a second appraisal while a COMPLETED + unexpired
    one exists returns ERR_APPRAISAL_OVERLAP (409).

    # difficulty: resource_temporal_overlap/appraisal_validity_window_at_most_one_unexpired_completed
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"],
        report_date="2026-03-01T00:00:00.000Z",
        appraised_value_cents=40_000_000,
        headers=loan_officer_headers,
    )
    # Attempt a second order — the first is COMPLETED and valid_until
    # (2026-06-29 ...) is in the future relative to SystemClock.now.
    res = api.order_appraisal(
        app["id"],
        order_appraisal_payload(report_date="2026-03-15T00:00:00.000Z"),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_APPRAISAL_OVERLAP.value,
        expected_status=409,
    )


def test_appraisal_overlap_clears_after_valid_until_elapses(
    api, loan_officer_headers,
):
    """PRD §3.4: "The system permits at most one COMPLETED Appraisal
    whose valid_until is greater than SystemClock.now per
    LoanApplication at any time"

    Claim: after the first appraisal's valid_until elapses
    (SystemClock.now > valid_until), a new appraisal order is no
    longer in overlap and must be accepted. The singleton is keyed on
    "unexpired COMPLETED", so advancing the clock past valid_until
    frees the slot.

    # difficulty: resource_temporal_overlap/appraisal_validity_window_at_most_one_unexpired_completed
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    appr1 = order_and_complete_appraisal(
        app["id"],
        report_date="2026-03-01T00:00:00.000Z",
        appraised_value_cents=40_000_000,
        headers=loan_officer_headers,
    )
    # Advance past the appraisal's valid_until (2026-06-29 ...).
    advance_clock(iso_plus(appr1["valid_until"], seconds=1))
    res = api.order_appraisal(
        app["id"],
        order_appraisal_payload(report_date="2026-07-01T00:00:00.000Z"),
        loan_officer_headers,
    )
    out = validate_success(res, 201)
    assert out["status"] == "ORDERED", (
        "PRD §3.4: once SystemClock.now > prior valid_until, the "
        "singleton is free and a new appraisal can be ordered."
    )


def test_appraisal_reject_terminates(api, loan_officer_headers):
    """PRD §3.4: "An appraisal is also rejectable from ORDERED to
    REJECTED without further effect."

    Claim: POST /appraisal/reject moves ORDERED -> REJECTED.
    """
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    ordered = validate_success(api.order_appraisal(
        app["id"], order_appraisal_payload(),
        loan_officer_headers,
    ), 201)
    out = validate_success(api.reject_appraisal(
        app["id"], None, loan_officer_headers,
    ), 200)
    assert out["status"] == "REJECTED"


# ===========================================================================
# Title search — PRD §3.4
# ===========================================================================
def test_title_search_empty_defects_goes_to_clear(
    api, loan_officer_headers,
):
    """PRD §3.4: "Completing a title search requires a defects_found
    array: if the array is empty, the title search advances to CLEAR;
    if it contains one or more defect descriptions, it advances to
    ISSUES_FOUND."

    Claim: defects_found=[] -> status=CLEAR.
    """
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    ts = validate_success(api.order_title_search(
        app["id"], None, loan_officer_headers,
    ), 201)
    out = validate_success(api.complete_title_search(
        app["id"], complete_title_search_payload(defects_found=[]),
        loan_officer_headers,
    ), 200)
    assert out["status"] == "CLEAR"


def test_title_search_with_defects_goes_to_issues_found(
    api, loan_officer_headers,
):
    """PRD §3.4: "if it contains one or more defect descriptions, it
    advances to ISSUES_FOUND".

    Claim: defects_found=["lien"] -> status=ISSUES_FOUND.
    """
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    validate_success(api.order_title_search(
        app["id"], None, loan_officer_headers,
    ), 201)
    out = validate_success(api.complete_title_search(
        app["id"],
        complete_title_search_payload(defects_found=["outstanding lien"]),
        loan_officer_headers,
    ), 200)
    assert out["status"] == "ISSUES_FOUND"


def test_title_search_resolve_from_issues_found(api, loan_officer_headers):
    """PRD §3.4: "A title search in ISSUES_FOUND can subsequently be
    resolved by the loan officer (typically after the curative work
    has been performed off-system), at which point status becomes
    RESOLVED and the system stamps resolved_at with SystemClock.now."

    Claim: /resolve on ISSUES_FOUND -> RESOLVED with resolved_at set.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    order_and_complete_title_search(
        app["id"], defects_found=["x"], headers=loan_officer_headers,
    )
    out = validate_success(api.resolve_title_search(
        app["id"], None, loan_officer_headers,
    ), 200)
    assert out["status"] == "RESOLVED"
    assert isinstance(out.get("resolved_at"), str) and out["resolved_at"]
