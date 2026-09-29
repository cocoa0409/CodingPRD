"""Endpoint-surface coverage: computed reads, epoch sweeps, panel amendment,
pinned rates and the filtered/paginated discovery channels.

Every test builds its own world through the public API; the harness restarts
the server with an empty database before each test.
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ACTUARY_HEADERS,
    ADJUSTER_HEADERS,
    PANEL_ADMIN_HEADERS,
    UNDERWRITER_HEADERS,
    constants as C,
    factories as F,
    fixtures as X,
)
from test_helpers.assertions import assert_money, assert_ratio_4dp, assert_score_2dp


# --------------------------------------------------------------------------
# Local helpers
# --------------------------------------------------------------------------
def _instant(value):
    """Parse an ISO 8601 UTC timestamp so two spellings of one instant compare
    equal regardless of fractional-digit formatting."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _email_filtering_partial():
    """A single scan finding that observes EMAIL_FILTERING at PARTIAL."""
    return [F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")]


def _bound_aurora_policy(api):
    """Aurora Health taken from the empty database to an INFORCE policy.

    Catalog -> account -> application -> five attestations -> submit -> scan
    ordered and completed -> quote -> bind, leaving a five-section tower on a
    5,000,000 aggregate with a 250,000 retention. The completed scan observes
    EMAIL_FILTERING at PARTIAL, so the verified score is 87.50 and the bindable
    premium is 28,458.00.
    """
    return X.bound_policy(api, findings=_email_filtering_partial())


def _settled_ransomware_claim(api):
    """The bound Aurora policy plus a RANSOMWARE claim settled by an accepted
    proof of loss: a 72-hour outage on a 12-hour waiting period at a 1.00
    margin, so the assessed indemnity is 300,000.00, the 250,000.00 retention
    absorbs the top and one payment row of 45,000.00 net posts."""
    chain = _bound_aurora_policy(api)
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
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
    chain["claim"] = claim
    chain["proof"] = X.accept_proof(api, proof["id"])
    return chain


# --------------------------------------------------------------------------
# Computed reads
# --------------------------------------------------------------------------
def test_loss_summary_reports_the_settled_figures_without_mutating_anything(api):
    """PRD §3.9: "The paid figure is the sum of `net_paid_usd` over every payment row whose `payment_status` is `POSTED` and whose claim belongs to this policy; reversed rows are excluded."
    PRD §3.9: "The outstanding reserve is the sum of `reserved_amount_usd` over every claim of the policy whose `status` is not one of `SETTLED`, `DENIED`, or `CLOSED_NO_COVERAGE` — closed files hold no reserve."
    PRD §3.9: "The incurred figure is the paid figure plus the outstanding reserve, rounded half up to 2 decimal places, and the loss ratio is the incurred figure divided by the policy's `premium_usd`, rounded half up to 4 decimal places."
    PRD §3.9: "A computed read exposes these figures directly as `paid_total_usd`, `outstanding_reserve_usd`, `incurred_usd`, and `loss_ratio`, alongside `aggregate_limit_remaining_usd` and `limit_status`."
    PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp refreshed on every change to the row, and `version` is an integer that starts at 1 and increments by exactly 1 on every mutation."

    Design: Corner/endpoints/loss_summary_read_is_pure_and_advances_no_version
    """
    chain = _settled_ransomware_claim(api)
    policy_id = chain["policy"]["id"]
    claim_id = chain["claim"]["id"]

    policy_before = X.read_policy(api, policy_id)
    claim_before = X.read_claim(api, claim_id)

    resp = api.get_policy_loss_summary(policy_id, ACTUARY_HEADERS)
    summary = validate_success(resp, expected_status=200)

    assert_money(summary["paid_total_usd"], 45000.00, "paid_total_usd")
    assert_money(summary["outstanding_reserve_usd"], 0.00, "outstanding_reserve_usd")
    assert_money(summary["incurred_usd"], 45000.00, "incurred_usd")
    assert_ratio_4dp(summary["loss_ratio"], 1.5813, "loss_ratio")
    assert_money(
        summary["aggregate_limit_remaining_usd"], 4955000.00, "aggregate_limit_remaining_usd"
    )
    assert summary["limit_status"] == "PARTIALLY_ERODED", (
        f"limit_status: expected PARTIALLY_ERODED, got {summary['limit_status']}"
    )

    policy_after = X.read_policy(api, policy_id)
    claim_after = X.read_claim(api, claim_id)
    assert policy_after["version"] == policy_before["version"], (
        "reading the loss summary mutated the policy: version moved from "
        f"{policy_before['version']} to {policy_after['version']}"
    )
    assert claim_after["version"] == claim_before["version"], (
        "reading the loss summary mutated the claim: version moved from "
        f"{claim_before['version']} to {claim_after['version']}"
    )


def test_control_posture_read_is_not_quotable_while_a_mandatory_gap_stands(api):
    """PRD §3.4: "The level used for scoring is then the lower of the `attested_level` and that observed level on the same ordering."
    PRD §3.4: "`mandatory_gap_control_keys` lists the `control_key` of every catalog row whose `is_mandatory` is true and whose established level factor is strictly below the factor of its own `min_level_required`, ordered by `weight` descending and then `control_key` ascending."
    PRD §3.4: "A dedicated computed read returns both variants side by side as `attested_score` and `verified_score`, together with `mandatory_gap_count`, `mandatory_gap_control_keys`, the `min_score_for_coverage` threshold of 70, and a boolean `quotable`."
    PRD §3.5: "The verified-basis mandatory gap is **recomputed at quote time** against the control catalog exactly as it stands in that request, and the recomputed count must be zero."

    Design: Corner/endpoints/control_posture_read_marks_a_mandatory_gap_as_not_quotable
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    X.seed_catalog(api)
    account = X.create_account(api)
    application = X.create_application(api, account["id"])
    X.attest_controls(api, application["id"], C.ATTEST_95)
    X.submit_application(api, application["id"])
    scan = X.order_scan(api, application["id"])
    X.complete_scan(
        api, scan["id"], findings=[F.scan_finding("OFFLINE_BACKUPS", "CRITICAL", "PARTIAL")]
    )

    resp = api.get_control_posture(application["id"], UNDERWRITER_HEADERS)
    posture = validate_success(resp, expected_status=200)

    assert_score_2dp(posture["attested_score"], 95.00, "attested_score")
    assert_score_2dp(posture["verified_score"], 82.50, "verified_score")
    assert posture["mandatory_gap_count"] == 1, (
        f"mandatory_gap_count: expected 1, got {posture['mandatory_gap_count']}"
    )
    assert posture["mandatory_gap_control_keys"] == ["OFFLINE_BACKUPS"], (
        "mandatory_gap_control_keys: expected ['OFFLINE_BACKUPS'], got "
        f"{posture['mandatory_gap_control_keys']}"
    )
    assert float(posture["min_score_for_coverage"]) == 70.0, (
        f"min_score_for_coverage: expected 70, got {posture['min_score_for_coverage']}"
    )
    assert posture["quotable"] is False, (
        "quotable must be false while a mandatory control gap stands, even though "
        f"the verified score {posture['verified_score']} is above 70"
    )

    reread = X.read_application(api, application["id"])
    assert reread["status"] == "REMEDIATION_REQUIRED", (
        f"application status: expected REMEDIATION_REQUIRED, got {reread['status']}"
    )


# --------------------------------------------------------------------------
# Renewal remediation submission
# --------------------------------------------------------------------------
def test_submit_remediation_stores_only_the_submitted_subset(api):
    """PRD §3.9: "The `Insured`, or an `Underwriter` acting for it, submits evidence by supplying `submitted_control_keys`, which moves the assessment from `CONDITIONS_ISSUED` to `REMEDIATION_SUBMITTED`."
    PRD §3.9: "The submitted set is stored and the assessment's `version` is incremented by 1."
    PRD §3.9: "Either way `verification_round` starts at 0."

    Design: Corner/endpoints/submit_remediation_records_only_the_submitted_control_keys
    """
    chain = _bound_aurora_policy(api)
    X.set_clock(api, "2027-05-05T00:00:00Z")
    assessment = X.open_renewal_assessment(
        api,
        chain["policy"]["id"],
        required_control_keys=["EMAIL_FILTERING", "INCIDENT_RESPONSE_PLAN"],
        remediation_due_at="2027-06-01T00:00:00Z",
    )
    assert assessment["status"] == "CONDITIONS_ISSUED", (
        f"assessment opened in {assessment['status']}, expected CONDITIONS_ISSUED"
    )
    verified_before = assessment["verified_control_keys"]
    policy_before = X.read_policy(api, chain["policy"]["id"])

    resp = api.submit_remediation(
        assessment["id"], {"submitted_control_keys": ["EMAIL_FILTERING"]}, UNDERWRITER_HEADERS
    )
    submitted = validate_success(resp, expected_status=200)

    assert submitted["status"] == "REMEDIATION_SUBMITTED", (
        f"status: expected REMEDIATION_SUBMITTED, got {submitted['status']}"
    )
    assert submitted["submitted_control_keys"] == ["EMAIL_FILTERING"], (
        "submitted_control_keys must be stored verbatim, got "
        f"{submitted['submitted_control_keys']}"
    )
    assert submitted["required_control_keys"] == [
        "EMAIL_FILTERING",
        "INCIDENT_RESPONSE_PLAN",
    ], f"required_control_keys changed to {submitted['required_control_keys']}"
    assert submitted["verified_control_keys"] == verified_before, (
        "a partial submission must not touch verified_control_keys: "
        f"{verified_before} became {submitted['verified_control_keys']}"
    )
    assert submitted["verification_round"] == 0, (
        f"verification_round: expected 0, got {submitted['verification_round']}"
    )
    assert submitted["version"] == 2, (
        f"assessment version: expected 2 after one submission, got {submitted['version']}"
    )

    policy_after = X.read_policy(api, chain["policy"]["id"])
    assert policy_after["version"] == policy_before["version"], (
        "submitting remediation evidence must not mutate the policy: version moved from "
        f"{policy_before['version']} to {policy_after['version']}"
    )


# --------------------------------------------------------------------------
# The epoch sweep
# --------------------------------------------------------------------------
def test_run_epoch_expires_a_stale_quote_and_a_matured_policy_together(api):
    """PRD §2.5: "A companion administrative capability advances the system epoch at whatever instant the clock currently holds and performs three sweeps in one request: quoted applications whose quote has expired, in-force policies whose period has matured, and renewal assessments whose remediation deadline has passed."
    PRD §2.5: "Its response reports `expired_application_count`, `expired_policy_count`, `non_renewed_assessment_count`, and `run_at`."
    PRD §3.5: "A quote left unbound does not linger indefinitely: when the epoch sweep runs at or after `quote_expires_at`, a `QUOTED` application moves to `EXPIRED` with `premium_usd` cleared to null and its `version` incremented by 1."
    PRD §3.5: "An in-force policy matures when the epoch sweep runs at or after `period_end`, at which point `lifecycle_status` becomes `EXPIRED` and the policy's `version` is incremented by 1."

    Design: Corner/endpoints/run_epoch_sweeps_a_stale_quote_and_a_matured_policy_in_one_call
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    bound = _bound_aurora_policy(api)
    # A second applicant is quoted at the same instant and left unbound, so its
    # quote expires 30 days later while the first application rests in BOUND.
    quoted = X.quoted_application(
        api,
        account_spec=C.ACCOUNT_CORDIAL,
        findings=_email_filtering_partial(),
        seed=False,
    )
    assert quoted["application"]["status"] == "QUOTED", (
        f"second application should be QUOTED, got {quoted['application']['status']}"
    )

    X.set_clock(api, "2027-08-01T00:00:00Z")
    resp = api.run_epoch(UNDERWRITER_HEADERS)
    report = validate_success(resp, expected_status=200)

    assert report["expired_application_count"] == 1, (
        f"expired_application_count: expected 1, got {report['expired_application_count']}"
    )
    assert report["expired_policy_count"] == 1, (
        f"expired_policy_count: expected 1, got {report['expired_policy_count']}"
    )
    assert report["non_renewed_assessment_count"] == 0, (
        "non_renewed_assessment_count: expected 0, got "
        f"{report['non_renewed_assessment_count']}"
    )
    assert _instant(report["run_at"]) == _instant("2027-08-01T00:00:00Z"), (
        f"run_at: expected the current clock instant, got {report['run_at']}"
    )

    swept_application = X.read_application(api, quoted["application"]["id"])
    assert swept_application["status"] == "EXPIRED", (
        f"stale quote should be EXPIRED, got {swept_application['status']}"
    )
    assert swept_application.get("premium_usd") is None, (
        f"premium_usd should be cleared on expiry, got {swept_application.get('premium_usd')}"
    )

    matured_policy = X.read_policy(api, bound["policy"]["id"])
    assert matured_policy["lifecycle_status"] == "EXPIRED", (
        f"matured policy lifecycle_status: expected EXPIRED, got {matured_policy['lifecycle_status']}"
    )

    bound_application = X.read_application(api, bound["application"]["id"])
    assert bound_application["status"] == "BOUND", (
        f"the bound application must be untouched by the sweep, got {bound_application['status']}"
    )


def test_run_epoch_with_nothing_due_changes_no_row(api):
    """PRD §2.5: "A companion administrative capability advances the system epoch at whatever instant the clock currently holds and performs three sweeps in one request: quoted applications whose quote has expired, in-force policies whose period has matured, and renewal assessments whose remediation deadline has passed."
    PRD §2.5: "Every row the sweep touches has its `version` incremented by 1."
    PRD §3.5: "An in-force policy matures when the epoch sweep runs at or after `period_end`, at which point `lifecycle_status` becomes `EXPIRED` and the policy's `version` is incremented by 1."

    Design: Corner/endpoints/run_epoch_with_nothing_due_is_a_no_op
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = _bound_aurora_policy(api)
    X.set_clock(api, "2026-08-02T00:00:00Z")

    policy_before = X.read_policy(api, chain["policy"]["id"])
    application_before = X.read_application(api, chain["application"]["id"])

    resp = api.run_epoch(UNDERWRITER_HEADERS)
    report = validate_success(resp, expected_status=200)

    assert report["expired_application_count"] == 0, (
        f"expired_application_count: expected 0, got {report['expired_application_count']}"
    )
    assert report["expired_policy_count"] == 0, (
        f"expired_policy_count: expected 0, got {report['expired_policy_count']}"
    )
    assert report["non_renewed_assessment_count"] == 0, (
        "non_renewed_assessment_count: expected 0, got "
        f"{report['non_renewed_assessment_count']}"
    )
    assert _instant(report["run_at"]) == _instant("2026-08-02T00:00:00Z"), (
        f"run_at: expected the current clock instant, got {report['run_at']}"
    )

    policy_after = X.read_policy(api, chain["policy"]["id"])
    application_after = X.read_application(api, chain["application"]["id"])
    assert policy_after["lifecycle_status"] == "INFORCE", (
        f"policy lifecycle_status: expected INFORCE, got {policy_after['lifecycle_status']}"
    )
    assert policy_after["version"] == policy_before["version"], (
        "an idle sweep must touch no policy row: version moved from "
        f"{policy_before['version']} to {policy_after['version']}"
    )
    assert application_after["status"] == "BOUND", (
        f"application status: expected BOUND, got {application_after['status']}"
    )
    assert application_after["version"] == application_before["version"], (
        "an idle sweep must touch no application row: version moved from "
        f"{application_before['version']} to {application_after['version']}"
    )


# --------------------------------------------------------------------------
# Panel amendment
# --------------------------------------------------------------------------
def test_logged_hours_price_off_the_pinned_rate_not_the_amended_panel_rate(api):
    """PRD §3.7: "Two rates are pinned at that instant and never move again: `approved_rate_usd` from the chosen firm's `pre_approved_hourly_rate_usd` and `approved_per_record_rate_usd` from its `per_record_notification_rate_usd`."
    PRD §3.7: "Amendments affect future eligibility and future ranking only; a rate already pinned on an existing engagement is never rewritten."
    PRD §3.7: "`incurred_amount_usd` is then the sum of two independently rounded terms: cumulative `incurred_hours` multiplied by `approved_rate_usd`, rounded half up to 2 decimal places; plus cumulative `records_notified` multiplied by `approved_per_record_rate_usd`, rounded half up to 2 decimal places."
    PRD §3.7: "The first log moves the engagement from `AUTHORIZED` to `ACTIVE`; every later log is a self-loop within `ACTIVE`."

    Design: Corner/endpoints/engagement_keeps_its_pinned_rate_after_the_panel_rate_is_raised
    """
    chain = _bound_aurora_policy(api)
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    vendor = X.create_vendor(
        api,
        vendor_name="Ironclad Forensics",
        vendor_type="FORENSICS",
        pre_approved_hourly_rate_usd=500,
        per_record_notification_rate_usd=0,
        specialty_sectors=["HEALTHCARE", "FINANCIAL"],
        tier=1,
        capacity_concurrent_engagements=1,
    )
    engagement = X.authorize_engagement(
        api,
        claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
    )
    assert_money(engagement["approved_rate_usd"], 500.00, "approved_rate_usd at authorisation")

    amended = validate_success(
        api.update_panel_vendor(
            vendor["id"], {"pre_approved_hourly_rate_usd": 900}, PANEL_ADMIN_HEADERS
        ),
        expected_status=200,
    )
    assert_money(amended["pre_approved_hourly_rate_usd"], 900.00, "pre_approved_hourly_rate_usd")

    resp = api.log_engagement_hours(engagement["id"], {"hours": 4}, ADJUSTER_HEADERS)
    logged = validate_success(resp, expected_status=200)

    assert logged["status"] == "ACTIVE", (
        f"engagement status after the first log: expected ACTIVE, got {logged['status']}"
    )
    assert_money(logged["approved_rate_usd"], 500.00, "approved_rate_usd after the amendment")
    assert float(logged["incurred_hours"]) == 4.0, (
        f"incurred_hours: expected 4, got {logged['incurred_hours']}"
    )
    assert_money(logged["incurred_amount_usd"], 2000.00, "incurred_amount_usd")

    vendor_after = validate_success(
        api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS), expected_status=200
    )
    assert_money(
        vendor_after["pre_approved_hourly_rate_usd"], 900.00, "panel pre_approved_hourly_rate_usd"
    )


def test_panel_vendor_patch_leaves_unsupplied_fields_alone(api):
    """PRD §3.7: "Amending a firm may change `status`, `pre_approved_hourly_rate_usd`, `per_record_notification_rate_usd`, `specialty_sectors`, `tier`, or `capacity_concurrent_engagements`, and increments the firm's `version` by 1."
    PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp refreshed on every change to the row, and `version` is an integer that starts at 1 and increments by exactly 1 on every mutation."

    Design: Corner/endpoints/panel_vendor_patch_updates_only_the_supplied_fields
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    vendor = X.create_vendor(
        api,
        vendor_name="Ironclad Forensics",
        vendor_type="FORENSICS",
        pre_approved_hourly_rate_usd=500,
        per_record_notification_rate_usd=0,
        specialty_sectors=["HEALTHCARE", "FINANCIAL"],
        tier=1,
        capacity_concurrent_engagements=1,
    )
    assert vendor["version"] == 1, f"a new panel firm starts at version 1, got {vendor['version']}"

    resp = api.update_panel_vendor(vendor["id"], {"tier": 2}, PANEL_ADMIN_HEADERS)
    amended = validate_success(resp, expected_status=200)

    assert amended["tier"] == 2, f"tier: expected 2, got {amended['tier']}"
    assert amended["vendor_name"] == "Ironclad Forensics", (
        f"vendor_name changed to {amended['vendor_name']}"
    )
    assert amended["vendor_type"] == "FORENSICS", (
        f"vendor_type changed to {amended['vendor_type']}"
    )
    assert amended["status"] == "ACTIVE", f"status changed to {amended['status']}"
    assert_money(amended["pre_approved_hourly_rate_usd"], 500.00, "pre_approved_hourly_rate_usd")
    assert_money(
        amended["per_record_notification_rate_usd"], 0.00, "per_record_notification_rate_usd"
    )
    assert amended["capacity_concurrent_engagements"] == 1, (
        "capacity_concurrent_engagements changed to "
        f"{amended['capacity_concurrent_engagements']}"
    )
    assert sorted(amended["specialty_sectors"]) == ["FINANCIAL", "HEALTHCARE"], (
        f"specialty_sectors changed to {amended['specialty_sectors']}"
    )
    assert amended["version"] == 2, (
        f"version: expected 2 after one amendment, got {amended['version']}"
    )


# --------------------------------------------------------------------------
# Filtered discovery channels
# --------------------------------------------------------------------------
def test_claim_payment_list_partitions_the_ledger_by_payment_status(api):
    """PRD §3.8: "Payment rows are readable individually and as a list in `created_at` ascending order, filterable by `incident_claim_id`, `coverage_section_id`, `loss_source`, and `payment_status` — and since payment rows are created only by cascade, that list is their only discovery channel."
    PRD §3.8: "A `ClaimsAdjuster` reverses a posted payment row, supplying a `reversal_reason`. The row must be in `POSTED`; a row already `REVERSED` is refused with `ERR_INVALID_PAYMENT_STATE`."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/claim_payment_list_filters_by_payment_status
    """
    chain = _settled_ransomware_claim(api)
    claim_id = chain["claim"]["id"]

    posted_rows = X.list_payments_for_claim(api, claim_id)
    assert len(posted_rows) == 1, (
        f"the settled claim should carry exactly one payment row, got {len(posted_rows)}"
    )
    payment_id = posted_rows[0]["id"]
    validate_success(
        api.reverse_claim_payment(
            payment_id, {"reversal_reason": "CLERICAL_ERROR"}, ADJUSTER_HEADERS
        ),
        expected_status=200,
    )

    reversed_rows, reversed_meta = validate_paginated(
        api.list_claim_payments(
            ADJUSTER_HEADERS,
            params={
                "incident_claim_id": claim_id,
                "payment_status": "REVERSED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert reversed_meta["total_count"] == 1, (
        f"REVERSED filter total_count: expected 1, got {reversed_meta['total_count']}"
    )
    assert reversed_meta["has_more"] is False, "one row on a limit of 10 leaves nothing more"
    assert len(reversed_rows) == 1, f"expected one REVERSED row, got {len(reversed_rows)}"
    row = reversed_rows[0]
    assert row["id"] == payment_id, f"expected the reversed row {payment_id}, got {row['id']}"
    assert row["payment_status"] == "REVERSED", (
        f"payment_status: expected REVERSED, got {row['payment_status']}"
    )
    assert_money(row["gross_amount_usd"], 50000.00, "gross_amount_usd")
    assert_money(row["net_paid_usd"], 45000.00, "net_paid_usd")

    _posted, posted_meta = validate_paginated(
        api.list_claim_payments(
            ADJUSTER_HEADERS,
            params={
                "incident_claim_id": claim_id,
                "payment_status": "POSTED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert posted_meta["total_count"] == 0, (
        f"POSTED filter total_count: expected 0, got {posted_meta['total_count']}"
    )

    _all_rows, all_meta = validate_paginated(
        api.list_claim_payments(
            ADJUSTER_HEADERS,
            params={"incident_claim_id": claim_id, "limit": 10, "offset": 0},
        )
    )
    assert all_meta["total_count"] == 1, (
        f"unfiltered total_count: expected 1, got {all_meta['total_count']}"
    )


def test_panel_register_filters_by_vendor_type_before_it_paginates(api):
    """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, accepts a minimum of 1 and a maximum of 100. `offset` skips a number of rows from the front of the result set and defaults to 0."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §3.7: "The panel register is readable by all five roles, ordered `tier` ascending, then `pre_approved_hourly_rate_usd` ascending, then `created_at` ascending — the very order the selector applies — and filterable by `vendor_type` and `status`; individual firms are readable by `vendor_id` including the live `active_engagement_count`."

    Design: Corner/endpoints/panel_vendor_list_filters_by_type_and_paginates
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    X.create_vendor(
        api,
        vendor_name="Ironclad Forensics",
        vendor_type="FORENSICS",
        pre_approved_hourly_rate_usd=500,
        per_record_notification_rate_usd=0,
        specialty_sectors=["HEALTHCARE", "FINANCIAL"],
        tier=1,
        capacity_concurrent_engagements=1,
    )
    X.create_vendor(
        api,
        vendor_name="Beacon DFIR",
        vendor_type="FORENSICS",
        pre_approved_hourly_rate_usd=450,
        per_record_notification_rate_usd=0,
        specialty_sectors=["HEALTHCARE"],
        tier=2,
        capacity_concurrent_engagements=2,
    )
    X.create_vendor(
        api,
        vendor_name="Sable DFIR",
        vendor_type="FORENSICS",
        pre_approved_hourly_rate_usd=450,
        per_record_notification_rate_usd=0,
        specialty_sectors=["HEALTHCARE"],
        tier=2,
        capacity_concurrent_engagements=2,
    )
    X.create_vendor(
        api,
        vendor_name="Kestrel Legal",
        vendor_type="LEGAL_COUNSEL",
        pre_approved_hourly_rate_usd=800,
        per_record_notification_rate_usd=0,
        specialty_sectors=["HEALTHCARE"],
        tier=1,
        capacity_concurrent_engagements=2,
    )

    rows, meta = validate_paginated(
        api.list_panel_vendors(
            PANEL_ADMIN_HEADERS, params={"vendor_type": "FORENSICS", "limit": 2, "offset": 1}
        )
    )
    assert meta["total_count"] == 3, (
        f"total_count must count only FORENSICS rows: expected 3, got {meta['total_count']}"
    )
    assert len(rows) == 2, f"limit 2 at offset 1 should return 2 rows, got {len(rows)}"
    assert meta["has_more"] is False, (
        "offset 1 plus 2 rows reaches the filtered total of 3, so has_more must be false"
    )
    assert all(row["vendor_type"] == "FORENSICS" for row in rows), (
        f"a non-FORENSICS row leaked into the filtered page: {rows}"
    )
    # The tier-1 firm sorts first on the declared panel ordering, so offset 1
    # skips exactly it and leaves the two tier-2 firms.
    assert {row["vendor_name"] for row in rows} == {"Beacon DFIR", "Sable DFIR"}, (
        f"expected the two tier-2 forensics firms, got {[row['vendor_name'] for row in rows]}"
    )

    first_page, first_meta = validate_paginated(
        api.list_panel_vendors(
            PANEL_ADMIN_HEADERS, params={"vendor_type": "FORENSICS", "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2, f"limit 2 at offset 0 should return 2 rows, got {len(first_page)}"
    assert first_meta["has_more"] is True, (
        "two of three filtered rows leave one behind, so has_more must be true"
    )
    assert first_page[0]["vendor_name"] == "Ironclad Forensics", (
        "the tier-1 firm must lead the declared panel ordering, got "
        f"{first_page[0]['vendor_name']}"
    )


def test_flat_child_lists_agree_with_the_nested_ones(api):
    """PRD §2.3: "Several endpoints do declare their own ordering — the control catalog is returned by `weight` descending then `control_key` ascending, the panel register by `tier` ascending then `pre_approved_hourly_rate_usd` ascending then `created_at` ascending, a policy's tower by `erosion_priority` ascending, and an application's attestations by `control_key` ascending — and where such an ordering is declared it replaces the default."
    PRD §3.5: "A policy's tower is readable under the policy in `erosion_priority` ascending order — exactly the order allocation walks — with a `section_key` filter, individual sections are readable by `section_id`, and underwriting and actuarial roles can search sections flat across policies with `policy_id` and `section_key` filters."
    PRD §3.5: "Each tower section is created with `sublimit_remaining_usd` equal to its `sublimit_usd`."
    PRD §3.2: "Attestations can be listed under their application in `control_key` ascending order, read individually, or swept across the whole book by underwriting and actuarial roles with `application_id` and `control_key` filters."
    PRD §3.3: "Scans are listed under their application in `created_at` ascending order with a `status` filter, read individually, and swept flat across applications by underwriting and actuarial roles with `application_id` and `status` filters."

    Design: Corner/endpoints/flat_child_lists_reach_every_child_by_parent_filter
    """
    X.set_clock(api, C.DEFAULT_CLOCK)
    chain = _bound_aurora_policy(api)
    policy_id = chain["policy"]["id"]
    application_id = chain["application"]["id"]

    flat_sections, flat_meta = validate_paginated(
        api.list_coverage_sections(
            UNDERWRITER_HEADERS, params={"policy_id": policy_id, "limit": 10, "offset": 0}
        )
    )
    assert flat_meta["total_count"] == 5, (
        f"the tower has five sections, got total_count {flat_meta['total_count']}"
    )
    assert flat_meta["has_more"] is False, "five rows on a limit of 10 leave nothing more"
    assert [row["section_key"] for row in flat_sections] == [
        "FIRST_PARTY_RESPONSE",
        "BUSINESS_INTERRUPTION",
        "DEPENDENT_BI",
        "THIRD_PARTY_LIABILITY",
        "CYBER_EXTORTION",
    ], f"sections out of erosion_priority order: {[r['section_key'] for r in flat_sections]}"

    nested_sections, _nested_meta = validate_paginated(
        api.list_policy_coverage_sections(
            policy_id, UNDERWRITER_HEADERS, params={"limit": 10, "offset": 0}
        )
    )
    assert [row["id"] for row in nested_sections] == [row["id"] for row in flat_sections], (
        "the nested tower listing and the flat search must agree row for row"
    )

    flat_attestations, attestation_meta = validate_paginated(
        api.list_control_attestations(
            UNDERWRITER_HEADERS,
            params={"application_id": application_id, "limit": 10, "offset": 0},
        )
    )
    assert attestation_meta["total_count"] == 5, (
        f"the application carries five attestations, got {attestation_meta['total_count']}"
    )
    nested_attestations, _ = validate_paginated(
        api.list_application_control_attestations(
            application_id, UNDERWRITER_HEADERS, params={"limit": 10, "offset": 0}
        )
    )
    assert {row["id"] for row in flat_attestations} == {
        row["id"] for row in nested_attestations
    }, "the flat attestation search must reach exactly the application's attestations"

    flat_scans, scan_meta = validate_paginated(
        api.list_external_scans(
            UNDERWRITER_HEADERS,
            params={"application_id": application_id, "limit": 10, "offset": 0},
        )
    )
    assert scan_meta["total_count"] == 1, (
        f"the application ordered exactly one scan, got {scan_meta['total_count']}"
    )
    assert flat_scans[0]["status"] == "COMPLETED", (
        f"the scan should be COMPLETED, got {flat_scans[0]['status']}"
    )

    first_party = next(
        row for row in flat_sections if row["section_key"] == "FIRST_PARTY_RESPONSE"
    )
    section = validate_success(
        api.get_coverage_section(first_party["id"], UNDERWRITER_HEADERS), expected_status=200
    )
    assert_money(section["sublimit_usd"], 1000000.00, "sublimit_usd")
    assert_money(section["sublimit_remaining_usd"], 1000000.00, "sublimit_remaining_usd")
