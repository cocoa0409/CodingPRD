"""Disclosure issuance, APR-tolerance re-disclosure, TRID waiting
period and rounding-order cash-to-close (PRD §3.6).

Covers difficulty design instances:
- combinatorial_formula/closing_cost_rounding_order_pinned
- combinatorial_formula/apr_tolerance_branching_3_inputs
- boundary_precision_check/apr_tolerance_12_vs_13_bps_strict_greater_than
- transitive_cascade/re_disclosure_cascade_depth_3
- compensating_invariant/disclosure_version_chain_apr_drift_invariant
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledge_disclosure,
    advance_clock,
    api_client,
    assert_disclosure,
    create_and_pre_qualify,
    iso_plus,
    issue_disclosure_payload,
    issue_closing_disclosure,
    issue_loan_estimate,
    make_borrower_headers,
    setup_application_in_conditional_approval,
    setup_application_ready_for_clear_to_close,
    setup_at_conditional_approval_with_le_apr,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Disclosure issuance — PRD §3.6
# ===========================================================================
def test_issue_loan_estimate_succeeds_and_starts_trid_clock(
    api, loan_officer_headers,
):
    """PRD §3.6: "The initial LOAN_ESTIMATE issuance also stamps
    trid_clock_started_at on the parent LoanApplication."

    Claim: after issuing the first LOAN_ESTIMATE, the parent
    application's trid_clock_started_at is no longer null.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    assert app.get("trid_clock_started_at") is None, (
        "PRD §3.1: trid_clock_started_at is null at creation."
    )
    le = issue_loan_estimate(app["id"], headers=loan_officer_headers)
    assert_disclosure(le)
    assert le["status"] == "ISSUED"
    assert le["kind"] == "LOAN_ESTIMATE"
    after = validate_success(api.get_loan_application(
        app["id"], loan_officer_headers,
    ), 200)
    assert after.get("trid_clock_started_at") is not None, (
        "PRD §3.6: initial LOAN_ESTIMATE issuance stamps "
        "trid_clock_started_at on the application."
    )


def test_loan_estimate_eligible_to_consummate_at_is_null(
    api, loan_officer_headers,
):
    """PRD §3.6: "For a LOAN_ESTIMATE, eligible_to_consummate_at is
    null."

    Claim: a LOAN_ESTIMATE row has eligible_to_consummate_at = null.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    le = issue_loan_estimate(app["id"], headers=loan_officer_headers)
    assert le.get("eligible_to_consummate_at") is None, (
        "PRD §3.6: LOAN_ESTIMATE.eligible_to_consummate_at must be null"
    )


def test_second_loan_estimate_supersedes_first(api, loan_officer_headers):
    """PRD §3.6: "Issuing a new disclosure of the same kind for the
    same application supersedes the previous one (in both ISSUED and
    ACKNOWLEDGED), setting its status to SUPERSEDED."

    Claim: after a second LOAN_ESTIMATE, the first one's status is
    SUPERSEDED.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    le1 = issue_loan_estimate(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    le2 = issue_loan_estimate(
        app["id"], apr_bps=655, headers=loan_officer_headers,
    )
    rows = api.list_disclosures(
        app["id"], loan_officer_headers, params={"kind": "LOAN_ESTIMATE"},
    ).json()["data"]
    by_id = {r["id"]: r for r in rows}
    assert by_id[le1["id"]]["status"] == "SUPERSEDED", (
        "PRD §3.6: prior LE must be SUPERSEDED by a new one of the "
        "same kind."
    )
    assert by_id[le2["id"]]["status"] in ("ISSUED", "ACKNOWLEDGED")


def test_loan_estimate_versions_are_monotonic_per_kind(
    api, loan_officer_headers,
):
    """PRD §2.4: "this is a monotonically increasing, server-minted,
    per-application-per-kind integer that starts at 1 for the first
    LOAN_ESTIMATE (and again at 1 for the first CLOSING_DISCLOSURE)
    issued for the application."

    Claim: three successive LOAN_ESTIMATEs are versioned 1, 2, 3.

    # difficulty: compensating_invariant/disclosure_version_chain_apr_drift_invariant
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    le1 = issue_loan_estimate(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    le2 = issue_loan_estimate(
        app["id"], apr_bps=655, headers=loan_officer_headers,
    )
    le3 = issue_loan_estimate(
        app["id"], apr_bps=660, headers=loan_officer_headers,
    )
    # The "version" we are asserting is the per-(application, kind)
    # monotonic integer that PRD §2.4 specifies. It is exposed via
    # Disclosure.version per the entity definition.
    versions = sorted(int(d["version"]) for d in (le1, le2, le3))
    assert versions == [1, 2, 3], (
        f"PRD §2.4: per-kind versions must be 1,2,3 in order. "
        f"Got {versions}."
    )


def test_disclosure_apr_drift_invariant_telescopes(
    api, loan_officer_headers,
):
    """PRD §2.4: "monotonically increasing, server-minted,
    per-application-per-kind integer".
    PRD §3.6: "Issuing a new disclosure of the same kind for the same
    application supersedes the previous one"

    Claim: a chain of three LE issuances with apr_bps 650 / 668 / 655
    must produce versions [1, 2, 3] for LOAN_ESTIMATE; versions 1 and 2
    are SUPERSEDED, version 3 is ISSUED. The telescoping invariant
    (668-650) + (655-668) == (655-650) = 5 bps is a derived check on
    Disclosure.apr_bps values.

    # difficulty: compensating_invariant/disclosure_version_chain_apr_drift_invariant
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    le1 = issue_loan_estimate(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    le2 = issue_loan_estimate(
        app["id"], apr_bps=668, headers=loan_officer_headers,
    )
    le3 = issue_loan_estimate(
        app["id"], apr_bps=655, headers=loan_officer_headers,
    )
    rows = api.list_disclosures(
        app["id"], loan_officer_headers, params={"kind": "LOAN_ESTIMATE"},
    ).json()["data"]
    by_id = {r["id"]: r for r in rows}
    aprs = [by_id[le1["id"]]["apr_bps"],
            by_id[le2["id"]]["apr_bps"],
            by_id[le3["id"]]["apr_bps"]]
    assert aprs == [650, 668, 655], (
        f"PRD §3.6: apr_bps round-trips per disclosure. Got {aprs}."
    )
    # Telescoping invariant: sum of pairwise deltas equals last - first.
    deltas_sum = (aprs[1] - aprs[0]) + (aprs[2] - aprs[1])
    assert deltas_sum == aprs[-1] - aprs[0]
    assert deltas_sum == 5

    assert by_id[le1["id"]]["status"] == "SUPERSEDED"
    assert by_id[le2["id"]]["status"] == "SUPERSEDED"
    assert by_id[le3["id"]]["status"] in ("ISSUED", "ACKNOWLEDGED")


# ===========================================================================
# Borrower acknowledgement — PRD §3.6
# ===========================================================================
def test_borrower_acknowledges_own_disclosure(api, loan_officer_headers):
    """PRD §3.6: "A borrower can acknowledge a disclosure issued to
    their own application — the actor's X-User-ID must equal the
    application's borrower_id — moving status to ACKNOWLEDGED and
    stamping acknowledged_at with SystemClock.now."

    Claim: with X-User-ID = the application's borrower_id, the
    acknowledge call returns 200 and the disclosure becomes
    ACKNOWLEDGED.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    borrower, app = create_and_pre_qualify(headers=loan_officer_headers)
    le = issue_loan_estimate(app["id"], headers=loan_officer_headers)
    headers = make_borrower_headers(borrower["id"])
    res = api.acknowledge_disclosure(
        app["id"], le["id"], None, headers,
    )
    out = validate_success(res, 200)
    assert out["status"] == "ACKNOWLEDGED"
    assert isinstance(out.get("acknowledged_at"), str) and out["acknowledged_at"]


def test_other_borrower_cannot_acknowledge_disclosure(
    api, loan_officer_headers,
):
    """PRD §3.6: "the actor's X-User-ID must equal the application's
    borrower_id"

    Claim: a Borrower role whose X-User-ID is NOT the application's
    borrower_id cannot acknowledge — the request is rejected (403 or
    404). PRD does not commit to a single error_id here, but it does
    state ownership is the gating rule.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    borrower, app = create_and_pre_qualify(headers=loan_officer_headers)
    le = issue_loan_estimate(app["id"], headers=loan_officer_headers)
    # Use a Borrower header for a *different* (unrelated) id.
    other_borrower_id = "00000000-0000-0000-0000-000000000abc"
    headers = make_borrower_headers(other_borrower_id)
    res = api.acknowledge_disclosure(
        app["id"], le["id"], None, headers,
    )
    assert res.status_code in (403, 404), (
        f"Other borrower must not be able to acknowledge; got "
        f"{res.status_code}."
    )


# ===========================================================================
# APR tolerance — PRD §3.6
# difficulty: combinatorial_formula/apr_tolerance_branching_3_inputs
# difficulty: boundary_precision_check/apr_tolerance_12_vs_13_bps_strict_greater_than
# ===========================================================================
def test_apr_tolerance_delta_12_bps_accepted(api, loan_officer_headers):
    """PRD §3.6: "If the absolute difference exceeds 12 basis points
    (i.e., 0.125%), the system rejects the issuance with
    ERR_APR_TOLERANCE_EXCEEDED and requires a fresh LOAN_ESTIMATE to be
    issued first ... The comparison is strict on the value 12: a delta
    of exactly 12 is accepted, a delta of 13 or more triggers
    re-disclosure."

    Claim: with latest LE apr_bps=650, a CLOSING_DISCLOSURE with
    apr_bps=662 (delta=12) is accepted (201).

    # difficulty: boundary_precision_check/apr_tolerance_12_vs_13_bps_strict_greater_than
    """
    _, app, _ = setup_at_conditional_approval_with_le_apr(le_apr_bps=650)
    res = api.issue_disclosure(
        app["id"],
        issue_disclosure_payload(
            kind="CLOSING_DISCLOSURE",
            apr_bps=662,
            total_loan_costs_cents=500_000,
            total_other_costs_cents=800_000,
        ),
        loan_officer_headers,
    )
    cd = validate_success(res, 201)
    assert cd["kind"] == "CLOSING_DISCLOSURE"
    assert cd["apr_bps"] == 662
    assert cd["status"] == "ISSUED"


def test_apr_tolerance_delta_13_bps_rejected(api, loan_officer_headers):
    """PRD §3.6: "a delta of 13 or more triggers re-disclosure."

    Claim: with latest LE apr_bps=650, a CD with apr_bps=663
    (delta=13) is rejected with ERR_APR_TOLERANCE_EXCEEDED.

    # difficulty: boundary_precision_check/apr_tolerance_12_vs_13_bps_strict_greater_than
    # difficulty: combinatorial_formula/apr_tolerance_branching_3_inputs
    """
    _, app, _ = setup_at_conditional_approval_with_le_apr(le_apr_bps=650)
    res = api.issue_disclosure(
        app["id"],
        issue_disclosure_payload(
            kind="CLOSING_DISCLOSURE",
            apr_bps=663,
            total_loan_costs_cents=500_000,
            total_other_costs_cents=800_000,
        ),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_APR_TOLERANCE_EXCEEDED.value,
        expected_status=409,
    )


def test_apr_tolerance_branching_three_inputs(api, loan_officer_headers):
    """PRD §3.6: "When a CLOSING_DISCLOSURE is issued, the system
    compares its apr_bps to that of the latest LOAN_ESTIMATE on file
    (the most recent non-VOIDED LOAN_ESTIMATE by version, descending).
    If the absolute difference exceeds 12 basis points ... the system
    rejects the issuance with ERR_APR_TOLERANCE_EXCEEDED"

    Claim: three inputs (LE chain selector, LE.apr_bps, CD candidate
    apr_bps) drive a branching fork between ACCEPT and REJECT. With
    LE.apr_bps=650 and CD.apr_bps=663 the request must be rejected.
    The PRD ties REJECT to ERR_APR_TOLERANCE_EXCEEDED and the LE
    chain remains at its prior ACKNOWLEDGED status.

    # difficulty: combinatorial_formula/apr_tolerance_branching_3_inputs
    """
    _, app, le = setup_at_conditional_approval_with_le_apr(le_apr_bps=650)
    # le has been ACKNOWLEDGED by setup_at_conditional_approval_with_le_apr.
    res = api.issue_disclosure(
        app["id"],
        issue_disclosure_payload(
            kind="CLOSING_DISCLOSURE",
            apr_bps=663,
            total_loan_costs_cents=500_000,
            total_other_costs_cents=800_000,
        ),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_APR_TOLERANCE_EXCEEDED.value,
        expected_status=409,
    )
    # Latest LE unchanged.
    rows = api.list_disclosures(
        app["id"], loan_officer_headers, params={"kind": "LOAN_ESTIMATE"},
    ).json()["data"]
    le_after = next(r for r in rows if r["id"] == le["id"])
    assert le_after["status"] == "ACKNOWLEDGED", (
        "PRD §3.6: the failed CD issuance must not alter the LE chain."
    )


def test_re_disclosure_cascade_depth_3(api, loan_officer_headers):
    """PRD §3.6: "Cascading re-disclosure: when a new LOAN_ESTIMATE is
    issued whose apr_bps differs from the latest CLOSING_DISCLOSURE by
    more than 12 basis points, any ACKNOWLEDGED CLOSING_DISCLOSURE on
    the application is marked SUPERSEDED and a fresh CD becomes
    required."
    PRD §3.10: "SystemClock.now is no earlier than that disclosure's
    eligible_to_consummate_at (the TRID 3-business-day waiting period
    has elapsed)"

    Claim (depth-3 cascade):
      Hop 1: previous LE (v1) is SUPERSEDED when v2 is issued.
      Hop 2: the existing ACKNOWLEDGED CD is SUPERSEDED because the new
             LE drifts > 12 bps from the CD's apr_bps.
      Hop 3: clear-to-close after the cascade fails with
             ERR_TRID_WAITING_PERIOD because no current CD has elapsed
             eligible_to_consummate_at.

    # difficulty: transitive_cascade/re_disclosure_cascade_depth_3
    """
    # Set up: in CONDITIONAL_APPROVAL with LE apr=650, CD apr=655
    # (delta=5 from LE; well within tolerance), CD ACKNOWLEDGED, and
    # TRID period has elapsed.
    borrower, app, _, le, cd = (
        setup_application_ready_for_clear_to_close(
            clock_anchor="2026-03-02T10:00:00.000Z",
            le_apr_bps=650,
            cd_apr_bps=655,
            advance_to_after_trid=True,
        )
    )

    # Trigger: issue a NEW LOAN_ESTIMATE with apr_bps=700 (delta from
    # CD's 655 = 45 bps > 12, satisfying the "new LE differs from
    # latest CD by more than 12 bps" cascading-re-disclosure clause).
    new_le_res = api.issue_disclosure(
        app["id"],
        issue_disclosure_payload(
            kind="LOAN_ESTIMATE",
            apr_bps=700,
            total_loan_costs_cents=500_000,
            total_other_costs_cents=800_000,
        ),
        loan_officer_headers,
    )
    validate_success(new_le_res, 201)

    # Hop 1: previous LE (v1) is SUPERSEDED.
    le_rows = api.list_disclosures(
        app["id"], loan_officer_headers, params={"kind": "LOAN_ESTIMATE"},
    ).json()["data"]
    le_after = next(r for r in le_rows if r["id"] == le["id"])
    assert le_after["status"] == "SUPERSEDED", (
        "PRD §3.6: previous LE must be SUPERSEDED by the new LE of the "
        "same kind."
    )

    # Hop 2: ACKNOWLEDGED CD is SUPERSEDED by the cascading-re-disclosure.
    cd_rows = api.list_disclosures(
        app["id"], loan_officer_headers,
        params={"kind": "CLOSING_DISCLOSURE"},
    ).json()["data"]
    cd_after = next(r for r in cd_rows if r["id"] == cd["id"])
    assert cd_after["status"] == "SUPERSEDED", (
        "PRD §3.6: cascading re-disclosure marks the previously "
        "ACKNOWLEDGED CD as SUPERSEDED when the new LE drifts > 12 bps "
        "from the CD."
    )

    # Hop 3: clear-to-close now fails because the prior CD has been
    # SUPERSEDED and no fresh CD has been issued. PRD §3.10 lists the
    # CD-in-ISSUED/ACKNOWLEDGED + TRID-elapsed conditions and PRD §2.10
    # places UDAAP-review-required ahead of TRID. PRD does not uniquely
    # commit to which of the two error_ids fires when the latest CD is
    # SUPERSEDED — both are PRD-faithful readings of §3.10. PRD §3.6
    # names ERR_TRID_WAITING_PERIOD for the race-condition variant of
    # this scenario, but the sequential cascade case is silent. Accept
    # either as PRD-faithful.
    res = api.clear_to_close(app["id"], None, loan_officer_headers)
    validate_error_is_one_of(
        res,
        [
            ApiErrorId.ERR_TRID_WAITING_PERIOD.value,
            ApiErrorId.ERR_UDAAP_REVIEW_REQUIRED.value,
        ],
    )


def test_re_disclosure_cascade_supersedes_acknowledged_cd(
    api, loan_officer_headers,
):
    """PRD §3.6: "Cascading re-disclosure: when a new LOAN_ESTIMATE is
    issued whose apr_bps differs from the latest CLOSING_DISCLOSURE by
    more than 12 basis points, any ACKNOWLEDGED CLOSING_DISCLOSURE on
    the application is marked SUPERSEDED and a fresh CD becomes
    required."

    Claim (depth-2 of the depth-3 cascade): with an ACKNOWLEDGED CD on
    file at apr=655, issuing a fresh LE with apr=700 (delta=45 > 12)
    forces the CD to SUPERSEDED. We verify Hop 1 (prior LE -> superseded)
    and Hop 2 (ACK'd CD -> superseded) — Hop 3 is verified in the
    companion test test_re_disclosure_cascade_depth_3.

    # difficulty: transitive_cascade/re_disclosure_cascade_depth_3
    """
    _, app, _, le, cd = setup_application_ready_for_clear_to_close(
        clock_anchor="2026-03-02T10:00:00.000Z",
        le_apr_bps=650,
        cd_apr_bps=655,
        advance_to_after_trid=True,
    )
    # Issue a new LE at apr 700 (delta from CD's 655 = 45 > 12).
    validate_success(api.issue_disclosure(
        app["id"],
        issue_disclosure_payload(
            kind="LOAN_ESTIMATE",
            apr_bps=700,
            total_loan_costs_cents=500_000,
            total_other_costs_cents=800_000,
        ),
        loan_officer_headers,
    ), 201)

    # Hop 1: prior LE (version 1) is SUPERSEDED.
    rows = api.list_disclosures(
        app["id"], loan_officer_headers, params={"kind": "LOAN_ESTIMATE"},
    ).json()["data"]
    le_after = next(r for r in rows if r["id"] == le["id"])
    assert le_after["status"] == "SUPERSEDED"

    # Hop 2: ACK'd CD is SUPERSEDED via the cascading re-disclosure.
    cd_rows = api.list_disclosures(
        app["id"], loan_officer_headers,
        params={"kind": "CLOSING_DISCLOSURE"},
    ).json()["data"]
    cd_after = next(r for r in cd_rows if r["id"] == cd["id"])
    assert cd_after["status"] == "SUPERSEDED", (
        "PRD §3.6: cascading re-disclosure must mark the ACKNOWLEDGED "
        "CD as SUPERSEDED when the new LE drifts > 12 bps."
    )


# ===========================================================================
# Cash-to-close rounding order — PRD §3.6
# difficulty: combinatorial_formula/closing_cost_rounding_order_pinned
# ===========================================================================
def test_closing_cost_origination_tier_low_boundary(api, loan_officer_headers):
    """PRD §3.6: "if the principal is at most $417,000 (41,700,000
    cents), the origination fee is 1.00% of the principal ... The
    boundaries are inclusive at the low end of each higher tier — a
    principal of exactly 41,700,000 cents uses the 1.00% rate"

    Claim: with principal=20_000_000 (well within low tier), the
    origination component of cash_to_close uses 1.00% =>
    ROUND_HALF_UP(20_000_000 * 0.01) = 200_000.
    A CA Borrower with one tax line of 800_000 cents and state rate
    0.0050 produces ROUND_HALF_UP(800_000 * 0.0050) = 4000 cents.
    Per PRD §3.6 the rounding ORDER is per-line tax round, then sum,
    then origination tier, then total. The resulting cash_to_close is:
      total_loan_costs + (tax_lines_sum + total_other_costs) +
      origination - principal
      = 500_000 + (4_000 + 800_000) + 200_000 - 20_000_000
      = -18_496_000

    # difficulty: combinatorial_formula/closing_cost_rounding_order_pinned
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        annual_income_cents=12_000_000,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        state_code="CA",
        headers=loan_officer_headers,
    )
    res = api.issue_disclosure(
        app["id"],
        issue_disclosure_payload(
            kind="LOAN_ESTIMATE",
            apr_bps=650,
            total_loan_costs_cents=500_000,
            total_other_costs_cents=800_000,
        ),
        loan_officer_headers,
    )
    le = validate_success(res, 201)
    assert le["cash_to_close_cents"] == -18_496_000, (
        "PRD §3.6 pinned rounding order: cash_to_close should be "
        "500_000 + (4_000 + 800_000) + 200_000 - 20_000_000 = "
        f"-18_496_000. Got {le['cash_to_close_cents']}."
    )


def test_origination_fee_tier_boundary_at_417000_dollars(
    api, loan_officer_headers,
):
    """PRD §3.6: "a principal of exactly 41,700,000 cents uses the
    1.00% rate"

    Claim: principal = 41_700_000 falls in the low tier (1.00%); the
    origination component = ROUND_HALF_UP(41_700_000 * 0.01) = 417_000.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        annual_income_cents=15_000_000,
        sale_price_cents=42_000_000,
        requested_loan_amount_cents=41_700_000,
        state_code="CA",
        headers=loan_officer_headers,
    )
    res = api.issue_disclosure(
        app["id"],
        issue_disclosure_payload(
            kind="LOAN_ESTIMATE",
            apr_bps=650,
            total_loan_costs_cents=0,
            total_other_costs_cents=0,
        ),
        loan_officer_headers,
    )
    le = validate_success(res, 201)
    # CA state rate on total_other_costs=0 contributes 0.
    # tax_lines_sum=0; cash_to_close = 0 + 0 + 417_000 - 41_700_000
    # = -41_283_000.
    assert le["cash_to_close_cents"] == -41_283_000, (
        "PRD §3.6: principal=41_700_000 uses 1.00% (low tier "
        "inclusive). origination=417_000; expected cash_to_close="
        f"-41_283_000. Got {le['cash_to_close_cents']}."
    )


def test_origination_fee_tier_boundary_at_766000_dollars(
    api, loan_officer_headers,
):
    """PRD §3.6: "otherwise if the principal is at most $766,000
    (76,600,000 cents), the fee is 0.75% ... a principal of exactly
    76,600,000 cents uses the 0.75% rate."

    Claim: principal = 76_600_000 uses 0.75% (mid tier inclusive); the
    origination = ROUND_HALF_UP(76_600_000 * 0.0075) = 574_500.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    # Need annual_income_cents >= principal / 4 = 19_150_000.
    _, app = create_and_pre_qualify(
        annual_income_cents=20_000_000,
        sale_price_cents=80_000_000,
        requested_loan_amount_cents=76_600_000,
        state_code="CA",
        headers=loan_officer_headers,
    )
    res = api.issue_disclosure(
        app["id"],
        issue_disclosure_payload(
            kind="LOAN_ESTIMATE",
            apr_bps=650,
            total_loan_costs_cents=0,
            total_other_costs_cents=0,
        ),
        loan_officer_headers,
    )
    le = validate_success(res, 201)
    assert le["cash_to_close_cents"] == 0 + 0 + 574_500 - 76_600_000
