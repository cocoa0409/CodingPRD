"""Validation corner cases on the claims, panel and renewal side of the file.

Every test builds the whole world it needs from scratch through the public API:
the control catalog, the insured account, the application, the bound policy and
whatever claim, engagement or proof the rule under test needs. The harness
restarts the server with an empty database before each test.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADJUSTER_2_HEADERS,
    ADJUSTER_HEADERS,
    PANEL_ADMIN_HEADERS,
    UNDERWRITER_HEADERS,
    ErrorId,
    constants as C,
    factories as F,
    fixtures,
)
from test_helpers.assertions import (
    assert_money,
    data_of,
    find_row,
    get_rows,
    get_total_count,
)

# The scan contradicts the applicant on one control only: EMAIL_FILTERING is
# attested FULL but observed PARTIAL, so the verified basis lands on 87.50.
EMAIL_FILTERING_PARTIAL = [F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")]

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2027-08-01T00:00:00Z"

IRONCLAD_FORENSICS = {
    "vendor_name": "Ironclad Forensics",
    "vendor_type": "FORENSICS",
    "pre_approved_hourly_rate_usd": 500,
    "per_record_notification_rate_usd": 0,
    "specialty_sectors": ["HEALTHCARE", "FINANCIAL"],
    "tier": 1,
    "capacity_concurrent_engagements": 1,
}

HOSTAGE_DESK = {
    "vendor_name": "Hostage Desk",
    "vendor_type": "RANSOM_NEGOTIATION",
    "pre_approved_hourly_rate_usd": 500,
    "per_record_notification_rate_usd": 0,
    "specialty_sectors": ["HEALTHCARE"],
    "tier": 1,
    "capacity_concurrent_engagements": 2,
}

# Bitwise Systems attests one mandatory control at its floor rather than above
# it, which still clears the 70.00 minimum and opens no mandatory gap.
ATTEST_BITWISE = {
    "MFA_PRIVILEGED": "FULL",
    "OFFLINE_BACKUPS": "FULL",
    "EDR_COVERAGE": "PARTIAL",
    "EMAIL_FILTERING": "PARTIAL",
    "INCIDENT_RESPONSE_PLAN": "PARTIAL",
}


def _instant(value):
    """Parse an ISO 8601 UTC instant so equal times compare equal."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _aurora_policy(
    api,
    dependent_bi_definition="NAMED_PLUS_SUPPLY_CHAIN",
    named_dependency_keys=("CSP_ALPHA",),
    coverage_sections=None,
):
    """Catalog, Aurora Health, application, quote, and the five-section tower."""
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    chain = fixtures.quoted_application(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        findings=EMAIL_FILTERING_PARTIAL,
        dependent_bi_definition=dependent_bi_definition,
    )
    chain["policy"] = fixtures.bind_application(
        api,
        chain["application"]["id"],
        coverage_sections=coverage_sections
        if coverage_sections is not None
        else C.STANDARD_TOWER,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        named_dependency_keys=list(named_dependency_keys),
    )
    chain["sections"] = {
        row["section_key"]: row
        for row in get_rows(
            api.list_policy_coverage_sections(chain["policy"]["id"], UNDERWRITER_HEADERS)
        )
    }
    return chain


def test_directed_rate_above_the_pre_approved_rate_is_refused(api):
    """PRD §3.7: "A directed authorisation may also supply `directed_rate_usd`, which must not exceed the firm's `pre_approved_hourly_rate_usd`; a higher figure is refused with `ERR_RATE_EXCEEDS_PRE_APPROVED`."

    Design: Corner/validations/directed_rate_above_the_pre_approved_rate_returns_422
    """
    chain = _aurora_policy(api)
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    claim = fixtures.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    vendor = fixtures.create_vendor(api, IRONCLAD_FORENSICS)

    response = api.create_vendor_engagement(
        claim["id"],
        F.vendor_engagement_payload(
            vendor_type="FORENSICS",
            deployment_start_at="2026-09-10T00:00:00Z",
            deployment_end_at="2026-09-12T00:00:00Z",
            authorized_hours_cap=40,
            panel_vendor_id=vendor["id"],
            directed_rate_usd=600,
        ),
        ADJUSTER_HEADERS,
    )
    validate_error(response, ErrorId.RATE_EXCEEDS_PRE_APPROVED)

    assert (
        get_total_count(
            api.list_vendor_engagements(
                ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
            )
        )
        == 0
    ), "a refused authorisation must create no engagement"

    firm = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert firm["active_engagement_count"] == 0, (
        f"the firm must stay idle: {firm['active_engagement_count']}"
    )
    assert firm["version"] == 1, f"the firm's version moved to {firm['version']}"

    after = fixtures.read_claim(api, claim["id"])
    assert after["status"] == "COVERAGE_CONFIRMED", (
        f"claim status drifted to {after['status']}"
    )


def test_incident_discovered_before_the_period_start_is_refused(api):
    """PRD §3.6: "`incident_discovered_at` must fall inside the half-open policy period — at or after `period_start` and strictly before `period_end` — or the notification is refused with `ERR_INCIDENT_OUTSIDE_POLICY_PERIOD`."

    Design: Corner/validations/incident_discovered_before_the_period_start_returns_422
    """
    chain = _aurora_policy(api)
    fixtures.set_clock(api, "2026-08-02T00:00:00Z")

    # One second before the policy incepted, and only one day of reporting delay,
    # so lateness has nothing to say about this notification.
    response = api.create_incident_claim(
        F.incident_claim_payload(
            chain["policy"]["id"],
            incident_type="RANSOMWARE",
            incident_discovered_at="2026-07-31T23:59:59Z",
            outage_start_at="2026-07-31T23:59:59Z",
            outage_end_at="2026-08-01T23:59:59Z",
        ),
        ADJUSTER_HEADERS,
    )
    validate_error(response, ErrorId.INCIDENT_OUTSIDE_POLICY_PERIOD)

    assert (
        get_total_count(
            api.list_incident_claims(
                ADJUSTER_HEADERS, params={"policy_id": chain["policy"]["id"]}
            )
        )
        == 0
    ), "a refused notification must create no claim"


def test_notification_thirty_one_days_after_discovery_is_refused(api):
    """PRD §3.6: "And the notification must be timely: `notified_at` is stamped from the logical clock at acceptance, and the elapsed time from `incident_discovered_at` to `notified_at` must be no more than 30 days, a longer delay yielding `ERR_LATE_NOTIFICATION`."

    Design: Corner/validations/notification_thirty_one_days_after_discovery_returns_422
    """
    chain = _aurora_policy(api)

    # Discovery sits comfortably inside the policy period; only the delay is bad.
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")
    response = api.create_incident_claim(
        F.incident_claim_payload(
            chain["policy"]["id"],
            incident_type="RANSOMWARE",
            incident_discovered_at="2026-08-05T00:00:00Z",
            outage_start_at="2026-08-05T00:00:00Z",
            outage_end_at="2026-08-08T00:00:00Z",
        ),
        ADJUSTER_HEADERS,
    )
    validate_error(response, ErrorId.LATE_NOTIFICATION)

    assert (
        get_total_count(
            api.list_incident_claims(
                ADJUSTER_HEADERS, params={"policy_id": chain["policy"]["id"]}
            )
        )
        == 0
    ), "a refused notification must create no claim"


def test_claim_notified_on_the_thirtieth_day_is_accepted(api):
    """PRD §3.6: "And the notification must be timely: `notified_at` is stamped from the logical clock at acceptance, and the elapsed time from `incident_discovered_at` to `notified_at` must be no more than 30 days, a longer delay yielding `ERR_LATE_NOTIFICATION`."
    PRD §3.6: "The claim opens in `NOTIFIED` with `reserved_amount_usd`, `retention_absorbed_usd`, `paid_total_usd`, and `unallocated_loss_usd` all at 0.00 and `proof_review_round` at 0."

    Design: Corner/validations/claim_notified_on_the_thirtieth_day_is_accepted
    """
    chain = _aurora_policy(api)

    # Exactly 30 days after discovery: the boundary is inclusive.
    fixtures.set_clock(api, "2026-09-04T00:00:00Z")
    response = api.create_incident_claim(
        F.incident_claim_payload(
            chain["policy"]["id"],
            incident_type="RANSOMWARE",
            incident_discovered_at="2026-08-05T00:00:00Z",
            outage_start_at="2026-08-05T00:00:00Z",
            outage_end_at="2026-08-08T00:00:00Z",
        ),
        ADJUSTER_HEADERS,
    )
    validate_success(response, expected_status=201)
    claim = data_of(response, expected_status=201)

    assert claim["status"] == "NOTIFIED", f"unexpected opening status {claim['status']}"
    assert _instant(claim["notified_at"]) == _instant("2026-09-04T00:00:00Z"), (
        f"notified_at must come from the clock: {claim['notified_at']}"
    )
    assert claim["dependency_key"] == "NONE", (
        f"dependency_key must default to NONE: {claim['dependency_key']}"
    )
    assert claim["affected_record_count"] == 0, (
        f"affected_record_count must default to 0: {claim['affected_record_count']}"
    )
    assert_money(claim["reserved_amount_usd"], 0.00, "reserved_amount_usd")
    assert_money(claim["retention_absorbed_usd"], 0.00, "retention_absorbed_usd")
    assert_money(claim["paid_total_usd"], 0.00, "paid_total_usd")
    assert_money(claim["unallocated_loss_usd"], 0.00, "unallocated_loss_usd")
    assert claim["proof_review_round"] == 0, (
        f"proof_review_round must open at 0: {claim['proof_review_round']}"
    )
    assert claim["version"] == 1, f"a new claim opens at version 1: {claim['version']}"


def test_renewal_assessment_opened_one_day_early_is_refused(api):
    """PRD §3.9: "An `Underwriter` opens a renewal assessment against a policy inside the renewal window, which begins 90 days before the policy's `period_end`: an assessment opened while the clock is still earlier than `period_end` less 90 days is refused with `ERR_RENEWAL_WINDOW_NOT_OPEN`."

    Design: Corner/validations/renewal_assessment_opened_one_day_early_returns_422
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]

    # The period ends 2027-08-01, so the window opens 2027-05-03.
    fixtures.set_clock(api, "2027-05-02T00:00:00Z")
    response = api.create_renewal_assessment(
        policy["id"],
        F.renewal_assessment_payload(
            required_control_keys=["EMAIL_FILTERING"],
            remediation_due_at="2027-06-01T00:00:00Z",
        ),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, ErrorId.RENEWAL_WINDOW_NOT_OPEN)

    assert (
        get_total_count(
            api.list_renewal_assessments(
                UNDERWRITER_HEADERS, params={"policy_id": policy["id"]}
            )
        )
        == 0
    ), "a refused opening must create no assessment"

    after = fixtures.read_policy(api, policy["id"])
    assert after["lifecycle_status"] == "INFORCE", (
        f"policy lifecycle drifted to {after['lifecycle_status']}"
    )
    assert after["version"] == policy["version"], (
        f"version moved from {policy['version']} to {after['version']}"
    )


def test_dependent_outage_outside_the_named_dependency_list_is_refused(api):
    """PRD §3.6: "A `DEPENDENT_OUTAGE` additionally requires that the policy tower actually contains a `DEPENDENT_BI` section, and, when the policy's `dependent_bi_definition` is `NAMED_ONLY`, that the claim's `dependency_key` appears among the policy's `named_dependency_keys`; a broader definition of `NAMED_PLUS_SUPPLY_CHAIN` or `BROAD_SYSTEM_FAILURE` responds without the dependency having been scheduled by name."
    PRD §3.6: "Failure here is `ERR_DEPENDENT_BI_NOT_COVERED`."

    Design: Corner/validations/dependent_outage_outside_the_named_dependency_list_returns_422
    """
    chain = _aurora_policy(
        api,
        dependent_bi_definition="NAMED_ONLY",
        named_dependency_keys=("CSP_ALPHA",),
    )
    policy = chain["policy"]
    assert policy["dependent_bi_definition"] == "NAMED_ONLY", (
        f"unexpected wording {policy['dependent_bi_definition']}"
    )
    assert policy["named_dependency_keys"] == ["CSP_ALPHA"], (
        f"unexpected schedule {policy['named_dependency_keys']}"
    )
    assert "DEPENDENT_BI" in chain["sections"], "the tower must carry a DEPENDENT_BI section"

    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    response = api.create_incident_claim(
        F.incident_claim_payload(
            policy["id"],
            incident_type="DEPENDENT_OUTAGE",
            incident_discovered_at="2026-09-05T00:00:00Z",
            dependency_key="CSP_BETA",
            outage_start_at="2026-09-05T00:00:00Z",
            outage_end_at="2026-09-08T00:00:00Z",
        ),
        ADJUSTER_HEADERS,
    )
    validate_error(response, ErrorId.DEPENDENT_BI_NOT_COVERED)

    assert (
        get_total_count(
            api.list_incident_claims(ADJUSTER_HEADERS, params={"policy_id": policy["id"]})
        )
        == 0
    ), "a refused notification must create no claim"


def test_ransom_negotiation_cost_with_no_extortion_section_is_refused(api):
    """PRD §3.7: "That mapping is fixed: `FORENSICS`, `NOTIFICATION`, and `PR_CRISIS` costs are eligible against `FIRST_PARTY_RESPONSE` only; `LEGAL_COUNSEL` costs are eligible against `FIRST_PARTY_RESPONSE` and `THIRD_PARTY_LIABILITY`; and `RANSOM_NEGOTIATION` costs are eligible against `CYBER_EXTORTION` only."
    PRD §3.8: "In either case the eligible set is intersected with the claim's `covered_section_keys`, and if that intersection is empty the allocation fails with `ERR_NO_ELIGIBLE_COVERAGE_SECTION`."

    Design: Corner/validations/ransom_negotiation_cost_with_no_extortion_section_confirmed_returns_422
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")

    # The tower carries CYBER_EXTORTION, but the adjuster did not confirm it.
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
    vendor = fixtures.create_vendor(api, HOSTAGE_DESK)
    engagement = fixtures.authorize_engagement(
        api,
        claim["id"],
        vendor_type="RANSOM_NEGOTIATION",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
    )
    fixtures.log_hours(api, engagement["id"], hours=20)

    response = api.complete_vendor_engagement(engagement["id"], ADJUSTER_HEADERS)
    validate_error(response, ErrorId.NO_ELIGIBLE_COVERAGE_SECTION)

    after_engagement = data_of(api.get_vendor_engagement(engagement["id"], ADJUSTER_HEADERS))
    assert after_engagement["status"] == "ACTIVE", (
        f"a refused completion must leave the engagement ACTIVE, got {after_engagement['status']}"
    )
    assert_money(after_engagement["incurred_amount_usd"], 10000.00, "incurred_amount_usd")

    assert (
        get_total_count(
            api.list_claim_payments(
                ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]}
            )
        )
        == 0
    ), "no payment row may be posted by a refused completion"

    after_policy = fixtures.read_policy(api, policy["id"])
    assert_money(
        after_policy["aggregate_limit_remaining_usd"], 5000000.00, "aggregate_limit_remaining_usd"
    )
    extortion = find_row(
        get_rows(api.list_policy_coverage_sections(policy["id"], UNDERWRITER_HEADERS)),
        section_key="CYBER_EXTORTION",
    )
    assert_money(extortion["sublimit_remaining_usd"], 500000.00, "sublimit_remaining_usd")

    firm = data_of(api.get_panel_vendor(vendor["id"], PANEL_ADMIN_HEADERS))
    assert firm["active_engagement_count"] == 1, (
        f"the engagement is still open, so the firm stays busy: {firm['active_engagement_count']}"
    )


def test_cumulative_hours_above_the_authorized_cap_are_refused(api):
    """PRD §3.7: "Cumulative hours are capped: the engagement's `incurred_hours` after adding the increment must not exceed `authorized_hours_cap`, and a log that would breach the cap is refused with `ERR_AUTHORIZED_HOURS_EXCEEDED` and changes nothing."

    Design: Corner/validations/cumulative_hours_above_the_authorized_cap_returns_422
    """
    chain = _aurora_policy(api)
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    claim = fixtures.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    vendor = fixtures.create_vendor(api, IRONCLAD_FORENSICS)
    engagement = fixtures.authorize_engagement(
        api,
        claim["id"],
        vendor_type="FORENSICS",
        deployment_start_at="2026-09-10T00:00:00Z",
        deployment_end_at="2026-09-12T00:00:00Z",
        authorized_hours_cap=40,
        panel_vendor_id=vendor["id"],
    )
    fixtures.log_hours(api, engagement["id"], hours=30)

    # 30 + 11 is 41 against a cap of 40.
    response = api.log_engagement_hours(
        engagement["id"], F.log_hours_payload(hours=11), ADJUSTER_HEADERS
    )
    validate_error(response, ErrorId.AUTHORIZED_HOURS_EXCEEDED)

    after = data_of(api.get_vendor_engagement(engagement["id"], ADJUSTER_HEADERS))
    assert after["incurred_hours"] == 30, (
        f"the refused log must change nothing: incurred_hours {after['incurred_hours']}"
    )
    assert_money(after["incurred_amount_usd"], 15000.00, "incurred_amount_usd")
    assert after["status"] == "ACTIVE", f"engagement status drifted to {after['status']}"

    # The cap itself is inclusive: the increment that lands exactly on 40 is fine.
    restored = fixtures.log_hours(api, engagement["id"], hours=10)
    assert restored["incurred_hours"] == 40, (
        f"a log landing on the cap must be accepted: {restored['incurred_hours']}"
    )
    assert_money(restored["incurred_amount_usd"], 20000.00, "incurred_amount_usd")


def test_accepting_a_proof_on_an_exhausted_aggregate_is_refused(api):
    """PRD §3.8: "Accepting a proof requires the proof in `UNDER_REVIEW`, the claim in `PROOF_REVIEW`, and the policy in `INFORCE`; a policy whose `aggregate_limit_remaining_usd` stands at 0.00 refuses acceptance with `ERR_AGGREGATE_LIMIT_EXHAUSTED`."

    Design: Corner/validations/accepting_a_proof_on_an_exhausted_aggregate_returns_422
    """
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    chain = fixtures.bound_policy(
        api,
        account_spec=C.ACCOUNT_BITWISE,
        attestations=ATTEST_BITWISE,
        requested_aggregate_limit_usd=250000,
        requested_retention_usd=0,
        dependent_bi_definition="BROAD_SYSTEM_FAILURE",
        coverage_sections=C.SMALL_TOWER,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    )
    policy = chain["policy"]

    fixtures.set_clock(api, "2026-09-10T00:00:00Z")
    first_claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=300000,
    )
    second_claim = fixtures.confirmed_claim(
        api,
        policy["id"],
        incident_type="SYSTEM_FAILURE",
        incident_discovered_at="2026-09-06T00:00:00Z",
        outage_start_at="2026-09-06T00:00:00Z",
        outage_end_at="2026-09-09T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=100000,
    )

    proof_terms = {
        "claimed_bi_loss_usd": 300000,
        "trailing_12m_revenue_usd": 43800000,
        "prior_year_same_period_revenue_usd": 1200000,
        "prior_year_same_period_hours": 200,
        "gross_profit_margin_pct": 1.0,
        "extra_expense_usd": 0,
        "mitigation_savings_usd": 0,
    }
    # Both proofs are on file before any acceptance, so the second one is filed
    # while the aggregate is still intact.
    second_proof = fixtures.file_proof(api, second_claim["id"], **proof_terms)
    first_proof = fixtures.file_proof(api, first_claim["id"], **proof_terms)

    fixtures.accept_proof(api, first_proof["id"])
    drained = fixtures.read_policy(api, policy["id"])
    assert_money(drained["aggregate_limit_remaining_usd"], 0.00, "aggregate_limit_remaining_usd")
    assert drained["limit_status"] == "EXHAUSTED", (
        f"the aggregate is spent, so limit_status must be EXHAUSTED, got {drained['limit_status']}"
    )

    response = api.accept_proof_of_loss(second_proof["id"], ADJUSTER_2_HEADERS)
    validate_error(response, ErrorId.AGGREGATE_LIMIT_EXHAUSTED)

    after_proof = data_of(api.get_proof_of_loss(second_proof["id"], ADJUSTER_HEADERS))
    assert after_proof["status"] == "UNDER_REVIEW", (
        f"a refused acceptance must leave the proof UNDER_REVIEW, got {after_proof['status']}"
    )

    after_second = fixtures.read_claim(api, second_claim["id"])
    assert after_second["status"] == "PROOF_REVIEW", (
        f"claim status drifted to {after_second['status']}"
    )
    assert_money(after_second["paid_total_usd"], 0.00, "paid_total_usd")
    assert (
        get_total_count(
            api.list_claim_payments(
                ADJUSTER_HEADERS, params={"incident_claim_id": second_claim["id"]}
            )
        )
        == 0
    ), "no payment row may be posted for the refused claim"

    after_first = fixtures.read_claim(api, first_claim["id"])
    assert after_first["status"] == "SETTLED", (
        f"the paid claim must stay SETTLED, got {after_first['status']}"
    )
    assert_money(after_first["paid_total_usd"], 250000.00, "paid_total_usd")
    assert_money(after_first["unallocated_loss_usd"], 50000.00, "unallocated_loss_usd")


def test_coverage_confirmation_while_a_warranty_is_lapsed_is_refused(api):
    """PRD §3.5: "A `LAPSED` policy is still in force and still receives notifications, but two operations are barred while it stays lapsed — coverage confirmation on a claim and issuance of a renewal quote — each refused with `ERR_MANDATORY_CONTROL_LAPSE`."
    PRD §3.6: "Confirmation requires the policy in `INFORCE` with `limit_status` other than `EXHAUSTED`, requires `warranty_status` to be `COMPLIANT` rather than `LAPSED`, and is refused with `ERR_AGGREGATE_LIMIT_EXHAUSTED` when the policy's `aggregate_limit_remaining_usd` stands at 0.00."

    Design: Corner/validations/coverage_confirmation_while_a_warranty_is_lapsed_returns_422
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")

    lapsed = data_of(
        api.create_warranty_report(
            policy["id"],
            F.warranty_report_payload(["OFFLINE_BACKUPS"]),
            UNDERWRITER_HEADERS,
        )
    )
    assert lapsed["warranty_status"] == "LAPSED", (
        f"a reported lapse must show as LAPSED, got {lapsed['warranty_status']}"
    )

    claim = fixtures.notify_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
    )
    fixtures.triage_claim(api, claim["id"])

    response = api.confirm_coverage(
        claim["id"],
        F.confirm_coverage_payload(
            covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
            initial_reserve_usd=300000,
        ),
        ADJUSTER_HEADERS,
    )
    validate_error(response, ErrorId.MANDATORY_CONTROL_LAPSE)

    after = fixtures.read_claim(api, claim["id"])
    assert after["status"] == "TRIAGE", (
        f"a refused confirmation must leave the claim in TRIAGE, got {after['status']}"
    )
    assert_money(after["reserved_amount_usd"], 0.00, "reserved_amount_usd")

    after_policy = fixtures.read_policy(api, policy["id"])
    assert after_policy["warranty_status"] == "LAPSED", (
        f"warranty posture drifted to {after_policy['warranty_status']}"
    )
    assert after_policy["lapsed_warranty_control_keys"] == ["OFFLINE_BACKUPS"], (
        f"unexpected lapsed list {after_policy['lapsed_warranty_control_keys']}"
    )


def test_coverage_confirmation_passes_once_the_warranty_is_restored(api):
    """PRD §3.5: "The report rewrites `lapsed_warranty_control_keys`, sorted `control_key` ascending, and recomputes `warranty_status`, which reads `COMPLIANT` while the lapsed list is empty and `LAPSED` otherwise."
    PRD §3.6: "On success `covered_section_keys` and `reservation_of_rights` are stored, `reserved_amount_usd` is set from `initial_reserve_usd`, and the claim's `version` is incremented by 1."

    Design: Corner/validations/coverage_confirmation_passes_once_the_warranty_is_restored
    """
    chain = _aurora_policy(api)
    policy = chain["policy"]
    fixtures.set_clock(api, "2026-09-10T00:00:00Z")

    data_of(
        api.create_warranty_report(
            policy["id"],
            F.warranty_report_payload(["OFFLINE_BACKUPS"]),
            UNDERWRITER_HEADERS,
        )
    )
    restored = data_of(
        api.create_warranty_report(
            policy["id"], F.warranty_report_payload([]), UNDERWRITER_HEADERS
        )
    )
    assert restored["warranty_status"] == "COMPLIANT", (
        f"an empty report restores compliance, got {restored['warranty_status']}"
    )
    assert restored["lapsed_warranty_control_keys"] == [], (
        f"the lapsed list must be emptied, got {restored['lapsed_warranty_control_keys']}"
    )

    claim = fixtures.notify_claim(
        api,
        policy["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
    )
    fixtures.triage_claim(api, claim["id"])

    response = api.confirm_coverage(
        claim["id"],
        F.confirm_coverage_payload(
            covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
            initial_reserve_usd=300000,
        ),
        ADJUSTER_HEADERS,
    )
    validate_success(response)
    confirmed = data_of(response)

    assert confirmed["status"] == "COVERAGE_CONFIRMED", (
        f"unexpected status {confirmed['status']}"
    )
    assert_money(confirmed["reserved_amount_usd"], 300000.00, "reserved_amount_usd")
    assert sorted(confirmed["covered_section_keys"]) == [
        "BUSINESS_INTERRUPTION",
        "FIRST_PARTY_RESPONSE",
    ], f"unexpected confirmed sections {confirmed['covered_section_keys']}"

    after_policy = fixtures.read_policy(api, policy["id"])
    assert after_policy["warranty_status"] == "COMPLIANT", (
        f"warranty posture drifted to {after_policy['warranty_status']}"
    )
    assert after_policy["lapsed_warranty_control_keys"] == [], (
        f"unexpected lapsed list {after_policy['lapsed_warranty_control_keys']}"
    )
