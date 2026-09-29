"""Corner cases in the computed figures of the cyber underwriting API (continued).

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
    ADJUSTER_HEADERS,
    PANEL_ADMIN_HEADERS,
    UNDERWRITER_HEADERS,
    ErrorId,
)
from test_helpers import constants as C  # noqa: E402
from test_helpers import factories as F  # noqa: E402
from test_helpers import fixtures  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_instant,
    assert_money,
    assert_ratio_4dp,
    assert_total_count,
    data_of,
    find_row,
    get_rows,
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


def _forensics_panel(api):
    """Three ACTIVE forensics firms, created oldest first at distinct instants."""
    fixtures.set_clock(api, "2026-09-09T00:00:00Z")
    ironclad = fixtures.create_vendor(
        api,
        F.panel_vendor_payload(
            vendor_name="Ironclad Forensics",
            vendor_type="FORENSICS",
            pre_approved_hourly_rate_usd=500,
            per_record_notification_rate_usd=0,
            specialty_sectors=["HEALTHCARE", "FINANCIAL"],
            tier=1,
            capacity_concurrent_engagements=1,
        ),
    )
    fixtures.set_clock(api, "2026-09-09T01:00:00Z")
    beacon = fixtures.create_vendor(
        api,
        F.panel_vendor_payload(
            vendor_name="Beacon DFIR",
            vendor_type="FORENSICS",
            pre_approved_hourly_rate_usd=450,
            per_record_notification_rate_usd=0,
            specialty_sectors=["HEALTHCARE"],
            tier=2,
            capacity_concurrent_engagements=2,
        ),
    )
    fixtures.set_clock(api, "2026-09-09T02:00:00Z")
    sable = fixtures.create_vendor(
        api,
        F.panel_vendor_payload(
            vendor_name="Sable DFIR",
            vendor_type="FORENSICS",
            pre_approved_hourly_rate_usd=450,
            per_record_notification_rate_usd=0,
            specialty_sectors=["HEALTHCARE"],
            tier=2,
            capacity_concurrent_engagements=2,
        ),
    )
    return ironclad, beacon, sable


# ==========================================================================
# Vendor engagements and the waterfall
# ==========================================================================
def test_legal_counsel_cost_walks_first_party_then_third_party_liability(api):
    """That mapping is fixed: `FORENSICS`, `NOTIFICATION`, and `PR_CRISIS` costs are eligible against `FIRST_PARTY_RESPONSE` only; `LEGAL_COUNSEL` costs are eligible against `FIRST_PARTY_RESPONSE` and `THIRD_PARTY_LIABILITY`; and `RANSOM_NEGOTIATION` costs are eligible against `CYBER_EXTORTION` only.

    `retention_applied_usd` carries the retention absorbed by this allocation
    on the **first** payment row of the allocation only and 0.00 on every
    subsequent row, so the retention is visible exactly once and never
    double-counted.

    The remainder then walks the eligible sections of the policy in
    `erosion_priority` ascending order, breaking ties on `created_at`
    ascending.

    2,000 hours at 800.00 incur 1,600,000.00; the retention takes 250,000.00
    off the top, FIRST_PARTY_RESPONSE is exhausted at its 1,000,000.00
    sublimit, and the 350,000.00 balance falls to THIRD_PARTY_LIABILITY.

    Design: Corner/calculations/legal_counsel_cost_walks_first_party_then_third_party_liability
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
        covered_section_keys=[
            "FIRST_PARTY_RESPONSE",
            "BUSINESS_INTERRUPTION",
            "THIRD_PARTY_LIABILITY",
        ],
        initial_reserve_usd=1600000,
    )
    vendor = fixtures.create_vendor(
        api,
        F.panel_vendor_payload(
            vendor_name="Kestrel Legal",
            vendor_type="LEGAL_COUNSEL",
            pre_approved_hourly_rate_usd=800,
            per_record_notification_rate_usd=0,
            specialty_sectors=["HEALTHCARE"],
            tier=1,
            capacity_concurrent_engagements=2,
        ),
    )
    engagement = fixtures.authorize_engagement(
        api,
        claim["id"],
        vendor_type="LEGAL_COUNSEL",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-20T00:00:00Z",
        authorized_hours_cap=2000,
        panel_vendor_id=vendor["id"],
    )
    logged = fixtures.log_hours(api, engagement["id"], hours=2000)
    assert_money(logged["incurred_amount_usd"], 1600000.00, "incurred_amount_usd")

    completed = fixtures.complete_engagement(api, engagement["id"])

    assert completed["status"] == "COMPLETED", completed

    payments_response = api.list_claim_payments(
        ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
    )
    assert_total_count(payments_response, 2)
    payments = get_rows(payments_response)
    first_party = find_row(
        payments,
        coverage_section_id=chain["sections"]["FIRST_PARTY_RESPONSE"]["id"],
    )
    third_party = find_row(
        payments,
        coverage_section_id=chain["sections"]["THIRD_PARTY_LIABILITY"]["id"],
    )
    assert_money(first_party["gross_amount_usd"], 1000000.00, "gross_amount_usd")
    assert_money(first_party["retention_applied_usd"], 250000.00, "retention_applied_usd")
    assert_money(
        first_party["coinsurance_deduction_usd"], 0.00, "coinsurance_deduction_usd"
    )
    assert_money(first_party["net_paid_usd"], 1000000.00, "net_paid_usd")
    assert_money(third_party["gross_amount_usd"], 350000.00, "gross_amount_usd")
    assert_money(third_party["retention_applied_usd"], 0.00, "retention_applied_usd")
    assert_money(third_party["net_paid_usd"], 350000.00, "net_paid_usd")

    sections = {
        row["section_key"]: row
        for row in get_rows(
            api.list_policy_coverage_sections(policy["id"], UNDERWRITER_HEADERS)
        )
    }
    assert_money(
        sections["FIRST_PARTY_RESPONSE"]["sublimit_remaining_usd"],
        0.00,
        "sublimit_remaining_usd",
    )
    assert_money(
        sections["THIRD_PARTY_LIABILITY"]["sublimit_remaining_usd"],
        2650000.00,
        "sublimit_remaining_usd",
    )
    assert_money(
        sections["BUSINESS_INTERRUPTION"]["sublimit_remaining_usd"],
        2000000.00,
        "sublimit_remaining_usd",
    )

    policy = fixtures.read_policy(api, policy["id"])
    assert_money(
        policy["aggregate_limit_remaining_usd"],
        3650000.00,
        "aggregate_limit_remaining_usd",
    )
    assert policy["limit_status"] == "PARTIALLY_ERODED", policy

    claim = fixtures.read_claim(api, claim["id"])
    assert_money(claim["retention_absorbed_usd"], 250000.00, "retention_absorbed_usd")
    assert_money(claim["paid_total_usd"], 1350000.00, "paid_total_usd")
    assert_money(claim["unallocated_loss_usd"], 0.00, "unallocated_loss_usd")

    vendor = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert vendor["active_engagement_count"] == 0, vendor


def test_engagement_total_recomputed_from_cumulative_hours_and_records(api):
    """`incurred_amount_usd` is then the sum of two independently rounded terms: cumulative `incurred_hours` multiplied by `approved_rate_usd`, rounded half up to 2 decimal places; plus cumulative `records_notified` multiplied by `approved_per_record_rate_usd`, rounded half up to 2 decimal places.

    The money is recomputed from cumulative totals, never accumulated
    incrementally.

    After a second log of 5 hours and 7,345 records the engagement stands at 15
    hours and 12,345 records, so 15 * 200.00 = 3,000.00 plus 12,345 * 3.50 =
    43,207.50 gives 46,207.50, not the 26,707.50 that adding only the second
    increment would give.

    Design: Corner/calculations/engagement_total_recomputed_from_cumulative_hours_and_records
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
    vendor = fixtures.create_vendor(
        api,
        F.panel_vendor_payload(
            vendor_name="Postmark Notify",
            vendor_type="NOTIFICATION",
            pre_approved_hourly_rate_usd=200,
            per_record_notification_rate_usd=3.5,
            specialty_sectors=["HEALTHCARE", "TECHNOLOGY"],
            tier=1,
            capacity_concurrent_engagements=5,
        ),
    )
    engagement = fixtures.authorize_engagement(
        api,
        claim["id"],
        vendor_type="NOTIFICATION",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-20T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
    )
    first_log = fixtures.log_hours(api, engagement["id"], hours=10, records_notified=5000)
    assert_money(first_log["incurred_amount_usd"], 19500.00, "incurred_amount_usd")

    second_log = fixtures.log_hours(
        api, engagement["id"], hours=5, records_notified=7345
    )

    assert second_log["status"] == "ACTIVE", second_log
    assert float(second_log["incurred_hours"]) == 15.0, second_log
    assert second_log["records_notified"] == 12345, second_log
    assert_money(second_log["incurred_amount_usd"], 46207.50, "incurred_amount_usd")
    assert float(second_log["incurred_amount_usd"]) != 26707.50, second_log
    assert_money(second_log["approved_rate_usd"], 200.00, "approved_rate_usd")
    assert_money(
        second_log["approved_per_record_rate_usd"], 3.50, "approved_per_record_rate_usd"
    )


# ==========================================================================
# Panel selection
# ==========================================================================
def test_panel_selection_prefers_tier_one_over_a_cheaper_tier_two_firm(api):
    """Second, the surviving candidates are ranked by `tier` ascending, then by `pre_approved_hourly_rate_usd` ascending, then by `created_at` ascending, and the first is the winner; a firm's `id` never participates in the ordering.

    Two rates are pinned at that instant and never move again:
    `approved_rate_usd` from the chosen firm's `pre_approved_hourly_rate_usd`
    and `approved_per_record_rate_usd` from its
    `per_record_notification_rate_usd`.

    Tier is the first key, so the tier-1 firm at 500.00 an hour beats both
    tier-2 firms at 450.00 an hour.

    Design: Corner/calculations/panel_selection_prefers_tier_one_over_a_cheaper_tier_two_firm
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    ironclad, beacon, sable = _forensics_panel(api)

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

    engagement = fixtures.authorize_engagement(
        api,
        claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=40,
    )

    assert engagement["panel_vendor_id"] == ironclad["id"], engagement
    assert engagement["selection_mode"] == "PANEL_SELECTED", engagement
    assert_money(engagement["approved_rate_usd"], 500.00, "approved_rate_usd")
    assert_money(
        engagement["approved_per_record_rate_usd"],
        0.00,
        "approved_per_record_rate_usd",
    )

    assert (
        data_of(api.get_panel_vendor(ironclad["id"], PANEL_ADMIN_HEADERS))[
            "active_engagement_count"
        ]
        == 1
    )
    assert (
        data_of(api.get_panel_vendor(beacon["id"], PANEL_ADMIN_HEADERS))[
            "active_engagement_count"
        ]
        == 0
    )
    assert (
        data_of(api.get_panel_vendor(sable["id"], PANEL_ADMIN_HEADERS))[
            "active_engagement_count"
        ]
        == 0
    )

    claim = fixtures.read_claim(api, claim["id"])
    assert claim["status"] == "RESPONSE_ACTIVE", claim


def test_panel_selection_tie_broken_by_created_at_when_tier_and_rate_match(api):
    """First, the candidate pool is filtered to firms whose `vendor_type` equals the requested type, whose `status` is `ACTIVE`, whose `specialty_sectors` contains the `industry_code` of the insured behind the claim's policy, and whose colliding count at the requested window is strictly less than their `capacity_concurrent_engagements`.

    A buffered window runs from the engagement's `deployment_start_at` to its
    `deployment_end_at` extended by a changeover buffer of 24 hours, reflecting
    the day a firm needs to stand down one deployment before standing up the
    next. Both the buffered window and the requested window are treated as
    closed intervals, so windows that merely share an endpoint do collide.

    Second, the surviving candidates are ranked by `tier` ascending, then by
    `pre_approved_hourly_rate_usd` ascending, then by `created_at` ascending,
    and the first is the winner; a firm's `id` never participates in the
    ordering.

    The tier-1 firm's single capacity slot is taken by a deployment buffered
    through 2026-09-13T00:00:00Z, so the two tier-2 firms tie on tier and rate
    and the earlier-created row wins.

    Design: Corner/calculations/panel_selection_tie_broken_by_created_at_when_tier_and_rate_match
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    ironclad, beacon, sable = _forensics_panel(api)

    fixtures.set_clock(api, CLAIM_CLOCK)
    occupying_claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=100000,
    )
    fixtures.authorize_engagement(
        api,
        occupying_claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=ironclad["id"],
    )
    claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="SYSTEM_FAILURE",
        incident_discovered_at="2026-09-06T00:00:00Z",
        outage_start_at="2026-09-06T00:00:00Z",
        outage_end_at="2026-09-09T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=200000,
    )

    engagement = fixtures.authorize_engagement(
        api,
        claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-11T00:00:00Z",
        deployment_end_at="2026-09-13T00:00:00Z",
        authorized_hours_cap=40,
    )

    assert engagement["panel_vendor_id"] == beacon["id"], engagement
    assert engagement["panel_vendor_id"] != ironclad["id"], engagement
    assert engagement["panel_vendor_id"] != sable["id"], engagement
    assert_money(engagement["approved_rate_usd"], 450.00, "approved_rate_usd")
    assert engagement["selection_mode"] == "PANEL_SELECTED", engagement

    assert (
        data_of(api.get_panel_vendor(beacon["id"], PANEL_ADMIN_HEADERS))[
            "active_engagement_count"
        ]
        == 1
    )
    assert (
        data_of(api.get_panel_vendor(sable["id"], PANEL_ADMIN_HEADERS))[
            "active_engagement_count"
        ]
        == 0
    )
    assert (
        data_of(api.get_panel_vendor(ironclad["id"], PANEL_ADMIN_HEADERS))[
            "active_engagement_count"
        ]
        == 1
    )


def test_panel_selection_with_an_empty_candidate_pool_returns_422(api):
    """Third, if the candidate pool is empty, the authorisation fails with `ERR_NO_ELIGIBLE_PANEL_VENDOR` — the server never relaxes a filter to find a firm.

    `specialty_sectors` is a non-empty subset of the six industry codes the
    firm is empanelled for; an insured whose `industry_code` is absent from
    that list makes the firm ineligible for its claims.

    Neither forensics firm lists TECHNOLOGY and the one firm that does is a
    NOTIFICATION firm, so a TECHNOLOGY insured gets no cross-sector match.

    Design: Corner/calculations/panel_selection_with_an_empty_candidate_pool_returns_422
    """
    chain = _aurora_policy(
        api,
        account_spec=C.ACCOUNT_BITWISE,
        requested_aggregate_limit_usd=250000,
        requested_retention_usd=0,
        dependent_bi_definition="BROAD_SYSTEM_FAILURE",
        coverage_sections=list(C.SMALL_TOWER),
    )
    policy = chain["policy"]
    ironclad, beacon, _sable = _forensics_panel(api)
    fixtures.create_vendor(
        api,
        F.panel_vendor_payload(
            vendor_name="Postmark Notify",
            vendor_type="NOTIFICATION",
            pre_approved_hourly_rate_usd=200,
            per_record_notification_rate_usd=3.5,
            specialty_sectors=["HEALTHCARE", "TECHNOLOGY"],
            tier=1,
            capacity_concurrent_engagements=5,
        ),
    )

    fixtures.set_clock(api, CLAIM_CLOCK)
    claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=100000,
    )

    response = api.create_vendor_engagement(
        claim["id"],
        F.vendor_engagement_payload(
            vendor_type="FORENSICS",
            deployment_start_at="2026-09-10T00:00:00Z",
            deployment_end_at="2026-09-12T00:00:00Z",
            authorized_hours_cap=40,
        ),
        ADJUSTER_HEADERS,
    )

    validate_error(response, ErrorId.NO_ELIGIBLE_PANEL_VENDOR)

    assert_total_count(
        api.list_vendor_engagements(
            ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
        ),
        0,
    )
    claim = fixtures.read_claim(api, claim["id"])
    assert claim["status"] == "COVERAGE_CONFIRMED", claim
    assert (
        data_of(api.get_panel_vendor(ironclad["id"], PANEL_ADMIN_HEADERS))[
            "active_engagement_count"
        ]
        == 0
    )
    assert (
        data_of(api.get_panel_vendor(beacon["id"], PANEL_ADMIN_HEADERS))[
            "active_engagement_count"
        ]
        == 0
    )


# ==========================================================================
# Renewal pricing and portfolio aggregation
# ==========================================================================
def test_renewal_control_credit_binds_at_twelve_percent_of_the_pre_credit_premium(api):
    """The raw control credit is the number of entries in the assessment's `verified_control_keys` multiplied by 750. The credit actually granted is the lesser of that raw figure and 12 percent of the rounded pre-credit premium, rounded half up to 2 decimal places.

    A loss-ratio tier adjustment is selected: negative 0.05 when the loss ratio
    is at most 0.30; positive 0.05 when it is above 0.30 and at most 0.60;
    positive 0.20 when it is above 0.60 and at most 1.00; and positive 0.45
    when it is above 1.00.

    `premium_adjustment_pct` is `renewal_premium_usd` less the earned premium,
    divided by the earned premium, rounded half up to 4 decimal places.

    With no claims the loss ratio is 0.0000, so the pre-credit premium is
    28,458.00 * 0.95 = 27,035.10; five verified controls earn a raw 3,750.00
    but the cap of 12 percent holds the credit to 3,244.21, leaving 23,790.89
    and an adjustment of -0.1640.

    Design: Corner/calculations/renewal_control_credit_binds_at_twelve_percent_of_the_pre_credit_premium
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    assert_money(policy["premium_usd"], 28458.00, "premium_usd")
    assert policy["aggregation_flagged"] is False, policy

    fixtures.set_clock(api, "2027-05-05T00:00:00Z")
    assessment = fixtures.open_renewal_assessment(
        api,
        policy["id"],
        required_control_keys=list(C.ALL_CONTROL_KEYS),
        remediation_due_at="2027-06-15T00:00:00Z",
    )
    fixtures.submit_remediation(api, assessment["id"], list(C.ALL_CONTROL_KEYS))
    verified = fixtures.verify_remediation(
        api, assessment["id"], list(C.ALL_CONTROL_KEYS)
    )
    assert verified["status"] == "CONDITIONS_MET", verified
    assert len(verified["verified_control_keys"]) == 5, verified

    quoted = fixtures.issue_renewal_quote(api, assessment["id"], policy["id"])

    assert quoted["status"] == "RENEWAL_QUOTED", quoted
    assert_ratio_4dp(quoted["loss_ratio"], 0.0000, "loss_ratio")
    assert_money(quoted["renewal_premium_usd"], 23790.89, "renewal_premium_usd")
    assert float(quoted["renewal_premium_usd"]) != 23285.10, quoted
    assert_ratio_4dp(
        quoted["premium_adjustment_pct"], -0.1640, "premium_adjustment_pct"
    )
    assert quoted["verification_round"] == 1, quoted


def test_systemic_model_excludes_policies_outside_the_qualifying_definitions(api):
    """The population is assembled at the current logical clock instant: a policy is included when its `lifecycle_status` is `INFORCE`, when its `period_start` is at or before the current instant and its `period_end` strictly after it, when the insured account behind it has a `primary_dependency_key` equal to the scenario's `dependency_key`, when the policy's `dependent_bi_definition` is among the scenario's `qualifying_definitions`, and when the policy's tower actually contains a `DEPENDENT_BI` section.

    `capacity_breached` is true when `modeled_gross_exposure_usd` is strictly
    greater than `portfolio_capacity_usd`, and equality is not a breach.

    The only in-force policy on CSP_ALPHA is written NAMED_PLUS_SUPPLY_CHAIN,
    which is not among a NAMED_ONLY scenario's qualifying definitions, so no
    policy is included and the modelled exposure is 0.00.

    Design: Corner/calculations/systemic_model_excludes_policies_outside_the_qualifying_definitions
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    assert policy["dependent_bi_definition"] == "NAMED_PLUS_SUPPLY_CHAIN", policy
    assert "DEPENDENT_BI" in chain["sections"], chain["sections"]

    fixtures.set_clock(api, CLAIM_CLOCK)
    scenario = fixtures.draft_scenario(
        api,
        dependency_key="CSP_ALPHA",
        assumed_outage_hours=240,
        footprint_pct=0.5,
        portfolio_capacity_usd=100000,
        qualifying_definitions=["NAMED_ONLY"],
    )

    modeled = fixtures.run_model(api, scenario["id"])

    assert modeled["status"] == "MODELED", modeled
    assert modeled["modeled_policy_count"] == 0, modeled
    assert_money(
        modeled["modeled_gross_exposure_usd"], 0.00, "modeled_gross_exposure_usd"
    )
    assert modeled["capacity_breached"] is False, modeled
    assert_instant(modeled["modeled_at"], CLAIM_CLOCK, "modeled_at")

    policy = fixtures.read_policy(api, policy["id"])
    assert policy["aggregation_flagged"] is False, policy
