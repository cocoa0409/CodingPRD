"""Claim pricing, estimate/final reconciliation, adjudication fork, and OCC.

Covers difficulty rules: dual_variant_calc (estimated vs final divergence),
combinatorial_formula (per-day-then-sum rounding), non_linear_state_machine
(adjudicate PAID vs REJECTED fork), plus corner pricing/OCC/state/error instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
    factories as f,
)

COORD = TEST_USERS["admissions_coordinator_headers"]
MDS = TEST_USERS["mds_coordinator_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]


# =====================================================================
# Difficulty/dual_variant_calc/claim_estimated_vs_final_diverge_on_unpaid_bedhold
# =====================================================================

def test_estimated_vs_final_diverge_on_unpaid_medicare_bedhold():
    """PRD §3.9: "Estimating a draft claim moves it from DRAFT to ESTIMATED and writes
    estimated_amount_cents using the forward-looking variant, in which the billed day
    set is every calendar day in the inclusive period projected as fully covered, with
    no bed-hold deductions".
    PRD §3.9: "Finalizing an estimated claim moves it from ESTIMATED to FINALIZED and
    writes final_amount_cents using the chronological variant, in which the billed day
    set is the calendar days in the inclusive period minus any day that falls inside a
    closed or converted bed-hold's leave window beyond that hold's paid_day_count ...
    The variance_cents is then set to the final_amount_cents minus the
    estimated_amount_cents".

    Design: Difficulty/dual_variant_calc/claim_estimated_vs_final_diverge_on_unpaid_bedhold
    """
    facility, resident, admission, assessment = fixtures.setup_priced_medicare_admission()
    # Bed-hold over day 5 (2026-02-05 -> 2026-02-06), closed RETURNED, unpaid under Medicare.
    bh = get_success_data(api_client.create_bed_hold(
        admission["id"],
        f.create_bed_hold_payload(leave_reason="HOSPITAL",
                                  leave_start_at="2026-02-05T00:00:00Z",
                                  expected_return_at="2026-02-06T00:00:00Z"), COORD))
    get_success_data(api_client.close_bed_hold(
        bh["id"], {"return_outcome": "RETURNED", "actual_return_at": "2026-02-06T00:00:00Z"}, COORD))

    claim = fixtures.create_draft_claim(
        admission["id"], assessment["id"],
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    est = validate_success(api_client.estimate_claim(claim["id"], {}, BILLING))
    assert est["estimated_amount_cents"] == 452442, (
        f"estimated must be 452442, got {est['estimated_amount_cents']}")

    fin = validate_success(api_client.finalize_claim(claim["id"], {}, BILLING))
    assert fin["final_amount_cents"] == 397275, (
        f"final must be 397275, got {fin['final_amount_cents']}")
    assert fin["variance_cents"] == -55167, (
        f"variance must be -55167, got {fin['variance_cents']}")


def test_estimated_equals_final_when_no_bedhold():
    """PRD §3.9: "the two amounts diverge precisely when an unpaid bed-hold day overlaps
    the period".

    Design: Difficulty/dual_variant_calc/claim_estimated_vs_final_diverge_on_unpaid_bedhold
    """
    # With no bed-hold, estimated and final coincide and variance is 0 (the complement
    # of the divergence case).
    facility, admission, assessment, finalized = fixtures.setup_finalized_claim(
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    assert finalized["final_amount_cents"] == finalized["estimated_amount_cents"], (
        "no unpaid bed-hold day -> final must equal estimated")
    assert finalized["variance_cents"] == 0, f"expected variance 0, got {finalized['variance_cents']}"


# =====================================================================
# Difficulty/combinatorial_formula/claim_rounding_per_day_then_sum_not_sum_then_round
# =====================================================================

def test_claim_rounding_per_day_then_sum():
    """PRD §3.9: "The claim total rounds per day and then sums: for each billed covered
    day, the day's unrounded per-diem rate is rounded to the nearest cent using
    round-half-up, and those rounded per-day amounts are summed — never sum-then-round".

    Design: Difficulty/combinatorial_formula/claim_rounding_per_day_then_sum_not_sum_then_round
    """
    facility, admission, assessment, estimated = fixtures.setup_estimated_claim(
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    assert estimated["estimated_amount_cents"] == 452442, (
        f"per-day-then-sum must yield 452442 (not 452439), got {estimated['estimated_amount_cents']}")
    assert estimated["billed_day_count"] == 6, (
        f"expected billed_day_count 6, got {estimated['billed_day_count']}")


def test_claim_billed_day_count_matches_inclusive_period():
    """PRD §3.9: "the billed day set is every calendar day in the inclusive period
    projected as fully covered ... it also computes billed_day_count".

    Design: Difficulty/combinatorial_formula/claim_rounding_per_day_then_sum_not_sum_then_round
    """
    facility, admission, assessment, estimated = fixtures.setup_estimated_claim(
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    assert estimated["billed_day_count"] == 6, (
        f"inclusive 02-01..02-06 is 6 days, got {estimated['billed_day_count']}")


# =====================================================================
# Difficulty/non_linear_state_machine/claim_adjudicate_branch_fork_paid_vs_rejected
# =====================================================================

def test_adjudicate_paid_credits_covered_day_count():
    """PRD §3.9: "When the decision is PAID, the claim moves to PAID and the admission's
    covered_day_count is increased by the claim's billed_day_count".

    Design: Difficulty/non_linear_state_machine/claim_adjudicate_branch_fork_paid_vs_rejected
    """
    facility, admission, assessment, submitted = fixtures.setup_submitted_claim(
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    data = validate_success(api_client.adjudicate_claim(submitted["id"], {"decision": "PAID"}, BILLING))
    assert data["status"] == "PAID", f"expected PAID, got {data['status']}"
    adm = validate_success(api_client.get_admission(admission["id"], BILLING))
    assert adm["covered_day_count"] == 6, (
        f"PAID must add billed_day_count (6) to covered_day_count, got {adm['covered_day_count']}")


def test_adjudicate_rejected_leaves_covered_day_count_unchanged():
    """PRD §3.9: "When the decision is REJECTED, the claim moves to REJECTED, the
    driving assessment is left unchanged, and there is no change to covered_day_count".

    Design: Difficulty/non_linear_state_machine/claim_adjudicate_branch_fork_paid_vs_rejected
    """
    facility, admission, assessment, submitted = fixtures.setup_submitted_claim(
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    data = validate_success(api_client.adjudicate_claim(submitted["id"], {"decision": "REJECTED"}, BILLING))
    assert data["status"] == "REJECTED", f"expected REJECTED, got {data['status']}"
    adm = validate_success(api_client.get_admission(admission["id"], BILLING))
    assert adm["covered_day_count"] == 0, (
        f"REJECTED must leave covered_day_count at 0, got {adm['covered_day_count']}")


# =====================================================================
# Corner/state_machines/claim_adjudicate_rejected_leaves_covered_day_count_unchanged
# =====================================================================

def test_rejected_branch_status_and_ledger():
    """PRD §3.9: "When the decision is REJECTED, the claim moves to REJECTED ... and
    there is no change to covered_day_count".

    Design: Corner/state_machines/claim_adjudicate_rejected_leaves_covered_day_count_unchanged
    """
    facility, admission, assessment, submitted = fixtures.setup_submitted_claim(
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-06T00:00:00Z")
    data = validate_success(api_client.adjudicate_claim(submitted["id"], {"decision": "REJECTED"}, BILLING))
    assert data["status"] == "REJECTED"
    adm = validate_success(api_client.get_admission(admission["id"], BILLING))
    assert adm["covered_day_count"] == 0


# =====================================================================
# Corner/calculations/pdpm_nta_front_load_first_three_days
# =====================================================================

def test_nta_front_load_first_three_days():
    """PRD §3.9: "for NTA, the factor is 3.00 for stay-days 1 through 3 and 1.00
    thereafter".
    PRD §3.9: "the day's unrounded per-diem rate is rounded to the nearest cent using
    round-half-up, and those rounded per-day amounts are summed".

    Design: Corner/calculations/pdpm_nta_front_load_first_three_days
    """
    facility, resident, admission, assessment = fixtures.setup_priced_medicare_admission()
    claim = fixtures.create_draft_claim(
        admission["id"], assessment["id"],
        period_start_at="2026-02-01T00:00:00Z", period_end_at="2026-02-03T00:00:00Z")
    data = validate_success(api_client.estimate_claim(claim["id"], {}, BILLING))
    assert data["estimated_amount_cents"] == 286941, (
        f"3 front-loaded days at 95647 each must be 286941, got {data['estimated_amount_cents']}")
    assert data["billed_day_count"] == 3, f"expected billed_day_count 3, got {data['billed_day_count']}"


# =====================================================================
# Corner/state_machines/claim_initial_state_is_draft
# =====================================================================

def test_claim_initial_state_is_draft():
    """PRD §3.9: "A new claim begins in DRAFT with billed_day_count,
    estimated_amount_cents, and final_amount_cents initialized to 0".

    Design: Corner/state_machines/claim_initial_state_is_draft
    """
    facility, resident, admission, assessment = fixtures.setup_priced_medicare_admission()
    claim = fixtures.create_draft_claim(admission["id"], assessment["id"])
    assert claim["status"] == "DRAFT", f"expected DRAFT, got {claim['status']}"


# =====================================================================
# Corner/state_machines/claim_finalize_from_draft_returns_invalid_state
# =====================================================================

def test_finalize_from_draft_invalid_state():
    """PRD §2.7: "on a transition endpoint, the target resource must be in a state from
    which the requested transition is legal, else ERR_INVALID_STATE".
    PRD §3.9: "Finalizing an estimated claim moves it from ESTIMATED to FINALIZED".

    Design: Corner/state_machines/claim_finalize_from_draft_returns_invalid_state
    """
    facility, resident, admission, assessment = fixtures.setup_priced_medicare_admission()
    claim = fixtures.create_draft_claim(admission["id"], assessment["id"])
    validate_error(api_client.finalize_claim(claim["id"], {}, BILLING),
                   ApiErrorId.ERR_INVALID_STATE.value)


# =====================================================================
# Corner/cross_cutting_complexity_layers/occ_claim_submit_stale_version_rejected
# =====================================================================

def test_claim_submit_stale_version_rejected():
    """PRD §2.6: "The request must include expected_claim_version, carrying the client's
    last observed version of the claim ... if a submit arrives carrying a stale
    expected_claim_version that no longer matches the claim's current version, it is
    rejected with ERR_STALE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_claim_submit_stale_version_rejected
    """
    facility, admission, assessment, finalized = fixtures.setup_finalized_claim()
    resp = api_client.submit_claim(
        finalized["id"], {"expected_claim_version": finalized["version"] - 1}, BILLING)
    assert resp.status_code == 412, f"expected 412, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# =====================================================================
# Corner/validations/error_not_medicare_covered_on_claim_estimate
# =====================================================================

def test_estimate_on_non_covered_admission_rejected():
    """PRD §3.9: "Estimating requires that the parent admission's medicare_covered be
    true, or it is rejected with ERR_NOT_MEDICARE_COVERED".

    Design: Corner/validations/error_not_medicare_covered_on_claim_estimate
    """
    fixtures.seed_standard_rate_book()
    # NON_COVERED Medicare admission (no qualifying stay, allow_non_covered=True).
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=False, allow_non_covered=True)
    assessment = fixtures.create_submitted_assessment(admission["id"])
    claim = fixtures.create_draft_claim(admission["id"], assessment["id"])
    validate_error(api_client.estimate_claim(claim["id"], {}, BILLING),
                   ApiErrorId.ERR_NOT_MEDICARE_COVERED.value)


# =====================================================================
# Corner/validations/error_claim_period_invalid_end_before_start
# =====================================================================

def test_claim_period_end_before_start_rejected():
    """PRD §3.9: "The claim period must lie within the stay window ... and the period
    end must be on or after the period start; a malformed period is rejected with
    ERR_CLAIM_PERIOD_INVALID".

    Design: Corner/validations/error_claim_period_invalid_end_before_start
    """
    facility, resident, admission, assessment = fixtures.setup_priced_medicare_admission()
    payload = f.create_claim_payload(
        assessment["id"], period_start_at="2026-02-06T00:00:00Z", period_end_at="2026-02-01T00:00:00Z")
    validate_error(api_client.create_claim(admission["id"], payload, BILLING),
                   ApiErrorId.ERR_CLAIM_PERIOD_INVALID.value)


# =====================================================================
# Corner/endpoints/list_claims_by_driving_assessment_id_reverse_reachability
# =====================================================================

def test_list_claims_by_driving_assessment_id():
    """PRD §3.9: "A draft claim is created against an admission with a
    driving_assessment_id (the submitted assessment whose case-mix groups price the
    claim)".
    PRD §2.3: "The total_count reflects the total number of matching resources before
    pagination is applied".

    Design: Corner/endpoints/list_claims_by_driving_assessment_id_reverse_reachability
    """
    facility, resident, admission, assessment = fixtures.setup_priced_medicare_admission()
    claim = fixtures.create_draft_claim(admission["id"], assessment["id"])
    resp = api_client.list_claims(BILLING, params={"driving_assessment_id": assessment["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert data[0]["id"] == claim["id"], "filter must return the claim driven by that assessment"
