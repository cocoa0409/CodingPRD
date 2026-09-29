"""State machine behaviour: terminal states, undeclared transitions, sweeps.

Every test builds all of its own state through the public API.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ADJUSTER_2_HEADERS,
    ADJUSTER_HEADERS,
    ACTUARY_HEADERS,
    PANEL_ADMIN_HEADERS,
    UNDERWRITER_1,
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

RANSOMWARE_CLAIM = {
    "incident_type": "RANSOMWARE",
    "incident_discovered_at": "2026-09-05T00:00:00Z",
    "outage_start_at": "2026-09-05T00:00:00Z",
    "outage_end_at": "2026-09-08T00:00:00Z",
}


def _confirmed_ransomware_claim(client, reserve=300000):
    """Bind a policy, then notify, triage and confirm a ransomware claim on it."""
    chain = X.bound_policy(client, findings=STANDARD_SCAN_FINDINGS)
    X.set_clock(client, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        client,
        chain["policy"]["id"],
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=reserve,
        **RANSOMWARE_CLAIM,
    )
    return chain, claim


def _settled_claim(client):
    """Carry a confirmed claim through an accepted proof of loss to settlement."""
    chain, claim = _confirmed_ransomware_claim(client)
    proof = X.file_proof(
        client,
        claim["id"],
        claimed_bi_loss_usd=300000,
        gross_profit_margin_pct=1.0,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    X.accept_proof(client, proof["id"])
    return chain, claim, proof


def _forensics_vendor(client):
    return X.create_vendor(
        client,
        F.panel_vendor_payload(
            vendor_name="Ironclad Forensics",
            vendor_type="FORENSICS",
            pre_approved_hourly_rate_usd=500,
            per_record_notification_rate_usd=0,
            specialty_sectors=["HEALTHCARE", "FINANCIAL"],
            tier=1,
            capacity_concurrent_engagements=1,
        ),
        headers=PANEL_ADMIN_HEADERS,
    )


def test_triage_on_a_coverage_confirmed_claim_is_refused(api):
    """PRD §3.6: "**Triage.** A `ClaimsAdjuster` moves the claim from `NOTIFIED`
    to `TRIAGE`; the policy must still be in `INFORCE`."

    PRD §3.6: "Any transition not declared for the claim's current state, and any
    attempt to act on a terminal claim at all, is refused with
    `ERR_INVALID_CLAIM_STATE`."

    Design: Corner/state_machines/triage_on_a_coverage_confirmed_claim_returns_invalid_claim_state
    """
    _chain, claim = _confirmed_ransomware_claim(api)
    assert_status(claim, "COVERAGE_CONFIRMED")

    response = api.triage_incident_claim(claim["id"], ADJUSTER_HEADERS)
    validate_error(response, ErrorId.INVALID_CLAIM_STATE)

    after = X.read_claim(api, claim["id"])
    assert_status(after, "COVERAGE_CONFIRMED")
    assert_money(after["reserved_amount_usd"], 300000.00, "reserved_amount_usd")
    assert after["covered_section_keys"] == [
        "FIRST_PARTY_RESPONSE",
        "BUSINESS_INTERRUPTION",
    ]


def test_quote_on_a_draft_application_reports_the_state_failure(api):
    """PRD §3.5: "An `Underwriter` issues a bindable quote against an application
    in `UNDERWRITING`, taking it to `QUOTED`."

    PRD §2.10: "**Own state** — the addressed row is in a state from which the
    requested transition is declared in §3; terminal states admit no transition
    at all."

    PRD §2.10: "When several checks could reject the same request, the order in
    which they are evaluated determines which error the client sees, and that
    order is fixed."

    PRD §2.10: "Later checks never mask earlier ones."

    Design: Corner/state_machines/quote_on_a_draft_application_returns_invalid_application_state
    """
    X.seed_catalog(api)
    account = X.create_account(api)
    application = X.create_application(api, account["id"])
    X.attest_controls(api, application["id"], C.ATTEST_95)
    draft = X.read_application(api, application["id"])
    assert_status(draft, "DRAFT")

    # No scan has ever been ordered, so the latest-scan gate would also fail;
    # the own-state check is evaluated first.
    response = api.quote_application(
        application["id"], F.quote_payload(draft["version"]), UNDERWRITER_HEADERS
    )
    validate_error(response, ErrorId.INVALID_APPLICATION_STATE)

    after = X.read_application(api, application["id"])
    assert_status(after, "DRAFT")
    assert after["premium_usd"] is None
    assert after["quoted_by_user_id"] is None


def test_issue_renewal_quote_from_conditions_issued_is_refused(api):
    """PRD §3.9: "**Pricing the renewal.** A `PortfolioActuary` issues the
    renewal quote against an assessment in `CONDITIONS_MET`, taking it to
    `RENEWAL_QUOTED`."

    PRD §3.9: "The assessment lifecycle runs `CONDITIONS_ISSUED`,
    `REMEDIATION_SUBMITTED`, `CONDITIONS_MET`, and terminates in
    `RENEWAL_QUOTED` or `NON_RENEWED`; a transition not declared for the current
    state is refused with `ERR_INVALID_ASSESSMENT_STATE`."

    Design: Corner/state_machines/issue_renewal_quote_from_conditions_issued_returns_invalid_assessment_state
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]
    X.set_clock(api, "2027-05-05T00:00:00Z")
    assessment = X.open_renewal_assessment(
        api,
        policy["id"],
        required_control_keys=["EMAIL_FILTERING"],
        remediation_due_at="2027-06-01T00:00:00Z",
    )
    assert_status(assessment, "CONDITIONS_ISSUED")
    current_policy = X.read_policy(api, policy["id"])

    response = api.issue_renewal_quote(
        assessment["id"],
        F.issue_renewal_quote_payload(current_policy["version"]),
        ACTUARY_HEADERS,
    )
    validate_error(response, ErrorId.INVALID_ASSESSMENT_STATE)

    after = data_of(api.get_renewal_assessment(assessment["id"], UNDERWRITER_HEADERS))
    assert_status(after, "CONDITIONS_ISSUED")
    assert after["loss_ratio"] is None
    assert after["renewal_premium_usd"] is None
    assert after["premium_adjustment_pct"] is None


def test_declined_application_cannot_be_quoted(api):
    """PRD §3.2: "Attempting any transition from a state where that transition is
    not declared, or any transition at all out of a terminal state, is rejected
    with `ERR_INVALID_APPLICATION_STATE`."

    PRD §3.5: "The `declined_reason` supplied by the underwriter is stored
    verbatim, `premium_usd` is cleared to null, and — when the application was
    sitting in `REMEDIATION_REQUIRED` — the owning account's
    `open_remediation_count` is decremented by 1."

    Design: Corner/state_machines/declined_application_cannot_be_quoted
    """
    X.seed_catalog(api)
    account = X.create_account(api)
    application = X.create_application(api, account["id"])
    X.attest_controls(api, application["id"], C.ATTEST_95)
    X.submit_application(api, application["id"])
    scan = X.order_scan(api, application["id"])
    X.complete_scan(api, scan["id"], findings=STANDARD_SCAN_FINDINGS)
    declined = data_of(
        api.decline_application(
            application["id"], F.decline_payload("APPETITE"), UNDERWRITER_HEADERS
        )
    )
    assert_status(declined, "DECLINED")

    response = api.quote_application(
        application["id"], F.quote_payload(declined["version"]), UNDERWRITER_HEADERS
    )
    validate_error(response, ErrorId.INVALID_APPLICATION_STATE)

    after = X.read_application(api, application["id"])
    assert_status(after, "DECLINED")
    assert after["premium_usd"] is None
    assert (
        get_total_count(
            api.list_policies(
                UNDERWRITER_HEADERS, params={"application_id": application["id"]}
            )
        )
        == 0
    )


def test_settled_claim_cannot_be_denied(api):
    """PRD §3.6: "Any transition not declared for the claim's current state, and
    any attempt to act on a terminal claim at all, is refused with
    `ERR_INVALID_CLAIM_STATE`."

    PRD §3.8: "Because the claim was approved, the tower waterfall runs over
    `assessed_indemnity_usd` with a `loss_source` of `PROOF_OF_LOSS`, creating one
    payment row per eroded section, updating the claim's `retention_absorbed_usd`,
    `paid_total_usd`, and `unallocated_loss_usd`, zeroing `reserved_amount_usd` to
    0.00, and moving the claim on to `SETTLED`."

    Design: Corner/state_machines/settled_claim_cannot_be_denied
    """
    _chain, claim, _proof = _settled_claim(api)
    settled = X.read_claim(api, claim["id"])
    assert_status(settled, "SETTLED")

    response = api.deny_incident_claim(
        claim["id"], F.deny_claim_payload("PROOF_INSUFFICIENT"), ADJUSTER_2_HEADERS
    )
    validate_error(response, ErrorId.INVALID_CLAIM_STATE)

    after = X.read_claim(api, claim["id"])
    assert_status(after, "SETTLED")
    assert after["denial_reason"] is None
    # 300,000 assessed indemnity, 250,000 retention off the top, 50,000 into the
    # business interruption section less its 10 per cent coinsurance.
    assert_money(after["paid_total_usd"], 45000.00, "paid_total_usd")
    assert_money(
        after["retention_absorbed_usd"], 250000.00, "retention_absorbed_usd"
    )

    payments = get_rows(
        api.list_claim_payments(
            ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
        )
    )
    assert len(payments) == 1
    assert_status(payments[0], "POSTED", field="payment_status")


def test_completed_engagement_cannot_log_further_hours(api):
    """PRD §3.7: "Logging against an engagement that has reached `COMPLETED` or
    `TERMINATED` is refused with `ERR_INVALID_ENGAGEMENT_STATE`."

    PRD §3.7: "The firm's `active_engagement_count` is decremented by 1 and its
    `version` incremented by 1, the section and policy remaining figures and
    `limit_status` are updated exactly as on the payment cascade, and the
    engagement's `version` is incremented by 1."

    Design: Corner/state_machines/completed_engagement_cannot_log_further_hours
    """
    _chain, claim = _confirmed_ransomware_claim(api)
    vendor = _forensics_vendor(api)
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
    X.complete_engagement(api, engagement["id"])

    response = api.log_engagement_hours(
        engagement["id"], F.log_hours_payload(hours=1), ADJUSTER_HEADERS
    )
    validate_error(response, ErrorId.INVALID_ENGAGEMENT_STATE)

    after = data_of(api.get_vendor_engagement(engagement["id"], ADJUSTER_HEADERS))
    assert_status(after, "COMPLETED")
    assert after["incurred_hours"] == 4
    assert_money(after["incurred_amount_usd"], 2000.00, "incurred_amount_usd")

    firm = data_of(api.get_panel_vendor(vendor["id"], UNDERWRITER_HEADERS))
    assert firm["active_engagement_count"] == 0


def test_completing_the_same_scan_twice_is_refused(api):
    """PRD §3.3: "The scan must be in `PENDING`; a second result on the same scan
    is refused with `ERR_INVALID_SCAN_STATE`."

    PRD §3.3: "Both outcomes stamp `completed_at` from the logical clock and
    increment the scan's `version` by 1, and both are terminal for the scan."

    PRD §3.3: "The completion also computes `critical_finding_count`, the number
    of `findings` entries whose `severity` is `CRITICAL`, which starts at 0 when
    nothing critical was seen."

    Design: Corner/state_machines/completing_the_same_scan_twice_returns_invalid_scan_state
    """
    X.seed_catalog(api)
    account = X.create_account(api)
    application = X.create_application(api, account["id"])
    X.attest_controls(api, application["id"], C.ATTEST_95)
    X.submit_application(api, application["id"])
    scan = X.order_scan(api, application["id"])
    X.complete_scan(api, scan["id"], findings=STANDARD_SCAN_FINDINGS)

    response = api.complete_external_scan(
        scan["id"],
        F.scan_complete_payload(
            findings=[F.scan_finding("MFA_PRIVILEGED", "CRITICAL", "NONE")]
        ),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, ErrorId.INVALID_SCAN_STATE)

    after_scan = data_of(api.get_external_scan(scan["id"], UNDERWRITER_HEADERS))
    assert after_scan["critical_finding_count"] == 0

    after = X.read_application(api, application["id"])
    assert_score_2dp(after["verified_control_score"], 87.50, "verified_control_score")
    assert after["mandatory_gap_count"] == 0
    assert_status(after, "UNDERWRITING")

    owner = data_of(api.get_insured_account(account["id"], UNDERWRITER_HEADERS))
    assert owner["open_remediation_count"] == 0


def test_cancelling_the_same_policy_twice_is_refused(api):
    """PRD §3.6: "**Cancellation.** An `Underwriter` cancels an `INFORCE` policy
    mid-term, supplying a `cancellation_reason`; cancelling a policy that is not
    `INFORCE` — a second cancellation, for instance — is refused with
    `ERR_INVALID_POLICY_STATE`."

    PRD §3.6: "`lifecycle_status` becomes `CANCELLED`, `cancelled_at` is stamped
    from the logical clock, and `cancellation_reason` is stored."

    PRD §3.5: "The policy carries **two independent state dimensions**, and
    neither constrains the other."

    Design: Corner/state_machines/cancelling_the_same_policy_twice_returns_invalid_policy_state
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]
    X.set_clock(api, "2026-09-10T00:00:00Z")
    cancelled = data_of(
        api.cancel_policy(
            policy["id"], F.cancel_policy_payload("NON_PAYMENT"), UNDERWRITER_HEADERS
        )
    )
    assert_status(cancelled, "CANCELLED", field="lifecycle_status")

    response = api.cancel_policy(
        policy["id"],
        F.cancel_policy_payload("UNDERWRITING_DECISION"),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, ErrorId.INVALID_POLICY_STATE)

    after = X.read_policy(api, policy["id"])
    assert_status(after, "CANCELLED", field="lifecycle_status")
    assert_instant(after["cancelled_at"], "2026-09-10T00:00:00Z", "cancelled_at")
    assert after["cancellation_reason"] == "NON_PAYMENT"
    assert_status(after, "INTACT", field="limit_status")


def test_reversing_the_same_payment_twice_is_refused(api):
    """PRD §3.8: "The row must be in `POSTED`; a row already `REVERSED` is
    refused with `ERR_INVALID_PAYMENT_STATE`."

    PRD §3.8: "On the claim, `paid_total_usd` is decreased by `net_paid_usd`,
    `retention_absorbed_usd` is decreased by `retention_applied_usd`, and
    `unallocated_loss_usd` is reset to 0.00; a claim that had reached `SETTLED`
    returns to `APPROVED_FOR_PAYMENT`."

    PRD §3.8: "Reversed rows never re-enter the ledger."

    Design: Corner/state_machines/reversing_the_same_payment_twice_returns_invalid_payment_state
    """
    chain, claim, _proof = _settled_claim(api)
    payments = get_rows(
        api.list_claim_payments(
            ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
        )
    )
    assert len(payments) == 1
    payment = payments[0]
    reversed_row = data_of(
        api.reverse_claim_payment(
            payment["id"],
            F.reverse_payment_payload("DUPLICATE_POSTING"),
            ADJUSTER_2_HEADERS,
        )
    )
    assert_status(reversed_row, "REVERSED", field="payment_status")

    response = api.reverse_claim_payment(
        payment["id"], F.reverse_payment_payload("SECOND_ATTEMPT"), ADJUSTER_2_HEADERS
    )
    validate_error(response, ErrorId.INVALID_PAYMENT_STATE)

    after_payment = data_of(api.get_claim_payment(payment["id"], ADJUSTER_HEADERS))
    assert_status(after_payment, "REVERSED", field="payment_status")
    assert after_payment["reversal_reason"] == "DUPLICATE_POSTING"

    after_policy = X.read_policy(api, chain["policy"]["id"])
    assert_money(
        after_policy["aggregate_limit_remaining_usd"],
        5000000.00,
        "aggregate_limit_remaining_usd",
    )
    assert_status(after_policy, "INTACT", field="limit_status")

    after_claim = X.read_claim(api, claim["id"])
    assert_money(after_claim["paid_total_usd"], 0.00, "paid_total_usd")
    assert_status(after_claim, "APPROVED_FOR_PAYMENT")


def test_warranty_report_lapses_the_policy_and_a_clean_report_restores_it(api):
    """PRD §3.6: "The report rewrites `lapsed_warranty_control_keys`, sorted
    `control_key` ascending, and recomputes `warranty_status`, which reads
    `COMPLIANT` while the lapsed list is empty and `LAPSED` otherwise."

    PRD §3.6: "The policy's `version` is incremented by 1."

    PRD §3.6: "A `LAPSED` policy is still in force and still receives
    notifications, but two operations are barred while it stays lapsed — coverage
    confirmation on a claim and issuance of a renewal quote — each refused with
    `ERR_MANDATORY_CONTROL_LAPSE`."

    Design: Corner/state_machines/warranty_report_lapses_the_policy_and_a_clean_report_restores_it
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]
    version_at_bind = policy["version"]
    X.set_clock(api, "2026-09-10T00:00:00Z")

    lapse = api.create_warranty_report(
        policy["id"],
        F.warranty_report_payload(["OFFLINE_BACKUPS", "MFA_PRIVILEGED"]),
        UNDERWRITER_HEADERS,
    )
    assert lapse.status_code in (200, 201), lapse.text

    lapsed = X.read_policy(api, policy["id"])
    assert_status(lapsed, "LAPSED", field="warranty_status")
    assert lapsed["lapsed_warranty_control_keys"] == [
        "MFA_PRIVILEGED",
        "OFFLINE_BACKUPS",
    ]
    assert_status(lapsed, "INFORCE", field="lifecycle_status")
    assert_status(lapsed, "INTACT", field="limit_status")

    clean = api.create_warranty_report(
        policy["id"], F.warranty_report_payload([]), UNDERWRITER_HEADERS
    )
    assert clean.status_code in (200, 201), clean.text

    restored = X.read_policy(api, policy["id"])
    assert_status(restored, "COMPLIANT", field="warranty_status")
    assert restored["lapsed_warranty_control_keys"] == []
    assert restored["version"] == version_at_bind + 2
    assert_status(restored, "INFORCE", field="lifecycle_status")
    assert_status(restored, "INTACT", field="limit_status")


def test_warranty_keys_pinned_at_bind_survive_a_later_catalog_addition(api):
    """PRD §3.5: "`warranty_control_keys` is pinned to the set of catalog keys
    whose `is_mandatory` is true at that instant, and later catalog edits never
    disturb the snapshot."

    PRD §3.1: "Permanence has a consequence worth stating plainly: because the
    posture score's denominator is the sum of *every* catalog weight, adding a
    control changes the denominator of every score computed from that moment on,
    and adding a mandatory control can open a gap on an application that had
    none."

    Design: Corner/state_machines/warranty_keys_pinned_at_bind_survive_a_later_catalog_addition
    """
    # `control_key` is drawn from a fixed vocabulary of five controls (PRD §3.1),
    # so the catalog addition made after the bind has to be one of those five:
    # the policy is bound against a four-row catalog and INCIDENT_RESPONSE_PLAN
    # is catalogued as mandatory afterwards.
    catalog_rows = [
        row for row in C.STANDARD_CATALOG if row["control_key"] != "INCIDENT_RESPONSE_PLAN"
    ]
    attestations = {
        key: level
        for key, level in C.ATTEST_95.items()
        if key != "INCIDENT_RESPONSE_PLAN"
    }
    chain = X.bound_policy(
        api,
        attestations=attestations,
        catalog_rows=catalog_rows,
        findings=STANDARD_SCAN_FINDINGS,
    )
    policy = chain["policy"]
    version_at_bind = policy["version"]

    data_of(
        api.create_control_requirement(
            F.control_requirement_payload(
                control_key="INCIDENT_RESPONSE_PLAN",
                min_level_required="FULL",
                weight=20,
                is_mandatory=True,
            ),
            UNDERWRITER_HEADERS,
        ),
        201,
    )

    assert get_total_count(api.list_control_requirements(UNDERWRITER_HEADERS)) == 5

    after = X.read_policy(api, policy["id"])
    assert sorted(after["warranty_control_keys"]) == sorted(C.MANDATORY_CONTROL_KEYS)
    assert "INCIDENT_RESPONSE_PLAN" not in after["warranty_control_keys"]
    assert_status(after, "COMPLIANT", field="warranty_status")
    assert after["version"] == version_at_bind


def test_policy_cancellation_spares_claims_already_in_proof_review(api):
    """PRD §3.6: "Because the policy was cancelled, every incident claim on it
    whose `status` is `NOTIFIED`, `TRIAGE`, `COVERAGE_CONFIRMED`, or
    `RESPONSE_ACTIVE` moves to `CLOSED_NO_COVERAGE` with `reserved_amount_usd`
    zeroed to 0.00 and its `version` incremented by 1."

    PRD §3.6: "Claims that have already reached `PROOF_REVIEW` or gone beyond it
    — `INFO_REQUESTED`, `APPROVED_FOR_PAYMENT`, `SETTLED`, `DENIED` — are left
    entirely untouched, because the indemnity determination on those files is
    already under way."

    PRD §3.6: "Because those claims closed, each of their vendor engagements
    whose `status` is `AUTHORIZED` or `ACTIVE` moves to `TERMINATED`."

    PRD §3.6: "Because those engagements terminated, each affected panel firm's
    `active_engagement_count` is decremented once per terminated engagement and
    its `version` is incremented."

    Design: Corner/state_machines/policy_cancellation_spares_claims_already_in_proof_review
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]
    X.set_clock(api, "2026-09-10T00:00:00Z")
    vendor = X.create_vendor(
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
        headers=PANEL_ADMIN_HEADERS,
    )

    notified_claim = X.notify_claim(
        api,
        policy["id"],
        incident_type="BEC",
        incident_discovered_at="2026-09-05T00:00:00Z",
    )
    triaged_claim = X.notify_claim(
        api,
        policy["id"],
        incident_type="DATA_THEFT",
        incident_discovered_at="2026-09-05T00:00:00Z",
    )
    X.triage_claim(api, triaged_claim["id"])
    responding_claim = X.confirmed_claim(
        api,
        policy["id"],
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=100000,
        **RANSOMWARE_CLAIM,
    )
    engagement = X.authorize_engagement(
        api,
        responding_claim["id"],
        vendor_type="LEGAL_COUNSEL",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=100,
        panel_vendor_id=vendor["id"],
    )
    proof_claim = X.confirmed_claim(
        api,
        policy["id"],
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
        **RANSOMWARE_CLAIM,
    )
    proof = X.file_proof(
        api,
        proof_claim["id"],
        claimed_bi_loss_usd=300000,
        gross_profit_margin_pct=1.0,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    assert_status(X.read_claim(api, proof_claim["id"]), "PROOF_REVIEW")

    cancelled = data_of(
        api.cancel_policy(
            policy["id"],
            F.cancel_policy_payload("MATERIAL_MISREPRESENTATION"),
            UNDERWRITER_HEADERS,
        )
    )

    assert_status(cancelled, "CANCELLED", field="lifecycle_status")
    assert_instant(cancelled["cancelled_at"], "2026-09-10T00:00:00Z", "cancelled_at")

    for closed_id in (
        notified_claim["id"],
        triaged_claim["id"],
        responding_claim["id"],
    ):
        closed = X.read_claim(api, closed_id)
        assert_status(closed, "CLOSED_NO_COVERAGE")
        assert_money(closed["reserved_amount_usd"], 0.00, "reserved_amount_usd")

    spared = X.read_claim(api, proof_claim["id"])
    assert_status(spared, "PROOF_REVIEW")
    assert_money(spared["reserved_amount_usd"], 300000.00, "reserved_amount_usd")

    assert_status(
        data_of(api.get_vendor_engagement(engagement["id"], ADJUSTER_HEADERS)),
        "TERMINATED",
    )
    firm = data_of(api.get_panel_vendor(vendor["id"], UNDERWRITER_HEADERS))
    assert firm["active_engagement_count"] == 0
    assert_status(
        data_of(api.get_proof_of_loss(proof["id"], ADJUSTER_HEADERS)), "UNDER_REVIEW"
    )


def test_run_epoch_expires_a_quote_at_its_expiry_instant(api):
    """PRD §3.5: "A quote left unbound does not linger indefinitely: when the
    epoch sweep runs at or after `quote_expires_at`, a `QUOTED` application moves
    to `EXPIRED` with `premium_usd` cleared to null and its `version` incremented
    by 1."

    PRD §2.5: "Its response reports `expired_application_count`,
    `expired_policy_count`, `non_renewed_assessment_count`, and `run_at`."

    Design: Corner/state_machines/run_epoch_expires_a_quote_exactly_at_its_expiry_instant
    """
    chain = X.quoted_application(api, findings=STANDARD_SCAN_FINDINGS)
    quoted = chain["application"]
    assert_instant(
        quoted["quote_expires_at"], "2026-08-31T00:00:00Z", "quote_expires_at"
    )

    X.set_clock(api, "2026-08-31T00:00:00Z")
    sweep = data_of(api.run_epoch(UNDERWRITER_HEADERS))

    assert sweep["expired_application_count"] == 1
    assert sweep["expired_policy_count"] == 0
    assert sweep["non_renewed_assessment_count"] == 0
    assert_instant(sweep["run_at"], "2026-08-31T00:00:00Z", "run_at")

    after = X.read_application(api, quoted["id"])
    assert_status(after, "EXPIRED")
    assert after["premium_usd"] is None
    assert_instant(
        after["quote_expires_at"], "2026-08-31T00:00:00Z", "quote_expires_at"
    )
    assert after["quoted_by_user_id"] == UNDERWRITER_1
    assert after["version"] == quoted["version"] + 1


def test_run_epoch_non_renews_an_assessment_past_its_remediation_deadline(api):
    """PRD §3.9: "A second path to non-renewal is temporal: when the epoch sweep
    runs at or after an assessment's `remediation_due_at` and the assessment is
    still sitting in `CONDITIONS_ISSUED`, it moves to `NON_RENEWED` with
    `non_renewal_reason` recorded as `REMEDIATION_DEADLINE_MISSED`, the policy's
    `lifecycle_status` becomes `NON_RENEWED`, and the assessment's `version` is
    incremented by 1."

    PRD §3.5: "The policy carries **two independent state dimensions**, and
    neither constrains the other."

    Design: Corner/state_machines/run_epoch_non_renews_an_assessment_past_its_remediation_deadline
    """
    chain = X.bound_policy(api, findings=STANDARD_SCAN_FINDINGS)
    policy = chain["policy"]
    X.set_clock(api, "2027-05-05T00:00:00Z")
    assessment = X.open_renewal_assessment(
        api,
        policy["id"],
        required_control_keys=["EMAIL_FILTERING"],
        remediation_due_at="2027-06-01T00:00:00Z",
    )
    assert_status(assessment, "CONDITIONS_ISSUED")

    X.set_clock(api, "2027-06-01T00:00:00Z")
    sweep = data_of(api.run_epoch(UNDERWRITER_HEADERS))

    assert sweep["non_renewed_assessment_count"] == 1
    assert sweep["expired_policy_count"] == 0
    assert sweep["expired_application_count"] == 0

    after = data_of(api.get_renewal_assessment(assessment["id"], UNDERWRITER_HEADERS))
    assert_status(after, "NON_RENEWED")
    assert after["non_renewal_reason"] == "REMEDIATION_DEADLINE_MISSED"
    assert after["verified_control_keys"] == []
    assert after["renewal_premium_usd"] is None

    after_policy = X.read_policy(api, policy["id"])
    assert_status(after_policy, "NON_RENEWED", field="lifecycle_status")
    assert_status(after_policy, "INTACT", field="limit_status")
    assert_money(
        after_policy["aggregate_limit_remaining_usd"],
        5000000.00,
        "aggregate_limit_remaining_usd",
    )


def test_request_info_moves_proof_and_claim_together_and_advances_the_round(api):
    """PRD §3.8: "The proof moves from `UNDER_REVIEW` to `INFO_REQUESTED`, the
    claim moves from `PROOF_REVIEW` to `INFO_REQUESTED`, the note is stored, the
    claim's `proof_review_round` is incremented by 1, and both the proof's and the
    claim's `version` are incremented by 1."

    PRD §3.8: "The proof moves from `UNDER_REVIEW` to `ACCEPTED` with
    `baseline_method_applied`, `outage_hours`, `compensable_hours`, and every
    quantification component written, and its `version` incremented by 1."

    Design: Corner/state_machines/request_info_advances_the_round_and_moves_proof_and_claim_together
    """
    _chain, claim = _confirmed_ransomware_claim(api)
    proof = X.file_proof(
        api,
        claim["id"],
        claimed_bi_loss_usd=300000,
        gross_profit_margin_pct=1.0,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    assert_status(proof, "UNDER_REVIEW")

    returned = X.request_info(
        api,
        proof["id"],
        note="PROVIDE_SIGNED_HOURLY_REVENUE_WORKPAPERS",
        headers=ADJUSTER_2_HEADERS,
    )

    assert_status(returned, "INFO_REQUESTED")
    assert returned["info_request_note"] == "PROVIDE_SIGNED_HOURLY_REVENUE_WORKPAPERS"
    # Nothing is quantified until the proof is accepted.
    assert returned["assessed_indemnity_usd"] is None

    after_claim = X.read_claim(api, claim["id"])
    assert_status(after_claim, "INFO_REQUESTED")
    assert after_claim["proof_review_round"] == 1
