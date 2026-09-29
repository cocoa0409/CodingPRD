"""Consistency model: a cascade completes inside the request that triggers it,
so the reads issued straight afterwards already show the settled world.

Every test builds its own world through the public API; the harness restarts
the server with an empty database before each test.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    ADJUSTER_2_HEADERS,
    ADJUSTER_HEADERS,
    UNDERWRITER_HEADERS,
    factories as F,
    fixtures as X,
)
from test_helpers.assertions import assert_money, assert_ratio_4dp


def test_acceptance_response_already_reflects_the_whole_cascade(api):
    """PRD §2.8: "First, cascades run to completion inside the same request: consistency is immediate, and a caller never observes a half-propagated state."
    PRD §3.8: "3. Because the claim was approved, the tower waterfall runs over `assessed_indemnity_usd` with a `loss_source` of `PROOF_OF_LOSS`, creating one payment row per eroded section, updating the claim's `retention_absorbed_usd`, `paid_total_usd`, and `unallocated_loss_usd`, zeroing `reserved_amount_usd` to 0.00, and moving the claim on to `SETTLED`."
    PRD §3.8: "4. Because those payments posted, each affected section's `sublimit_remaining_usd` and the policy's `aggregate_limit_remaining_usd` are decremented and `limit_status` is recomputed."
    PRD §3.8: "1. The proof moves from `UNDER_REVIEW` to `ACCEPTED` with `baseline_method_applied`, `outage_hours`, `compensable_hours`, and every quantification component written, and its `version` incremented by 1."
    PRD §3.8: "Retention comes first, once per claim, off the top, before any section is touched."
    PRD §3.9: "A computed read exposes these figures directly as `paid_total_usd`, `outstanding_reserve_usd`, `incurred_usd`, and `loss_ratio`, alongside `aggregate_limit_remaining_usd` and `limit_status`."

    Design: Corner/consistency_model/acceptance_response_already_reflects_the_whole_cascade
    """
    # Aurora Health bound at a verified score of 87.50, so premium_usd is
    # 28,458.00; the tower carries a 250,000.00 retention and a 2,000,000.00
    # BUSINESS_INTERRUPTION sublimit at 0.1 coinsurance on a 5,000,000.00
    # aggregate.
    chain = X.bound_policy(api, findings=[F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")])
    policy_id = chain["policy"]["id"]
    bi_section = chain["sections"]["BUSINESS_INTERRUPTION"]
    assert_money(chain["policy"]["premium_usd"], 28458.00, "premium_usd")

    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        policy_id,
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    # A 72-hour outage less the 12-hour waiting period leaves 60 compensable
    # hours; the trailing baseline is 43,800,000 / 8,760 = 5,000.00 an hour at a
    # 1.00 margin, so the assessed indemnity is 300,000.00.
    proof = X.file_proof(
        api,
        claim["id"],
        claimed_bi_loss_usd=300000,
        trailing_12m_revenue_usd=43800000,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=1.0,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    assert proof["status"] == "UNDER_REVIEW", (
        f"the filed proof should sit UNDER_REVIEW, got {proof['status']}"
    )

    resp = api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS)
    accepted = validate_success(resp, expected_status=200)

    # The trigger response itself already carries the quantification.
    assert accepted["status"] == "ACCEPTED", (
        f"proof status in the accept response: expected ACCEPTED, got {accepted['status']}"
    )
    assert_money(accepted["assessed_indemnity_usd"], 300000.00, "assessed_indemnity_usd")
    assert float(accepted["compensable_hours"]) == 60.0, (
        f"compensable_hours: expected 60, got {accepted['compensable_hours']}"
    )

    # No epoch call, no retry, no polling: the first read already sees the end
    # of the cascade.
    settled = X.read_claim(api, claim["id"])
    assert settled["status"] == "SETTLED", (
        f"claim status immediately after acceptance: expected SETTLED, got {settled['status']}"
    )
    assert_money(settled["retention_absorbed_usd"], 250000.00, "retention_absorbed_usd")
    assert_money(settled["paid_total_usd"], 45000.00, "paid_total_usd")
    assert_money(settled["reserved_amount_usd"], 0.00, "reserved_amount_usd")

    rows, meta = validate_paginated(
        api.list_claim_payments(
            ADJUSTER_HEADERS,
            params={"incident_claim_id": claim["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one section eroded, so expected total_count 1, got {meta['total_count']}"
    )
    payment = rows[0]
    assert payment["payment_status"] == "POSTED", (
        f"payment_status: expected POSTED, got {payment['payment_status']}"
    )
    assert payment["loss_source"] == "PROOF_OF_LOSS", (
        f"loss_source: expected PROOF_OF_LOSS, got {payment['loss_source']}"
    )
    assert payment["coverage_section_id"] == bi_section["id"], (
        "the ransomware interruption must erode the BUSINESS_INTERRUPTION section, got "
        f"{payment['coverage_section_id']}"
    )
    assert_money(payment["gross_amount_usd"], 50000.00, "gross_amount_usd")
    assert_money(payment["coinsurance_deduction_usd"], 5000.00, "coinsurance_deduction_usd")
    assert_money(payment["net_paid_usd"], 45000.00, "net_paid_usd")
    assert_money(payment["retention_applied_usd"], 250000.00, "retention_applied_usd")

    eroded_section = validate_success(
        api.get_coverage_section(bi_section["id"], UNDERWRITER_HEADERS), expected_status=200
    )
    assert_money(eroded_section["sublimit_remaining_usd"], 1950000.00, "sublimit_remaining_usd")

    eroded_policy = X.read_policy(api, policy_id)
    assert_money(
        eroded_policy["aggregate_limit_remaining_usd"],
        4955000.00,
        "aggregate_limit_remaining_usd",
    )
    assert eroded_policy["limit_status"] == "PARTIALLY_ERODED", (
        f"limit_status: expected PARTIALLY_ERODED, got {eroded_policy['limit_status']}"
    )

    summary = validate_success(
        api.get_policy_loss_summary(policy_id, UNDERWRITER_HEADERS), expected_status=200
    )
    assert_money(summary["paid_total_usd"], 45000.00, "loss summary paid_total_usd")
    assert_ratio_4dp(summary["loss_ratio"], 1.5813, "loss_ratio")
