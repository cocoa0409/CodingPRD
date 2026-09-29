"""Corner cases in the computed figures of the cyber underwriting API.

Every expected figure below is recomputed from the formulas in the PRD: the
weighted posture score over the whole catalog, the layered and modified
premium, the business-interruption quantification with its pinned rounding
order, the engagement money as two independently rounded terms, the tower
allocation waterfall, the policy loss ratio, the renewal control credit and
the systemic aggregation model.

Each test builds all of its own state through the public API.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_error  # noqa: E402

from test_helpers import (  # noqa: E402
    ACTUARY_HEADERS,
    ADJUSTER_2_HEADERS,
    ADJUSTER_HEADERS,
    UNDERWRITER_HEADERS,
    ErrorId,
)
from test_helpers import constants as C  # noqa: E402
from test_helpers import factories as F  # noqa: E402
from test_helpers import fixtures  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_money,
    assert_ratio_4dp,
    assert_score_2dp,
    assert_total_count,
    data_of,
)

# The scan evidence that contradicts the applicant on one non-mandatory
# control: EMAIL_FILTERING is attested FULL but observed PARTIAL, which costs
# half of its weight of 15 and so takes the verified score from 95.00 to 87.50.
EMAIL_FILTERING_PARTIAL = [F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")]

CLAIM_CLOCK = "2026-09-10T00:00:00Z"


def _aurora_policy(api, **overrides):
    """Aurora Health bound with the standard tower.

    HEALTHCARE base rate 9,000 times revenue tier factor 1.00 times layer
    units 3.4 gives a gross of 30,600.00; the verified score of 87.50 earns
    -0.05, the retention of 250,000 earns -0.10 and the CSP_ALPHA dependency
    loads +0.08, so the bound premium is 30,600.00 * 0.93 = 28,458.00.
    """
    overrides.setdefault("findings", list(EMAIL_FILTERING_PARTIAL))
    return fixtures.bound_policy(api, **overrides)


# ==========================================================================
# Posture scoring
# ==========================================================================
def test_control_posture_read_reports_both_bases_and_the_quotable_flag(api):
    """A dedicated computed read returns both variants side by side as `attested_score` and `verified_score`, together with `mandatory_gap_count`, `mandatory_gap_control_keys`, the `min_score_for_coverage` threshold of 70, and a boolean `quotable`.

    Because it takes the lower of the two, identical attestations always yield
    a verified score that is lower than or equal to the attested score, and the
    verified basis can expose mandatory gaps the attested basis conceals.

    Attesting FULL/FULL/FULL/FULL/PARTIAL over weights 30/25/20/15/10 gives an
    attested numerator of 95 over a denominator of 100, and the scan's single
    PARTIAL observation on the non-mandatory EMAIL_FILTERING row costs half of
    its weight of 15, so the verified basis reads 87.50 and opens no gap.

    Design: Corner/calculations/control_posture_read_reports_both_bases_and_the_quotable_flag
    """
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    fixtures.seed_catalog(api)
    account = fixtures.create_account(api, C.ACCOUNT_AURORA)
    application = fixtures.create_application(api, account["id"])
    fixtures.attest_controls(api, application["id"], C.ATTEST_95)
    fixtures.submit_application(api, application["id"])
    scan = fixtures.order_scan(api, application["id"], scan_score=68)
    fixtures.complete_scan(api, scan["id"], findings=list(EMAIL_FILTERING_PARTIAL))

    posture = data_of(api.get_control_posture(application["id"], UNDERWRITER_HEADERS))

    assert_score_2dp(posture["attested_score"], 95.00, "attested_score")
    assert_score_2dp(posture["verified_score"], 87.50, "verified_score")
    assert posture["mandatory_gap_count"] == 0, posture
    assert posture["mandatory_gap_control_keys"] == [], posture
    assert float(posture["min_score_for_coverage"]) == 70.0, posture
    assert posture["quotable"] is True, posture

    application = fixtures.read_application(api, application["id"])
    assert_score_2dp(
        application["attested_control_score"], 95.00, "attested_control_score"
    )
    assert_score_2dp(
        application["verified_control_score"], 87.50, "verified_control_score"
    )


def test_unattested_control_counts_as_none_in_the_weighted_score(api):
    """The denominator is the sum of `weight` across every catalog row — the catalog has no status field, so there is no filtering and every row participates.

    On the **attested basis**, the level for a control is simply the
    `attested_level` of the application's attestation for that control, or
    `NONE` when the application has no attestation row for it.

    With EDR_COVERAGE (weight 20) unattested the numerator is 30 + 25 + 0 + 15
    + 5 = 75 over the full catalog denominator of 100, so the score is 75.00
    and not the 93.75 a denominator of attested weights alone would give.

    Design: Corner/calculations/unattested_control_counts_as_none_in_the_weighted_score
    """
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    fixtures.seed_catalog(api)
    account = fixtures.create_account(api, C.ACCOUNT_AURORA)
    application = fixtures.create_application(api, account["id"])
    fixtures.attest_controls(
        api,
        application["id"],
        {
            "MFA_PRIVILEGED": "FULL",
            "OFFLINE_BACKUPS": "FULL",
            "EMAIL_FILTERING": "FULL",
            "INCIDENT_RESPONSE_PLAN": "PARTIAL",
        },
    )

    posture = data_of(api.get_control_posture(application["id"], UNDERWRITER_HEADERS))

    assert_score_2dp(posture["attested_score"], 75.00, "attested_score")
    assert float(posture["attested_score"]) != 93.75, posture
    assert posture["verified_score"] is None, posture
    assert posture["quotable"] is False, posture
    assert posture["mandatory_gap_count"] == 1, posture
    assert posture["mandatory_gap_control_keys"] == ["EDR_COVERAGE"], posture

    application = fixtures.read_application(api, application["id"])
    assert_score_2dp(
        application["attested_control_score"], 75.00, "attested_control_score"
    )


def test_verified_score_ignores_failed_and_pending_scan_findings(api):
    """The governing scan is the single latest one: among the application's scans whose `status` is `COMPLETED`, take them in `completed_at` descending order and, where two share an instant, `created_at` descending order, and use the first.

    Failed and pending scans are ignored no matter how recent.

    Only the COMPLETED scan's single PARTIAL observation on EMAIL_FILTERING
    reaches the verified basis, so the score is 87.50; the FAILED scan's
    CRITICAL observation of MFA_PRIVILEGED at NONE, which would cost the whole
    weight of 30, contributes nothing at all.

    Design: Corner/calculations/verified_score_ignores_failed_and_pending_scan_findings
    """
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    fixtures.seed_catalog(api)
    account = fixtures.create_account(api, C.ACCOUNT_AURORA)
    application = fixtures.create_application(api, account["id"])
    fixtures.attest_controls(api, application["id"], C.ATTEST_95)
    fixtures.submit_application(api, application["id"])

    failed_scan = fixtures.order_scan(api, application["id"], scan_score=68)
    fixtures.complete_scan(
        api,
        failed_scan["id"],
        findings=[F.scan_finding("MFA_PRIVILEGED", "CRITICAL", "NONE")],
        outcome="FAILED",
    )
    pending_scan = fixtures.order_scan(api, application["id"], scan_score=68)
    governing_scan = fixtures.order_scan(api, application["id"], scan_score=68)

    completed = fixtures.complete_scan(
        api, governing_scan["id"], findings=list(EMAIL_FILTERING_PARTIAL)
    )

    assert completed["status"] == "COMPLETED", completed

    application = fixtures.read_application(api, application["id"])
    assert_score_2dp(
        application["verified_control_score"], 87.50, "verified_control_score"
    )
    assert float(application["verified_control_score"]) != 65.00, application
    assert float(application["verified_control_score"]) != 52.50, application
    assert application["mandatory_gap_count"] == 0, application
    assert application["status"] == "UNDERWRITING", application

    still_pending = data_of(api.get_external_scan(pending_scan["id"], UNDERWRITER_HEADERS))
    assert still_pending["status"] == "PENDING", still_pending

    account = data_of(api.get_insured_account(account["id"], UNDERWRITER_HEADERS))
    assert account["open_remediation_count"] == 0, account


# ==========================================================================
# The policy loss summary
# ==========================================================================
def test_loss_ratio_excludes_reversed_payments_from_the_paid_total(api):
    """The paid figure is the sum of `net_paid_usd` over every payment row whose `payment_status` is `POSTED` and whose claim belongs to this policy; reversed rows are excluded.

    The outstanding reserve is the sum of `reserved_amount_usd` over every
    claim of the policy whose `status` is not one of `SETTLED`, `DENIED`, or
    `CLOSED_NO_COVERAGE` — closed files hold no reserve.

    The one posted slice of 45,000.00 is reversed, so the paid leg falls to
    0.00 and the whole incurred figure is the 284,580.00 reserve of the open
    claim, giving exactly 284,580.00 / 28,458.00 = 10.0000.

    Design: Corner/calculations/loss_ratio_excludes_reversed_payments_from_the_paid_total
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    assert_money(policy["premium_usd"], 28458.00, "premium_usd")

    fixtures.set_clock(api, CLAIM_CLOCK)
    settled_claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    proof = fixtures.file_proof(
        api,
        settled_claim["id"],
        claimed_bi_loss_usd=300000,
        gross_profit_margin_pct=1.0,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    fixtures.accept_proof(api, proof["id"])

    # 60 compensable hours at an hourly baseline of 5,000.00 and a margin of
    # 1.0 assess 300,000.00; the retention absorbs 250,000.00, the remaining
    # 50,000.00 erodes BUSINESS_INTERRUPTION and 10 percent coinsurance leaves
    # a net of 45,000.00 on the single payment row.
    payments = fixtures.list_payments_for_claim(api, settled_claim["id"])
    assert len(payments) == 1, payments
    assert_money(payments[0]["net_paid_usd"], 45000.00, "net_paid_usd")

    reversed_row = data_of(
        api.reverse_claim_payment(
            payments[0]["id"], F.reverse_payment_payload(), ADJUSTER_2_HEADERS
        )
    )
    assert reversed_row["payment_status"] == "REVERSED", reversed_row

    open_claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="BEC",
        incident_discovered_at="2026-09-06T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE"],
        initial_reserve_usd=284580,
    )
    assert_money(open_claim["reserved_amount_usd"], 284580.00, "reserved_amount_usd")

    summary = data_of(api.get_policy_loss_summary(policy["id"], ACTUARY_HEADERS))

    assert_money(summary["paid_total_usd"], 0.00, "paid_total_usd")
    assert_money(summary["outstanding_reserve_usd"], 284580.00, "outstanding_reserve_usd")
    assert_money(summary["incurred_usd"], 284580.00, "incurred_usd")
    assert_ratio_4dp(summary["loss_ratio"], 10.0000, "loss_ratio")
    assert_money(
        summary["aggregate_limit_remaining_usd"],
        5000000.00,
        "aggregate_limit_remaining_usd",
    )
    assert summary["limit_status"] == "INTACT", summary


def test_loss_summary_sums_posted_payments_and_non_terminal_reserves(api):
    """The incurred figure is the paid figure plus the outstanding reserve, rounded half up to 2 decimal places, and the loss ratio is the incurred figure divided by the policy's `premium_usd`, rounded half up to 4 decimal places.

    Every claim of the policy participates regardless of notification date; the
    window is the whole policy, not a calendar period, and because the sums are
    order-insensitive no tie-break is needed.

    The settled claim contributes its 45,000.00 of posted payments but no
    reserve, the open claim contributes its 100,000.00 reserve, and
    145,000.00 / 28,458.00 rounds to 5.0952.

    Design: Corner/calculations/loss_summary_sums_posted_payments_and_non_terminal_reserves
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    assert_money(policy["premium_usd"], 28458.00, "premium_usd")

    fixtures.set_clock(api, CLAIM_CLOCK)
    settled_claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    proof = fixtures.file_proof(
        api,
        settled_claim["id"],
        claimed_bi_loss_usd=300000,
        gross_profit_margin_pct=1.0,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    fixtures.accept_proof(api, proof["id"])

    settled_claim = fixtures.read_claim(api, settled_claim["id"])
    assert settled_claim["status"] == "SETTLED", settled_claim
    assert_money(settled_claim["paid_total_usd"], 45000.00, "paid_total_usd")
    assert_money(
        settled_claim["retention_absorbed_usd"], 250000.00, "retention_absorbed_usd"
    )
    assert_money(settled_claim["reserved_amount_usd"], 0.00, "reserved_amount_usd")

    fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="DATA_THEFT",
        incident_discovered_at="2026-09-06T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE"],
        initial_reserve_usd=100000,
    )

    summary = data_of(api.get_policy_loss_summary(policy["id"], ACTUARY_HEADERS))

    assert_money(summary["paid_total_usd"], 45000.00, "paid_total_usd")
    assert_money(summary["outstanding_reserve_usd"], 100000.00, "outstanding_reserve_usd")
    assert_money(summary["incurred_usd"], 145000.00, "incurred_usd")
    assert_ratio_4dp(summary["loss_ratio"], 5.0952, "loss_ratio")
    assert_money(
        summary["aggregate_limit_remaining_usd"],
        4955000.00,
        "aggregate_limit_remaining_usd",
    )
    assert summary["limit_status"] == "PARTIALLY_ERODED", summary


# ==========================================================================
# Premium construction
# ==========================================================================
def test_revenue_tier_boundary_one_dollar_above_fifty_million_lifts_the_premium(api):
    """A revenue tier factor is applied: 1.00 when `annual_revenue_usd` is at most 50,000,000; 1.15 when it is above 50,000,000 and at most 250,000,000; and 1.35 when it is above 250,000,000.

    The gross premium is the base rate multiplied by the revenue tier factor
    multiplied by the layer units, rounded half up to 2 decimal places.

    At the ceiling the HEALTHCARE base of 9,000 times 1.00 times layer units
    3.4 grosses 30,600.00 and the 0.75 modifier prices 22,950.00; one dollar
    higher the factor of 1.15 grosses 35,190.00 and prices 26,392.50.

    Design: Corner/calculations/revenue_tier_boundary_one_dollar_above_fifty_million_lifts_the_premium
    """
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    fixtures.seed_catalog(api)
    at_ceiling_account = fixtures.create_account(
        api,
        C.ACCOUNT_AURORA,
        legal_name="Even Fifty Health",
        annual_revenue_usd=50000000,
        record_count=1000,
        primary_dependency_key="NONE",
    )
    over_account = fixtures.create_account(
        api,
        C.ACCOUNT_AURORA,
        legal_name="Dollar Over Health",
        annual_revenue_usd=50000001,
        record_count=1000,
        primary_dependency_key="NONE",
    )
    at_ceiling_app = fixtures.create_application(
        api,
        at_ceiling_account["id"],
        dependent_bi_definition="BROAD_SYSTEM_FAILURE",
    )
    fixtures.attest_controls(api, at_ceiling_app["id"], C.ATTEST_95)
    over_app = fixtures.create_application(
        api,
        over_account["id"],
        dependent_bi_definition="BROAD_SYSTEM_FAILURE",
    )
    fixtures.attest_controls(api, over_app["id"], C.ATTEST_95)
    fixtures.submit_application(api, at_ceiling_app["id"])

    submitted_over = fixtures.submit_application(api, over_app["id"])

    assert_money(
        submitted_over["indicative_premium_usd"], 26392.50, "indicative_premium_usd"
    )
    at_ceiling_app = fixtures.read_application(api, at_ceiling_app["id"])
    assert_money(
        at_ceiling_app["indicative_premium_usd"], 22950.00, "indicative_premium_usd"
    )
    step = round(
        float(submitted_over["indicative_premium_usd"])
        - float(at_ceiling_app["indicative_premium_usd"]),
        2,
    )
    assert step == 3442.50, step
    assert_score_2dp(
        submitted_over["attested_control_score"], 95.00, "attested_control_score"
    )
    assert_score_2dp(
        at_ceiling_app["attested_control_score"], 95.00, "attested_control_score"
    )
    assert submitted_over["status"] == "SUBMITTED", submitted_over
    assert at_ceiling_app["status"] == "SUBMITTED", at_ceiling_app


# ==========================================================================
# Business interruption quantification
# ==========================================================================
def test_extra_expense_cap_is_measured_against_the_rounded_bi_component(api):
    """`extra_expense_component_usd` is the lesser of `extra_expense_usd` and 25 percent of `bi_component_usd`, rounded half up to 2 decimal places. The cap is computed from the **already rounded** `bi_component_usd`, not from the raw product behind it.

    `assessed_indemnity_usd` is `bi_component_usd` less
    `mitigation_component_usd` plus `extra_expense_component_usd`, rounded half
    up to 2 decimal places.

    A 72.00-hour outage less the 12-hour waiting period leaves 60.00
    compensable hours, which at 43,800,000.00 / 8,760 = 5,000.00 an hour and a
    margin of 0.62 gives a bi component of 186,000.00; the claimed 60,000.00 of
    extra expense is therefore cut to 46,500.00 and, after the 20,000.00
    mitigation offset, the indemnity is 212,500.00.

    Design: Corner/calculations/extra_expense_cap_is_measured_against_the_rounded_bi_component
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]

    fixtures.set_clock(api, CLAIM_CLOCK)
    claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    proof = fixtures.file_proof(
        api,
        claim["id"],
        claimed_bi_loss_usd=250000,
        gross_profit_margin_pct=0.62,
        extra_expense_usd=60000,
        mitigation_savings_usd=20000,
    )

    accepted = fixtures.accept_proof(api, proof["id"])

    assert accepted["status"] == "ACCEPTED", accepted
    assert float(accepted["outage_hours"]) == 72.00, accepted
    assert float(accepted["compensable_hours"]) == 60.00, accepted
    assert_money(accepted["bi_component_usd"], 186000.00, "bi_component_usd")
    assert_money(
        accepted["mitigation_component_usd"], 20000.00, "mitigation_component_usd"
    )
    assert_money(
        accepted["extra_expense_component_usd"],
        46500.00,
        "extra_expense_component_usd",
    )
    assert float(accepted["extra_expense_component_usd"]) != 60000.00, accepted
    assert_money(accepted["assessed_indemnity_usd"], 212500.00, "assessed_indemnity_usd")
    assert accepted["baseline_method_applied"] == "TRAILING_12M", accepted


def test_outage_exactly_equal_to_the_waiting_period_returns_422(api):
    """The request carries `expected_claim_version` per §2.7, and the compensable hours computed against the eligible business interruption section must be strictly greater than zero — a proof whose entire outage sits inside the waiting period is refused with `ERR_WAITING_PERIOD_NOT_SATISFIED`.

    `compensable_hours` is the greater of zero and `outage_hours` less the
    eligible section's `waiting_period_hours`.

    An outage of exactly 12.00 hours against a waiting period of 12 hours
    leaves nothing compensable, so the filing is refused rather than accepted
    for a zero indemnity.

    Design: Corner/calculations/outage_exactly_equal_to_the_waiting_period_returns_422
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    assert (
        float(chain["sections"]["BUSINESS_INTERRUPTION"]["waiting_period_hours"]) == 12.0
    ), chain["sections"]["BUSINESS_INTERRUPTION"]

    fixtures.set_clock(api, CLAIM_CLOCK)
    claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-05T12:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )

    response = api.create_proof_of_loss(
        claim["id"],
        F.proof_of_loss_payload(
            claim["version"],
            claimed_bi_loss_usd=250000,
            gross_profit_margin_pct=0.62,
            extra_expense_usd=60000,
            mitigation_savings_usd=20000,
        ),
        ADJUSTER_HEADERS,
    )

    validate_error(response, ErrorId.WAITING_PERIOD_NOT_SATISFIED)

    claim = fixtures.read_claim(api, claim["id"])
    assert claim["status"] == "COVERAGE_CONFIRMED", claim
    assert_total_count(
        api.list_proofs_of_loss(
            ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
        ),
        0,
    )
    assert_money(claim["reserved_amount_usd"], 300000.00, "reserved_amount_usd")
    assert_money(claim["paid_total_usd"], 0.00, "paid_total_usd")


def test_one_hour_past_the_waiting_period_pays_only_the_capped_extra_expense(api):
    """`mitigation_component_usd` is the lesser of `mitigation_savings_usd` and `bi_component_usd`, rounded half up to 2 decimal places; the credit can never exceed the component it offsets.

    The amount absorbed by this allocation is the lesser of that available
    retention and the loss amount, rounded half up to 2 decimal places; it is
    added to the claim's `retention_absorbed_usd`, which therefore never
    exceeds the policy's `retention_usd`.

    The loss allocated to a section is the lesser of the remainder and that
    section's `sublimit_remaining_usd`, rounded half up to 2 decimal places; a
    section whose allocation would be zero or less is skipped without producing
    a zero-value payment row at all.

    A 13.00-hour outage leaves 1.00 compensable hour, so the bi component is
    3,100.00, the 20,000.00 of mitigation savings is held down to that same
    3,100.00, the extra expense is capped at 775.00, and the whole 775.00
    indemnity is absorbed by the 250,000.00 retention.

    Design: Corner/calculations/one_hour_past_the_waiting_period_pays_only_the_capped_extra_expense
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]

    fixtures.set_clock(api, CLAIM_CLOCK)
    claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-05T13:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    proof = fixtures.file_proof(
        api,
        claim["id"],
        claimed_bi_loss_usd=250000,
        gross_profit_margin_pct=0.62,
        extra_expense_usd=60000,
        mitigation_savings_usd=20000,
    )

    accepted = fixtures.accept_proof(api, proof["id"])

    assert float(accepted["compensable_hours"]) == 1.00, accepted
    assert_money(accepted["bi_component_usd"], 3100.00, "bi_component_usd")
    assert_money(
        accepted["mitigation_component_usd"], 3100.00, "mitigation_component_usd"
    )
    assert_money(
        accepted["extra_expense_component_usd"], 775.00, "extra_expense_component_usd"
    )
    assert_money(accepted["assessed_indemnity_usd"], 775.00, "assessed_indemnity_usd")

    claim = fixtures.read_claim(api, claim["id"])
    assert claim["status"] == "SETTLED", claim
    assert_money(claim["retention_absorbed_usd"], 775.00, "retention_absorbed_usd")
    assert_money(claim["paid_total_usd"], 0.00, "paid_total_usd")
    assert_total_count(
        api.list_claim_payments(
            ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
        ),
        0,
    )

    policy = fixtures.read_policy(api, policy["id"])
    assert_money(
        policy["aggregate_limit_remaining_usd"],
        5000000.00,
        "aggregate_limit_remaining_usd",
    )
    assert policy["limit_status"] == "INTACT", policy


def test_accept_override_switches_the_bi_baseline_to_the_prior_year_window(api):
    """The adjuster may supply a `baseline_method_override`; `baseline_method_applied` records the variant actually used, which is the override when one is supplied and the policy's `bi_baseline_method` otherwise.

    Under `SAME_PERIOD_PRIOR_YEAR` it is `prior_year_same_period_revenue_usd`
    divided by `prior_year_same_period_hours`, taken from the matching
    prior-year window, so a seasonal peak raises every downstream component and
    the assessed indemnity with it.

    The prior-year window gives 1,200,000.00 / 200 = 6,000.00 an hour, so 60.00
    compensable hours at a margin of 0.62 assess a bi component of 223,200.00,
    an extra expense capped at 55,800.00 and, after the 20,000.00 mitigation
    offset, an indemnity of 259,000.00 rather than the 212,500.00 the policy's
    own TRAILING_12M baseline would produce.

    Design: Corner/calculations/accept_override_switches_the_bi_baseline_to_the_prior_year_window
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    assert policy["bi_baseline_method"] == "TRAILING_12M", policy

    fixtures.set_clock(api, CLAIM_CLOCK)
    claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    proof = fixtures.file_proof(
        api,
        claim["id"],
        claimed_bi_loss_usd=250000,
        trailing_12m_revenue_usd=43800000,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=0.62,
        extra_expense_usd=60000,
        mitigation_savings_usd=20000,
    )

    accepted = data_of(
        api.accept_proof_of_loss(
            proof["id"],
            ADJUSTER_2_HEADERS,
            {"baseline_method_override": "SAME_PERIOD_PRIOR_YEAR"},
        )
    )

    assert accepted["baseline_method_applied"] == "SAME_PERIOD_PRIOR_YEAR", accepted
    assert_money(accepted["bi_component_usd"], 223200.00, "bi_component_usd")
    assert_money(
        accepted["mitigation_component_usd"], 20000.00, "mitigation_component_usd"
    )
    assert_money(
        accepted["extra_expense_component_usd"],
        55800.00,
        "extra_expense_component_usd",
    )
    assert_money(accepted["assessed_indemnity_usd"], 259000.00, "assessed_indemnity_usd")
    assert float(accepted["assessed_indemnity_usd"]) != 212500.00, accepted

    payments = fixtures.list_payments_for_claim(api, claim["id"])
    assert len(payments) == 1, payments
    assert_money(payments[0]["gross_amount_usd"], 9000.00, "gross_amount_usd")
    assert_money(
        payments[0]["coinsurance_deduction_usd"], 900.00, "coinsurance_deduction_usd"
    )
    assert_money(payments[0]["net_paid_usd"], 8100.00, "net_paid_usd")

    policy = fixtures.read_policy(api, policy["id"])
    assert_money(
        policy["aggregate_limit_remaining_usd"],
        4991900.00,
        "aggregate_limit_remaining_usd",
    )
    bi_section = data_of(
        api.get_coverage_section(
            chain["sections"]["BUSINESS_INTERRUPTION"]["id"], UNDERWRITER_HEADERS
        )
    )
    assert_money(
        bi_section["sublimit_remaining_usd"], 1991000.00, "sublimit_remaining_usd"
    )

    claim = fixtures.read_claim(api, claim["id"])
    assert claim["status"] == "SETTLED", claim
    assert_money(claim["retention_absorbed_usd"], 250000.00, "retention_absorbed_usd")
    assert_money(claim["paid_total_usd"], 8100.00, "paid_total_usd")
