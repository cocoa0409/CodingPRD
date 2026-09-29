"""Compensating actions that put back exactly what they consumed.

Money and capacity are conserved in this system, so a payment reversal restores
capacity and the claim ledger (PRD §3.8), and a claim denial gives back the
panel slots the response consumed (PRD §3.6, §3.7).
"""
from test_helpers import (
    ADJUSTER_2_HEADERS,
    ADJUSTER_HEADERS,
    PANEL_ADMIN_HEADERS,
    UNDERWRITER_HEADERS,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_money, data_of, find_row, get_rows


# ==========================================================================
# Payment reversal
# ==========================================================================
def _exhausted_policy_with_one_posted_payment(api):
    """A 250,000 aggregate wholly consumed by a single posted BUSINESS_INTERRUPTION row."""
    chain = X.bound_policy(
        api,
        account_spec=C.ACCOUNT_BITWISE,
        attestations=C.ATTEST_95,
        requested_aggregate_limit_usd=250000,
        requested_retention_usd=0,
        dependent_bi_definition="BROAD_SYSTEM_FAILURE",
        coverage_sections=list(C.SMALL_TOWER),
        findings=[],
    )
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-01T00:00:00Z",
        outage_start_at="2026-09-01T00:00:00Z",
        outage_end_at="2026-09-05T16:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=250000,
    )
    proof = X.file_proof(
        api,
        claim["id"],
        claimed_bi_loss_usd=400000,
        trailing_12m_revenue_usd=43800000,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=0.8,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    data_of(api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS))

    payments = X.list_payments_for_claim(api, claim["id"])
    assert len(payments) == 1, payments
    payment = payments[0]
    assert_money(payment["net_paid_usd"], 250000.00, "net_paid_usd")
    return chain, claim, payment


def test_reversal_restores_the_sublimit_and_carries_the_policy_back_to_intact(api):
    """The section gets back its gross and the aggregate its net, returning the policy to INTACT.

    PRD §3.8: "Reversal is a precise compensating action: the section's
    `sublimit_remaining_usd` is increased by the row's `gross_amount_usd`, the
    policy's `aggregate_limit_remaining_usd` is increased by its `net_paid_usd`, and
    `limit_status` is recomputed — which can carry the policy from `EXHAUSTED` back to
    `PARTIALLY_ERODED` when remaining capacity ends up strictly above zero and
    strictly below the full aggregate, or from `PARTIALLY_ERODED` back to `INTACT`
    when it ends up equal to the full aggregate."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_aggregate_sublimit_and_claim_ledger
    """
    chain, _claim, payment = _exhausted_policy_with_one_posted_payment(api)
    policy_id = chain["policy"]["id"]
    assert X.read_policy(api, policy_id)["limit_status"] == "EXHAUSTED"

    reversed_row = data_of(
        api.reverse_claim_payment(
            payment["id"], F.reverse_payment_payload("ADJUSTER_ERROR"), ADJUSTER_HEADERS
        )
    )

    assert reversed_row["payment_status"] == "REVERSED", reversed_row["payment_status"]
    assert reversed_row["reversal_reason"] == "ADJUSTER_ERROR", reversed_row["reversal_reason"]
    assert_money(reversed_row["gross_amount_usd"], 250000.00, "gross_amount_usd")

    policy = X.read_policy(api, policy_id)
    assert_money(policy["aggregate_limit_remaining_usd"], 250000.00, "aggregate_limit_remaining_usd")
    assert policy["limit_status"] == "INTACT", policy["limit_status"]

    sections = get_rows(api.list_policy_coverage_sections(policy_id, UNDERWRITER_HEADERS))
    section = find_row(sections, section_key="BUSINESS_INTERRUPTION")
    assert_money(section["sublimit_remaining_usd"], 250000.00, "sublimit_remaining_usd")


def test_reversal_rewinds_the_claim_ledger_and_reopens_the_settled_file(api):
    """The claim's paid, retained and unallocated figures return to 0.00 and it leaves SETTLED.

    PRD §3.8: "On the claim, `paid_total_usd` is decreased by `net_paid_usd`,
    `retention_absorbed_usd` is decreased by `retention_applied_usd`, and
    `unallocated_loss_usd` is reset to 0.00; a claim that had reached `SETTLED`
    returns to `APPROVED_FOR_PAYMENT`." The 150000.00 the aggregate could not place
    is therefore discarded rather than carried forward.

    Design: Difficulty/compensating_invariant/payment_reversal_restores_aggregate_sublimit_and_claim_ledger
    """
    chain, claim, payment = _exhausted_policy_with_one_posted_payment(api)
    before = X.read_claim(api, claim["id"])
    assert before["status"] == "SETTLED", before["status"]
    assert_money(before["unallocated_loss_usd"], 150000.00, "unallocated_loss_usd")

    data_of(
        api.reverse_claim_payment(
            payment["id"], F.reverse_payment_payload("ADJUSTER_ERROR"), ADJUSTER_HEADERS
        )
    )

    after = X.read_claim(api, claim["id"])
    assert after["status"] == "APPROVED_FOR_PAYMENT", after["status"]
    assert_money(after["paid_total_usd"], 0.00, "paid_total_usd")
    assert_money(after["retention_absorbed_usd"], 0.00, "retention_absorbed_usd")
    assert_money(after["unallocated_loss_usd"], 0.00, "unallocated_loss_usd")

    summary = data_of(api.get_policy_loss_summary(chain["policy"]["id"], UNDERWRITER_HEADERS))
    assert_money(summary["paid_total_usd"], 0.00, "paid_total_usd")
    assert_money(
        summary["aggregate_limit_remaining_usd"], 250000.00, "aggregate_limit_remaining_usd"
    )


# ==========================================================================
# Claim denial
# ==========================================================================
def _claim_with_two_engagements_and_logged_work(api):
    """One firm holding two engagements on the same claim, 45207.50 incurred on the first."""
    chain = X.bound_policy(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
        coverage_sections=list(C.STANDARD_TOWER),
        findings=[],
    )
    vendor = X.create_vendor(api, C.VENDOR_POSTMARK_NOTIFY)
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=250000,
        affected_record_count=12345,
    )
    first = X.authorize_engagement(
        api,
        claim["id"],
        vendor_type="NOTIFICATION",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-20T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
    )
    second = X.authorize_engagement(
        api,
        claim["id"],
        vendor_type="NOTIFICATION",
        deployment_start_at="2026-09-21T00:00:00Z",
        deployment_end_at="2026-09-30T00:00:00Z",
        authorized_hours_cap=20,
        panel_vendor_id=vendor["id"],
    )
    logged = X.log_hours(api, first["id"], hours=10, records_notified=12345)
    assert_money(logged["incurred_amount_usd"], 45207.50, "incurred_amount_usd")
    return chain, vendor, claim, first, second


def test_denial_terminates_both_engagements_and_gives_back_every_slot(api):
    """Denying the claim terminates the ACTIVE and the AUTHORIZED engagement alike.

    PRD §3.6: "The `denial_reason` is stored, `reserved_amount_usd` is zeroed to 0.00,
    and every vendor engagement of that claim whose `status` is `AUTHORIZED` or
    `ACTIVE` moves to `TERMINATED`, with the corresponding panel firm's
    `active_engagement_count` decremented once per terminated engagement and that
    firm's `version` incremented."

    Design: Difficulty/compensating_invariant/claim_denial_restores_panel_vendor_capacity_slots
    """
    _chain, vendor, claim, first, second = _claim_with_two_engagements_and_logged_work(api)
    before = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert before["active_engagement_count"] == 2, before["active_engagement_count"]

    denied = data_of(
        api.deny_incident_claim(
            claim["id"], F.deny_claim_payload("EXCLUDED_CAUSE"), ADJUSTER_HEADERS
        )
    )

    assert denied["status"] == "DENIED", denied["status"]
    assert denied["denial_reason"] == "EXCLUDED_CAUSE", denied["denial_reason"]
    assert_money(denied["reserved_amount_usd"], 0.00, "reserved_amount_usd")

    assert data_of(api.get_vendor_engagement(first["id"], ADJUSTER_HEADERS))["status"] == "TERMINATED"
    assert data_of(api.get_vendor_engagement(second["id"], ADJUSTER_HEADERS))["status"] == "TERMINATED"

    after = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert after["active_engagement_count"] == 0, after["active_engagement_count"]


def test_termination_retains_the_incurred_cost_without_paying_or_eroding_anything(api):
    """The 45207.50 already worked stays on the record but nothing is allocated for it.

    PRD §3.7: "Termination runs no allocation at all — the engagement's
    `incurred_amount_usd` is retained on the record as an unpaid figure, which is the
    carrier's audit trail of work done but not indemnified."

    Design: Difficulty/compensating_invariant/claim_denial_restores_panel_vendor_capacity_slots
    """
    chain, _vendor, claim, first, second = _claim_with_two_engagements_and_logged_work(api)

    data_of(
        api.deny_incident_claim(
            claim["id"], F.deny_claim_payload("EXCLUDED_CAUSE"), ADJUSTER_HEADERS
        )
    )

    worked = data_of(api.get_vendor_engagement(first["id"], ADJUSTER_HEADERS))
    assert_money(worked["incurred_amount_usd"], 45207.50, "incurred_amount_usd")
    assert_money(worked["incurred_hours"], 10.00, "incurred_hours")

    idle = data_of(api.get_vendor_engagement(second["id"], ADJUSTER_HEADERS))
    assert_money(idle["incurred_amount_usd"], 0.00, "incurred_amount_usd")

    assert X.list_payments_for_claim(api, claim["id"]) == []

    policy = X.read_policy(api, chain["policy"]["id"])
    assert_money(policy["aggregate_limit_remaining_usd"], 5000000.00, "aggregate_limit_remaining_usd")
    assert policy["limit_status"] == "INTACT", policy["limit_status"]
