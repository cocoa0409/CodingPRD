"""Multi-hop cascades: scan completion and proof acceptance.

Scan completion drives the four hops of PRD §3.3 out to the owning account's
counter; proof acceptance drives the six hops of PRD §3.8 out to a panel
firm's capacity slot.
"""
from test_helpers import ADJUSTER_2_HEADERS, ADJUSTER_HEADERS, PANEL_ADMIN_HEADERS, UNDERWRITER_HEADERS
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_instant,
    assert_money,
    assert_score_2dp,
    data_of,
    find_row,
    get_rows,
)


# ==========================================================================
# Scan completion: four hops to the account counter
# ==========================================================================
def _aurora_submitted_with_pending_scan(api):
    X.seed_catalog(api)
    account = X.create_account(api, C.ACCOUNT_AURORA)
    application = X.create_application(
        api,
        account["id"],
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
    )
    X.attest_controls(api, application["id"], C.ATTEST_95)
    X.submit_application(api, application["id"])
    scan = X.order_scan(api, application["id"], scan_score=41)
    return account, application, scan


def test_critical_finding_rewrites_verified_levels_and_reopens_the_gap(api):
    """A CRITICAL finding on a mandatory control drops its verified level and the score to 82.50.

    PRD §3.3: "Because the scan completed, every control attestation on that
    application has its `verified_level` rewritten to the lower of its
    `attested_level` and the level the scan observed for that control, comparing on
    the ordering where `NONE` is lowest, `PARTIAL` is next, and `FULL` is highest."
    A control the scanner did not mention keeps `FULL`, and the attested basis is
    untouched.

    Design: Difficulty/transitive_cascade/scan_completion_four_hop_cascade_reaches_account_counter
    """
    _account, application, scan = _aurora_submitted_with_pending_scan(api)

    completed = X.complete_scan(
        api,
        scan["id"],
        findings=[F.scan_finding("OFFLINE_BACKUPS", "CRITICAL", "PARTIAL")],
    )

    assert completed["status"] == "COMPLETED", completed["status"]
    assert completed["critical_finding_count"] == 1, completed["critical_finding_count"]
    assert_instant(completed["completed_at"], C.DEFAULT_CLOCK, "completed_at")

    attestations = get_rows(
        api.list_application_control_attestations(application["id"], UNDERWRITER_HEADERS)
    )
    assert find_row(attestations, control_key="OFFLINE_BACKUPS")["verified_level"] == "PARTIAL"
    assert find_row(attestations, control_key="EMAIL_FILTERING")["verified_level"] == "FULL"

    after = X.read_application(api, application["id"])
    assert_score_2dp(after["verified_control_score"], 82.50, "verified_control_score")
    assert_score_2dp(after["attested_control_score"], 95.00, "attested_control_score")
    assert after["mandatory_gap_count"] == 1, after["mandatory_gap_count"]
    assert after["mandatory_gap_control_keys"] == ["OFFLINE_BACKUPS"], after


def test_mandatory_gap_carries_the_application_to_remediation_and_bumps_the_account(api):
    """Hop 4 increments the owning account's open_remediation_count to 1.

    PRD §3.3: "Because the application entered `REMEDIATION_REQUIRED`, the owning
    insured account's `open_remediation_count` is incremented by 1 and that
    account's `version` is incremented by 1." The application does not rest in
    `UNDERWRITING` and its `premium_usd` is cleared to null.

    Design: Difficulty/transitive_cascade/scan_completion_four_hop_cascade_reaches_account_counter
    """
    account, application, scan = _aurora_submitted_with_pending_scan(api)
    before = data_of(api.get_insured_account(account["id"], UNDERWRITER_HEADERS))
    assert before["open_remediation_count"] == 0, before["open_remediation_count"]

    X.complete_scan(
        api,
        scan["id"],
        findings=[F.scan_finding("OFFLINE_BACKUPS", "CRITICAL", "PARTIAL")],
    )

    after = X.read_application(api, application["id"])
    assert after["status"] == "REMEDIATION_REQUIRED", after["status"]
    assert after["premium_usd"] is None, after["premium_usd"]

    reread = data_of(api.get_insured_account(account["id"], UNDERWRITER_HEADERS))
    assert reread["open_remediation_count"] == 1, reread["open_remediation_count"]


# ==========================================================================
# Proof acceptance: six hops to a panel firm's slot
# ==========================================================================
def _bitwise_claim_with_live_engagement_and_proof(api):
    """A 250,000 aggregate policy, one AUTHORIZED notification engagement, one proof under review."""
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
    vendor = X.create_vendor(api, C.VENDOR_POSTMARK_NOTIFY)
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
    engagement = X.authorize_engagement(
        api,
        claim["id"],
        vendor_type="NOTIFICATION",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-20T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
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
    return chain, vendor, claim, engagement, proof


def test_acceptance_posts_one_payment_row_and_settles_the_claim(api):
    """Hops 1 to 4: the waterfall writes a single BUSINESS_INTERRUPTION row for 250000.00.

    PRD §3.8: "A payment row is written for each section actually eroded, recording
    its `incident_claim_id`, the `coverage_section_id` of the section it eroded, the
    `loss_source` that produced it — `PROOF_OF_LOSS` or `VENDOR_ENGAGEMENT` — a
    `gross_amount_usd` equal to the allocated loss, the `coinsurance_deduction_usd`,
    the `net_paid_usd`, and a `payment_status` of `POSTED`." The 150000.00 the
    aggregate could not place lands on `unallocated_loss_usd`.

    Design: Difficulty/transitive_cascade/proof_acceptance_six_hop_cascade_terminates_engagement_and_releases_slot
    """
    chain, _vendor, claim, _engagement, proof = _bitwise_claim_with_live_engagement_and_proof(api)

    accepted = data_of(api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS))

    assert accepted["status"] == "ACCEPTED", accepted["status"]
    assert_money(accepted["assessed_indemnity_usd"], 400000.00, "assessed_indemnity_usd")

    settled = X.read_claim(api, claim["id"])
    assert settled["status"] == "SETTLED", settled["status"]
    assert_money(settled["paid_total_usd"], 250000.00, "paid_total_usd")
    assert_money(settled["unallocated_loss_usd"], 150000.00, "unallocated_loss_usd")
    assert_money(settled["reserved_amount_usd"], 0.00, "reserved_amount_usd")

    payments = X.list_payments_for_claim(api, claim["id"])
    assert len(payments) == 1, payments
    row = payments[0]
    assert row["payment_status"] == "POSTED", row["payment_status"]
    assert row["loss_source"] == "PROOF_OF_LOSS", row["loss_source"]
    assert_money(row["gross_amount_usd"], 250000.00, "gross_amount_usd")
    assert_money(row["coinsurance_deduction_usd"], 0.00, "coinsurance_deduction_usd")
    assert_money(row["retention_applied_usd"], 0.00, "retention_applied_usd")
    assert_money(row["net_paid_usd"], 250000.00, "net_paid_usd")

    policy = X.read_policy(api, chain["policy"]["id"])
    assert_money(policy["aggregate_limit_remaining_usd"], 0.00, "aggregate_limit_remaining_usd")
    assert policy["limit_status"] == "EXHAUSTED", policy["limit_status"]


def test_exhaustion_terminates_the_live_engagement_and_releases_the_firm_slot(api):
    """Hops 5 and 6: the AUTHORIZED engagement is terminated and the firm's count returns to 0.

    PRD §3.8: "If `limit_status` became `EXHAUSTED`, every vendor engagement in
    `AUTHORIZED` or `ACTIVE` on **any** claim of that policy — not merely this claim
    — moves to `TERMINATED`." Termination runs no allocation, so the engagement's
    incurred figure is retained as an unpaid one.

    Design: Difficulty/transitive_cascade/proof_acceptance_six_hop_cascade_terminates_engagement_and_releases_slot
    """
    _chain, vendor, _claim, engagement, proof = _bitwise_claim_with_live_engagement_and_proof(api)
    before = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert before["active_engagement_count"] == 1, before["active_engagement_count"]

    data_of(api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS))

    terminated = data_of(api.get_vendor_engagement(engagement["id"], ADJUSTER_HEADERS))
    assert terminated["status"] == "TERMINATED", terminated["status"]
    assert_money(terminated["incurred_amount_usd"], 0.00, "incurred_amount_usd")

    after = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert after["active_engagement_count"] == 0, after["active_engagement_count"]
