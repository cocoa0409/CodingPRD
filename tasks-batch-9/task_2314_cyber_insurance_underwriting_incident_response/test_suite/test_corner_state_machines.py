"""State machine behaviour: initial states, declared transitions, preconditions.

Every test builds all of its own state through the public API.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    UNDERWRITER_2,
    UNDERWRITER_2_HEADERS,
    UNDERWRITER_HEADERS,
    ErrorId,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_instant,
    assert_money,
    assert_score_2dp,
    assert_status,
    data_of,
    get_rows,
    get_total_count,
)

# The scanner contradicts only the optional email-filtering control, so the
# verified posture score lands at 87.50 with no mandatory gap.
STANDARD_SCAN_FINDINGS = [F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")]

# The scanner contradicts a mandatory control, opening a mandatory gap.
BACKUP_GAP_FINDINGS = [F.scan_finding("OFFLINE_BACKUPS", "CRITICAL", "PARTIAL")]


def _remediation_required_application(client):
    """Drive an application to REMEDIATION_REQUIRED off a scanned mandatory gap."""
    X.seed_catalog(client)
    account = X.create_account(client)
    application = X.create_application(client, account["id"])
    X.attest_controls(client, application["id"], C.ATTEST_95)
    X.submit_application(client, application["id"])
    scan = X.order_scan(client, application["id"])
    X.complete_scan(client, scan["id"], findings=BACKUP_GAP_FINDINGS)
    return account, X.read_application(client, application["id"])


def test_new_application_opens_in_draft_with_nothing_priced(api):
    """PRD §3.2: "A new application opens in `DRAFT`."

    PRD §3.4: "The **bindable run** fires at quote issuance, consumes
    `verified_control_score`, and writes `premium_usd`."

    PRD §3.4: "The **indicative run** fires at submission, consumes
    `attested_control_score`, and writes `indicative_premium_usd` — a figure
    issued before any scan can contradict the applicant."

    PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp refreshed on every
    change to the row, and `version` is an integer that starts at 1 and
    increments by exactly 1 on every mutation."

    Design: Corner/state_machines/application_starts_in_draft_with_null_scores
    """
    X.seed_catalog(api)
    account = X.create_account(api)

    application = data_of(
        api.create_application(
            F.application_payload(account["id"]), UNDERWRITER_HEADERS
        ),
        201,
    )

    assert_status(application, "DRAFT")
    assert application["verified_control_score"] is None
    assert application["indicative_premium_usd"] is None
    assert application["premium_usd"] is None
    assert application["quoted_by_user_id"] is None
    assert application["quote_expires_at"] is None
    assert application["version"] == 1


def test_bind_mints_the_policy_inforce_and_intact(api):
    """PRD §3.5: "The policy is minted with `lifecycle_status` `INFORCE` and
    `limit_status` `INTACT`."

    PRD §3.5: "`lapsed_warranty_control_keys` starts empty, `warranty_status`
    starts `COMPLIANT`, and `aggregation_flagged` starts false."

    PRD §3.5: "`aggregate_limit_usd` is copied from
    `requested_aggregate_limit_usd` and `aggregate_limit_remaining_usd` starts
    equal to it; `retention_usd` is copied from `requested_retention_usd`;
    `premium_usd` is copied from the application's `premium_usd` and becomes the
    earned-premium denominator of the loss ratio; `dependent_bi_definition` is
    copied from the application."

    PRD §3.5: "Binding takes a `QUOTED` application to `BOUND` and mints the
    policy."

    Design: Corner/state_machines/policy_starts_inforce_intact_and_compliant_at_bind
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]

    assert_status(policy, "INFORCE", field="lifecycle_status")
    assert_status(policy, "INTACT", field="limit_status")
    assert_money(policy["aggregate_limit_usd"], 5000000.00, "aggregate_limit_usd")
    assert_money(
        policy["aggregate_limit_remaining_usd"],
        5000000.00,
        "aggregate_limit_remaining_usd",
    )
    assert_money(policy["premium_usd"], 28458.00, "premium_usd")
    assert_money(policy["retention_usd"], 250000.00, "retention_usd")
    assert_status(policy, "COMPLIANT", field="warranty_status")
    assert policy["lapsed_warranty_control_keys"] == []
    assert policy["aggregation_flagged"] is False
    assert policy["cancelled_at"] is None
    assert policy["version"] == 1

    application = X.read_application(api, chain["application"]["id"])
    assert_status(application, "BOUND")


def test_submit_moves_draft_to_submitted_and_prices_the_floor(api):
    """PRD §3.2: "Submitting the application moves it from `DRAFT` to
    `SUBMITTED`, and there is one precondition: an attestation row must exist
    for every catalog control whose `is_mandatory` is true."

    PRD §3.2: "On success the server recomputes `attested_control_score` on the
    attested basis, writes `indicative_premium_usd` from the attested-basis
    pricing run, and increments the application's `version` by 1."

    PRD §3.4: "The premium is the gross premium multiplied by that multiplier,
    rounded half up to 2 decimal places, and then floored at 7,500.00 — the
    rounding is applied first and the floor second, so a computed 7,499.996
    rounds to 7,500.00 and a computed 6,000.00 becomes 7,500.00."

    PRD §3.2: "Each attestation write recomputes the application's
    `attested_control_score` and increments the application's `version` by 1."

    Design: Corner/state_machines/submit_moves_draft_application_to_submitted_and_prices_the_floor
    """
    X.seed_catalog(api)
    account = X.create_account(api, C.ACCOUNT_BITWISE)
    application = X.create_application(
        api,
        account["id"],
        requested_aggregate_limit_usd=250000,
        requested_retention_usd=0,
        dependent_bi_definition="BROAD_SYSTEM_FAILURE",
    )
    X.attest_controls(
        api,
        application["id"],
        {
            "MFA_PRIVILEGED": "FULL",
            "OFFLINE_BACKUPS": "FULL",
            "EDR_COVERAGE": "PARTIAL",
            "EMAIL_FILTERING": "PARTIAL",
            "INCIDENT_RESPONSE_PLAN": "PARTIAL",
        },
    )

    submitted = data_of(api.submit_application(application["id"], UNDERWRITER_HEADERS))

    assert_status(submitted, "SUBMITTED")
    assert_score_2dp(
        submitted["attested_control_score"], 77.50, "attested_control_score"
    )
    # The 5,500 technology base rate over a 0.25 million first layer with a
    # 0.95 modifier computes 1,306.25, which the floor lifts to 7,500.00.
    assert_money(submitted["indicative_premium_usd"], 7500.00, "indicative_premium_usd")
    assert submitted["verified_control_score"] is None
    # 1 at creation, one per attestation write, one for the submit.
    assert submitted["version"] == 7


def test_failed_scan_leaves_the_application_in_submitted(api):
    """PRD §3.3: "A `FAILED` outcome does nothing else."

    PRD §3.3: "Any `findings` supplied alongside it are ignored, no attestation
    acquires a verified level, and the application remains in `SUBMITTED`
    waiting for another attempt."

    PRD §3.3: "Both outcomes stamp `completed_at` from the logical clock and
    increment the scan's `version` by 1, and both are terminal for the scan."

    Design: Corner/state_machines/scan_failed_outcome_leaves_application_in_submitted
    """
    X.seed_catalog(api)
    account = X.create_account(api)
    application = X.create_application(api, account["id"])
    X.attest_controls(api, application["id"], C.ATTEST_95)
    X.submit_application(api, application["id"])
    X.set_clock(api, "2026-08-04T00:00:00Z")
    scan = X.order_scan(api, application["id"], scan_score=40)

    returned = X.complete_scan(
        api,
        scan["id"],
        findings=[F.scan_finding("OFFLINE_BACKUPS", "CRITICAL", "NONE")],
        outcome="FAILED",
    )

    assert_status(returned, "FAILED")
    assert_instant(returned["completed_at"], "2026-08-04T00:00:00Z", "completed_at")

    after = X.read_application(api, application["id"])
    assert_status(after, "SUBMITTED")
    assert after["verified_control_score"] is None

    attestations = get_rows(
        api.list_application_control_attestations(application["id"], UNDERWRITER_HEADERS)
    )
    assert len(attestations) == len(C.ALL_CONTROL_KEYS)
    for row in attestations:
        assert row["verified_level"] is None, (
            f"{row['control_key']} acquired a verified level from a FAILED scan"
        )

    owner = data_of(api.get_insured_account(account["id"], UNDERWRITER_HEADERS))
    assert owner["open_remediation_count"] == 0


def test_resubmit_controls_returns_the_application_to_submitted(api):
    """PRD §3.3: "From `REMEDIATION_REQUIRED` the `Insured` or an `Underwriter`
    re-attests the failed controls and the application returns to `SUBMITTED`."

    PRD §3.3: "Each named control's `attested_level` is updated;
    `verified_level` is reset to null on *every* attestation of the application,
    not merely the resubmitted ones, because the evidence they were derived from
    is now stale; `verified_control_score` is set to null, `mandatory_gap_count`
    back to 0, and `mandatory_gap_control_keys` back to an empty list;
    `attested_control_score` and `indicative_premium_usd` are recomputed; the
    owning account's `open_remediation_count` is decremented by 1 with that
    account's `version` incremented by 1; and the application's own `version` is
    incremented by 1."

    Design: Corner/state_machines/resubmit_controls_returns_remediation_required_application_to_submitted
    """
    account, application = _remediation_required_application(api)
    assert_status(application, "REMEDIATION_REQUIRED")

    revised = data_of(
        api.resubmit_controls(
            application["id"],
            F.resubmit_controls_payload(
                [{"control_key": "OFFLINE_BACKUPS", "attested_level": "FULL"}]
            ),
            UNDERWRITER_HEADERS,
        )
    )

    assert_status(revised, "SUBMITTED")
    assert revised["verified_control_score"] is None
    assert revised["mandatory_gap_count"] == 0
    assert revised["mandatory_gap_control_keys"] == []
    assert_score_2dp(revised["attested_control_score"], 95.00, "attested_control_score")
    assert_money(revised["indicative_premium_usd"], 25398.00, "indicative_premium_usd")

    attestations = get_rows(
        api.list_application_control_attestations(application["id"], UNDERWRITER_HEADERS)
    )
    for row in attestations:
        assert row["verified_level"] is None, (
            f"{row['control_key']} kept a stale verified level after resubmission"
        )

    owner = data_of(api.get_insured_account(account["id"], UNDERWRITER_HEADERS))
    assert owner["open_remediation_count"] == 0


def test_requoting_supersedes_the_live_quote_and_recomputes_the_expiry(api):
    """PRD §3.5: "Quoting is also legal against an application already in
    `QUOTED`, in which case it is a self-loop supersede: the previous
    `premium_usd`, `quoted_by_user_id`, and `quote_expires_at` are overwritten by
    the new quote."

    PRD §3.5: "On success the bindable pricing run writes `premium_usd`,
    `quoted_by_user_id` is stamped with the acting `X-User-ID`,
    `quote_expires_at` is set to the current logical clock instant plus 30 days,
    and the application's `version` is incremented by 1."

    Design: Corner/state_machines/requoting_supersedes_the_live_quote_and_recomputes_the_expiry
    """
    chain = X.quoted_application(api, findings=STANDARD_SCAN_FINDINGS)
    first_quote = chain["application"]
    assert_instant(
        first_quote["quote_expires_at"], "2026-08-31T00:00:00Z", "quote_expires_at"
    )

    X.set_clock(api, "2026-08-10T00:00:00Z")
    requoted = data_of(
        api.quote_application(
            first_quote["id"],
            F.quote_payload(first_quote["version"]),
            UNDERWRITER_2_HEADERS,
        )
    )

    assert_status(requoted, "QUOTED")
    assert_instant(
        requoted["quote_expires_at"], "2026-09-09T00:00:00Z", "quote_expires_at"
    )
    assert requoted["quoted_by_user_id"] == UNDERWRITER_2
    assert_money(requoted["premium_usd"], 28458.00, "premium_usd")
    assert requoted["version"] == first_quote["version"] + 1


def test_decline_from_remediation_required_releases_the_account_counter(api):
    """PRD §3.5: "Declining is available from `UNDERWRITING`,
    `REMEDIATION_REQUIRED`, or `QUOTED`."

    PRD §3.5: "The `declined_reason` supplied by the underwriter is stored
    verbatim, `premium_usd` is cleared to null, and — when the application was
    sitting in `REMEDIATION_REQUIRED` — the owning account's
    `open_remediation_count` is decremented by 1."

    Design: Corner/state_machines/decline_from_remediation_required_releases_the_account_counter
    """
    account, application = _remediation_required_application(api)
    assert_status(application, "REMEDIATION_REQUIRED")

    declined = data_of(
        api.decline_application(
            application["id"],
            F.decline_payload("BACKUP_POSTURE_UNACCEPTABLE"),
            UNDERWRITER_HEADERS,
        )
    )

    assert_status(declined, "DECLINED")
    assert declined["declined_reason"] == "BACKUP_POSTURE_UNACCEPTABLE"
    assert declined["premium_usd"] is None
    # The verified figure the decline was based on is retained for audit.
    assert_score_2dp(
        declined["verified_control_score"], 82.50, "verified_control_score"
    )

    owner = data_of(api.get_insured_account(account["id"], UNDERWRITER_HEADERS))
    assert owner["open_remediation_count"] == 0


def test_confirm_coverage_moves_the_triaged_claim_and_sets_the_reserve(api):
    """PRD §3.6: "Confirming coverage moves the claim from `TRIAGE` to
    `COVERAGE_CONFIRMED`."

    PRD §3.6: "On success `covered_section_keys` and `reservation_of_rights` are
    stored, `reserved_amount_usd` is set from `initial_reserve_usd`, and the
    claim's `version` is incremented by 1."

    PRD §3.6: "`initial_reserve_usd` sets the opening case reserve, and an
    optional `reservation_of_rights` boolean, defaulting to false, records that
    coverage is confirmed subject to a reservation."

    Design: Corner/state_machines/confirm_coverage_moves_triaged_claim_and_sets_the_reserve
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.notify_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
    )
    X.triage_claim(api, claim["id"])

    confirmed = X.confirm_coverage(
        api,
        claim["id"],
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )

    assert_status(confirmed, "COVERAGE_CONFIRMED")
    assert confirmed["covered_section_keys"] == [
        "FIRST_PARTY_RESPONSE",
        "BUSINESS_INTERRUPTION",
    ]
    assert_money(confirmed["reserved_amount_usd"], 300000.00, "reserved_amount_usd")
    assert confirmed["reservation_of_rights"] is False
    assert_money(confirmed["retention_absorbed_usd"], 0.00, "retention_absorbed_usd")
    assert_money(confirmed["paid_total_usd"], 0.00, "paid_total_usd")

    after = X.read_policy(api, policy["id"])
    assert_money(
        after["aggregate_limit_remaining_usd"],
        5000000.00,
        "aggregate_limit_remaining_usd",
    )


def test_first_hour_log_moves_the_engagement_from_authorized_to_active(api):
    """PRD §3.7: "The first log moves the engagement from `AUTHORIZED` to
    `ACTIVE`; every later log is a self-loop within `ACTIVE`."

    PRD §3.7: "`incurred_amount_usd` is then the sum of two independently
    rounded terms: cumulative `incurred_hours` multiplied by `approved_rate_usd`,
    rounded half up to 2 decimal places; plus cumulative `records_notified`
    multiplied by `approved_per_record_rate_usd`, rounded half up to 2 decimal
    places."

    PRD §3.7: "Supplying `panel_vendor_id` directs a firm and sets
    `selection_mode` to `DIRECTED`; omitting it invokes the selector and sets
    `selection_mode` to `PANEL_SELECTED`."

    PRD §3.7: "A `ClaimsAdjuster` authorises a panel deployment against a claim
    in `COVERAGE_CONFIRMED` or `RESPONSE_ACTIVE`; the first authorisation
    advances the claim from `COVERAGE_CONFIRMED` to `RESPONSE_ACTIVE`, and
    subsequent ones are a self-loop within `RESPONSE_ACTIVE`."

    Design: Corner/state_machines/first_hour_log_moves_engagement_from_authorized_to_active
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
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
    engagement = X.authorize_engagement(
        api,
        claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
    )
    assert_status(engagement, "AUTHORIZED")

    logged = X.log_hours(api, engagement["id"], hours=4)

    assert_status(logged, "ACTIVE")
    assert logged["incurred_hours"] == 4
    assert logged["records_notified"] == 0
    assert_money(logged["incurred_amount_usd"], 2000.00, "incurred_amount_usd")
    assert logged["selection_mode"] == "DIRECTED"
    assert_money(logged["approved_rate_usd"], 500.00, "approved_rate_usd")

    assert_status(X.read_claim(api, claim["id"]), "RESPONSE_ACTIVE")
    firm = data_of(api.get_panel_vendor(vendor["id"], UNDERWRITER_HEADERS))
    assert firm["active_engagement_count"] == 1


def test_engagement_completion_fully_absorbed_by_retention_writes_no_payment(api):
    """PRD §3.8: "Retention comes first, once per claim, off the top, before any
    section is touched."

    PRD §3.8: "The loss allocated to a section is the lesser of the remainder and
    that section's `sublimit_remaining_usd`, rounded half up to 2 decimal places;
    a section whose allocation would be zero or less is skipped without producing
    a zero-value payment row at all."

    PRD §3.7: "Completing an engagement takes it from `AUTHORIZED` or `ACTIVE` to
    `COMPLETED`."

    PRD §3.7: "The firm's `active_engagement_count` is decremented by 1 and its
    `version` incremented by 1, the section and policy remaining figures and
    `limit_status` are updated exactly as on the payment cascade, and the
    engagement's `version` is incremented by 1."

    Design: Corner/state_machines/engagement_completion_fully_absorbed_by_retention_creates_no_payment
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    vendor = X.create_vendor(
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
    engagement = X.authorize_engagement(
        api,
        claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
    )
    X.log_hours(api, engagement["id"], hours=4)

    completed = X.complete_engagement(api, engagement["id"])

    assert_status(completed, "COMPLETED")

    after_claim = X.read_claim(api, claim["id"])
    assert_money(
        after_claim["retention_absorbed_usd"], 2000.00, "retention_absorbed_usd"
    )
    assert_money(after_claim["paid_total_usd"], 0.00, "paid_total_usd")
    assert_money(after_claim["unallocated_loss_usd"], 0.00, "unallocated_loss_usd")

    assert (
        get_total_count(
            api.list_claim_payments(
                UNDERWRITER_HEADERS, params={"incident_claim_id": claim["id"]}
            )
        )
        == 0
    )

    after_policy = X.read_policy(api, policy["id"])
    assert_money(
        after_policy["aggregate_limit_remaining_usd"],
        5000000.00,
        "aggregate_limit_remaining_usd",
    )
    assert_status(after_policy, "INTACT", field="limit_status")

    section = data_of(
        api.get_coverage_section(
            chain["sections"]["FIRST_PARTY_RESPONSE"]["id"], UNDERWRITER_HEADERS
        )
    )
    assert_money(
        section["sublimit_remaining_usd"], 1000000.00, "sublimit_remaining_usd"
    )

    firm = data_of(api.get_panel_vendor(vendor["id"], UNDERWRITER_HEADERS))
    assert firm["active_engagement_count"] == 0


def test_renewal_assessment_with_no_requirements_opens_in_conditions_met(api):
    """PRD §3.9: "A non-empty requirement list creates the assessment in
    `CONDITIONS_ISSUED`; an empty list means there is nothing to remediate, and
    the assessment is created directly in `CONDITIONS_MET` with
    `verified_control_keys` empty."

    PRD §3.9: "Either way `verification_round` starts at 0."

    Design: Corner/state_machines/renewal_assessment_with_no_required_controls_opens_directly_in_conditions_met
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]
    X.set_clock(api, "2027-05-05T00:00:00Z")

    assessment = data_of(
        api.create_renewal_assessment(
            policy["id"], F.renewal_assessment_payload([]), UNDERWRITER_HEADERS
        ),
        201,
    )

    assert_status(assessment, "CONDITIONS_MET")
    assert assessment["required_control_keys"] == []
    assert assessment["verified_control_keys"] == []
    assert assessment["verification_round"] == 0
    assert assessment["non_renewal_reason"] is None
    assert assessment["loss_ratio"] is None
    assert assessment["renewal_premium_usd"] is None
    assert assessment["version"] == 1

    assert_status(X.read_policy(api, policy["id"]), "INFORCE", field="lifecycle_status")


def test_partial_verification_returns_the_assessment_to_conditions_issued(api):
    """PRD §3.9: "When it covers only part of the requirements and
    `verification_round` after the increment is still below 2, the assessment
    returns to `CONDITIONS_ISSUED` so the insured can submit more evidence."

    PRD §3.9: "The newly verified set is merged with whatever was already
    verified, held sorted `control_key` ascending, and `verification_round` is
    incremented by 1."

    Design: Corner/state_machines/partial_verification_returns_the_assessment_to_conditions_issued
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]
    X.set_clock(api, "2027-05-05T00:00:00Z")
    assessment = X.open_renewal_assessment(
        api,
        policy["id"],
        required_control_keys=["EMAIL_FILTERING", "INCIDENT_RESPONSE_PLAN"],
        remediation_due_at="2027-06-01T00:00:00Z",
    )
    X.submit_remediation(
        api, assessment["id"], ["EMAIL_FILTERING", "INCIDENT_RESPONSE_PLAN"]
    )

    verified = X.verify_remediation(api, assessment["id"], ["EMAIL_FILTERING"])

    assert_status(verified, "CONDITIONS_ISSUED")
    assert verified["verified_control_keys"] == ["EMAIL_FILTERING"]
    assert verified["verification_round"] == 1
    assert verified["non_renewal_reason"] is None

    assert_status(X.read_policy(api, policy["id"]), "INFORCE", field="lifecycle_status")


def test_submit_without_every_mandatory_attestation_is_refused(api):
    """PRD §3.2: "A submission with any mandatory control unattested is refused
    with `ERR_MANDATORY_ATTESTATION_MISSING`."

    PRD §3.2: "Each attestation write recomputes the application's
    `attested_control_score` and increments the application's `version` by 1."

    Design: Corner/state_machines/submit_without_every_mandatory_attestation_returns_422
    """
    X.seed_catalog(api)
    account = X.create_account(api)
    application = X.create_application(api, account["id"])
    # EDR_COVERAGE is mandatory in the catalog and is deliberately left unattested.
    X.attest_controls(
        api,
        application["id"],
        {
            "MFA_PRIVILEGED": "FULL",
            "OFFLINE_BACKUPS": "FULL",
            "EMAIL_FILTERING": "FULL",
            "INCIDENT_RESPONSE_PLAN": "PARTIAL",
        },
    )

    response = api.submit_application(application["id"], UNDERWRITER_HEADERS)
    validate_error(response, ErrorId.MANDATORY_ATTESTATION_MISSING)

    after = X.read_application(api, application["id"])
    assert_status(after, "DRAFT")
    assert_score_2dp(after["attested_control_score"], 75.00, "attested_control_score")
    assert after["indicative_premium_usd"] is None
    # 1 at creation plus one per accepted attestation; the refused submit adds nothing.
    assert after["version"] == 5


def test_quote_is_refused_when_the_newest_scan_came_back_failed(api):
    """PRD §3.5: "The application's latest scan by `created_at` descending must
    be in `COMPLETED`."

    PRD §3.5: "A newer scan that is still `PENDING`, or one that came back
    `FAILED`, blocks the quote even when an earlier scan completed successfully —
    the newest attempt governs."

    PRD §3.3: "A `FAILED` outcome does nothing else."

    Design: Corner/state_machines/quote_with_a_newer_failed_scan_returns_422
    """
    X.seed_catalog(api)
    account = X.create_account(api)
    application = X.create_application(api, account["id"])
    X.attest_controls(api, application["id"], C.ATTEST_95)
    X.submit_application(api, application["id"])
    first_scan = X.order_scan(api, application["id"])
    X.complete_scan(api, first_scan["id"], findings=STANDARD_SCAN_FINDINGS)
    second_scan = X.order_scan(
        api, application["id"], scan_score=30, vendor_name="Second Look"
    )
    X.complete_scan(api, second_scan["id"], outcome="FAILED")
    current = X.read_application(api, application["id"])
    assert_status(current, "UNDERWRITING")

    response = api.quote_application(
        application["id"], F.quote_payload(current["version"]), UNDERWRITER_HEADERS
    )
    validate_error(response, ErrorId.SCAN_NOT_COMPLETED)

    after = X.read_application(api, application["id"])
    assert_status(after, "UNDERWRITING")
    assert after["premium_usd"] is None
    assert_score_2dp(after["verified_control_score"], 87.50, "verified_control_score")


def test_resubmit_controls_naming_an_ungapped_control_is_refused(api):
    """PRD §3.3: "The request body carries `attestations`, a list of revised
    control-and-level pairs, and every `control_key` it names must already appear
    in the application's `mandatory_gap_control_keys` — the loop reopens only the
    controls that actually failed."

    PRD §2.10: "**Schema** — required fields present, enum values inside their
    declared domains, non-negative numerics, monetary fields at most 2 decimals,
    ratio fields inside range (`coinsurance_pct` at most 0.50,
    `gross_profit_margin_pct` at most 1.00, `footprint_pct` at most 1.00),
    timestamps in ISO 8601 UTC, interval fields correctly ordered (`period_start`
    before `period_end`, `outage_start_at` before `outage_end_at`,
    `deployment_start_at` before `deployment_end_at`), `waiting_period_hours`
    greater than 0 and required for a `BUSINESS_INTERRUPTION` or `DEPENDENT_BI`
    section and absent — null — for every other section key, and
    `requested_aggregate_limit_usd` at least the 250,000 minimum; otherwise
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/state_machines/resubmit_controls_naming_an_ungapped_control_returns_invalid_request
    """
    account, application = _remediation_required_application(api)
    assert application["mandatory_gap_control_keys"] == ["OFFLINE_BACKUPS"]

    response = api.resubmit_controls(
        application["id"],
        F.resubmit_controls_payload(
            [{"control_key": "EMAIL_FILTERING", "attested_level": "FULL"}]
        ),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, ErrorId.INVALID_REQUEST)

    after = X.read_application(api, application["id"])
    assert_status(after, "REMEDIATION_REQUIRED")
    assert after["mandatory_gap_control_keys"] == ["OFFLINE_BACKUPS"]
    assert_score_2dp(after["verified_control_score"], 82.50, "verified_control_score")

    owner = data_of(api.get_insured_account(account["id"], UNDERWRITER_HEADERS))
    assert owner["open_remediation_count"] == 1
