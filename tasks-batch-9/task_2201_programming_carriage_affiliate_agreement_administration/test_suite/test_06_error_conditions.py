"""Rejection paths of the carriage administration contract: path resolution,
header validity, operator scope, segregation of duties, the revision guard on
invoice creation, and the report / renewal / engagement state gates.

Every test builds its own state from an empty database through PRD-declared
endpoints only.
"""
import pytest

from test_helpers import (
    ACCOUNTANT,
    ADMIN,
    AUDITOR,
    NON_EXISTENT_UUID,
    SALES,
    ApiErrorId,
    advance_clock,
    create_agreement_payload,
    create_audit_finding_payload,
    create_invoice_payload,
    create_subscriber_report_payload,
    distributor_version,
    fetch_agreement,
    fetch_engagement,
    fetch_report,
    file_report,
    get_success_data,
    make_affiliate_sales_exec_headers,
    make_distributor_liaison_headers,
    make_revenue_accountant_headers,
    open_engagement,
    record_finding,
    register_distributor,
    setup_accepted_report,
    setup_engagement_in_fieldwork,
    setup_executed_agreement,
    start_fieldwork,
    validate_error,
    validate_paginated,
    validate_success,
)

# Commercial shape shared by the recipes below: a small telco operator on a
# BASIC-tier agreement with a flat rate, so every fee is exact.
_TELCO = {
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
}
_TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}
_JUNE = "2026-06"
_JUNE_REPORT = {
    "period_month": _JUNE,
    "reported_subscribers": 130_000,
    "reported_tier": "BASIC",
}
# 130,000 billable subscribers (above the 100,000 floor) x 40.0000 cents x 1.00.
_JUNE_FEE_CENTS = 5_200_000


def _setup_agreement_executed_by(api, acting_user_id, distributor_overrides, agreement_overrides):
    """Operator plus an agreement driven DRAFT → NEGOTIATING → EXECUTED by one
    nominated `X-User-ID` acting as `AffiliateSalesExec`."""
    exec_headers = make_affiliate_sales_exec_headers(acting_user_id)
    distributor = register_distributor(**distributor_overrides)
    agreement = get_success_data(
        api.create_agreement(
            create_agreement_payload(distributor["id"], **agreement_overrides), exec_headers
        )
    )
    get_success_data(
        api.agreement_lifecycle(agreement["id"], {"action": "SUBMIT_FOR_NEGOTIATION"}, exec_headers)
    )
    agreement = get_success_data(
        api.agreement_lifecycle(agreement["id"], {"action": "EXECUTE"}, exec_headers)
    )
    return distributor, agreement


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
_PATH_NOT_FOUND_CASES = [
    ("distributor", lambda api: api.get_distributor(NON_EXISTENT_UUID, ADMIN),
     ApiErrorId.ERR_DISTRIBUTOR_NOT_FOUND),
    ("agreement", lambda api: api.get_agreement(NON_EXISTENT_UUID, ADMIN),
     ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
    ("rate_card_entry", lambda api: api.get_rate_card_entry(NON_EXISTENT_UUID, ADMIN),
     ApiErrorId.ERR_RATE_CARD_ENTRY_NOT_FOUND),
    ("mfn_clause", lambda api: api.get_mfn_clause(NON_EXISTENT_UUID, SALES),
     ApiErrorId.ERR_MFN_CLAUSE_NOT_FOUND),
    ("report", lambda api: api.get_subscriber_report(NON_EXISTENT_UUID, ACCOUNTANT),
     ApiErrorId.ERR_REPORT_NOT_FOUND),
    ("engagement", lambda api: api.get_audit_engagement(NON_EXISTENT_UUID, AUDITOR),
     ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND),
    ("finding", lambda api: api.get_audit_finding(NON_EXISTENT_UUID, AUDITOR),
     ApiErrorId.ERR_FINDING_NOT_FOUND),
    ("title", lambda api: api.get_content_title(NON_EXISTENT_UUID, ADMIN),
     ApiErrorId.ERR_TITLE_NOT_FOUND),
    ("window", lambda api: api.get_rights_window(NON_EXISTENT_UUID, ADMIN),
     ApiErrorId.ERR_WINDOW_NOT_FOUND),
    ("blackout_rule", lambda api: api.get_blackout_rule(NON_EXISTENT_UUID, ADMIN),
     ApiErrorId.ERR_BLACKOUT_NOT_FOUND),
    ("commitment", lambda api: api.get_marketing_commitment(NON_EXISTENT_UUID, SALES),
     ApiErrorId.ERR_COMMITMENT_NOT_FOUND),
    ("invoice", lambda api: api.get_invoice(NON_EXISTENT_UUID, ACCOUNTANT),
     ApiErrorId.ERR_INVOICE_NOT_FOUND),
    ("analysis", lambda api: api.get_renewal_analysis(NON_EXISTENT_UUID, SALES),
     ApiErrorId.ERR_ANALYSIS_NOT_FOUND),
]


@pytest.mark.parametrize(
    "read_call, expected_error_id",
    [(case[1], case[2]) for case in _PATH_NOT_FOUND_CASES],
    ids=[case[0] for case in _PATH_NOT_FOUND_CASES],
)
def test_path_parameter_not_found_uses_its_own_entity_code(api, read_call, expected_error_id):
    """PRD §2.8: "Path parameters are resolved left to right, and the first
    unresolvable segment decides the response."
    PRD §2.8: "The path identifiers used across the API are `distributorId`,
    `agreementId`, `rateCardEntryId`, `mfnClauseId`, `reportId`, `engagementId`,
    `findingId`, `titleId`, `windowId`, `blackoutRuleId`, `commitmentId`,
    `invoiceId` and `analysisId`, and each has its own not-found code:
    `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_RATE_CARD_ENTRY_NOT_FOUND`, `ERR_MFN_CLAUSE_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
    `ERR_TITLE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_BLACKOUT_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and
    `ERR_ANALYSIS_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/every_path_parameter_404_uses_its_own_entity_code
    """
    response = read_call(api)
    validate_error(response, expected_error_id.value)


# ---------------------------------------------------------------------------
# Header validity
# ---------------------------------------------------------------------------
_BAD_HEADER_CASES = [
    ("role_header_omitted", {"X-User-ID": "u-admin-1", "Content-Type": "application/json"}),
    ("user_id_header_omitted", {"X-User-Role": "NetworkAdmin", "Content-Type": "application/json"}),
    (
        "undeclared_role",
        {
            "X-User-ID": "u-admin-1",
            "X-User-Role": "ProgrammingIntern",
            "Content-Type": "application/json",
        },
    ),
]


@pytest.mark.parametrize(
    "headers", [case[1] for case in _BAD_HEADER_CASES], ids=[case[0] for case in _BAD_HEADER_CASES]
)
def test_missing_or_undeclared_role_header_is_unauthenticated(api, headers):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/missing_or_unknown_role_header_is_unauthenticated
    """
    distributor = register_distributor()

    control = validate_success(api.get_distributor(distributor["id"], ADMIN))
    assert control["id"] == distributor["id"], "well-formed headers must read the operator back"

    response = api.get_distributor(distributor["id"], headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Operator scope for a DistributorLiaison
# ---------------------------------------------------------------------------
def test_liaison_cannot_read_another_operators_agreement(api):
    """PRD §2.1: "When `X-User-Role` is `DistributorLiaison`, `X-User-ID` is the
    `id` of the acting `Distributor`; ownership checks on any resource that
    references a `Distributor` compare the resource's resolved distributor
    identity to `X-User-ID`."
    PRD §2.1: "A `DistributorLiaison` acting on a resource that resolves to any
    other operator is rejected with `ERR_DISTRIBUTOR_SCOPE_VIOLATION` (HTTP
    403)."

    Design: Corner/errors/liaison_cannot_reach_another_operators_records
    """
    owner, agreement = setup_executed_agreement(
        distributor_overrides={
            "distributor_type": "CABLE_MSO",
            "rate_card_class": "CLASS_A",
            "total_subscribers": 1_500_000,
        },
        agreement_overrides=_TERMS,
    )
    other = register_distributor(
        distributor_type="DBS", rate_card_class="CLASS_B", total_subscribers=800_000
    )

    response = api.get_agreement(agreement["id"], make_distributor_liaison_headers(other["id"]))
    validate_error(response, ApiErrorId.ERR_DISTRIBUTOR_SCOPE_VIOLATION.value)

    own_read = validate_success(
        api.get_agreement(agreement["id"], make_distributor_liaison_headers(owner["id"]))
    )
    assert own_read["id"] == agreement["id"], "the owning operator's liaison reads its own agreement"


def test_liaison_cannot_file_a_report_against_another_operators_agreement(api):
    """PRD §2.1: "A `DistributorLiaison` acting on a resource that resolves to any
    other operator is rejected with `ERR_DISTRIBUTOR_SCOPE_VIOLATION` (HTTP
    403)."
    PRD §2.8: "**The first rule that fails decides the response, and no side
    effect of the requested operation fires.**"

    Design: Corner/errors/liaison_cannot_reach_another_operators_records
    """
    _owner, agreement = setup_executed_agreement(
        distributor_overrides={
            "distributor_type": "CABLE_MSO",
            "rate_card_class": "CLASS_A",
            "total_subscribers": 1_500_000,
        },
        agreement_overrides=_TERMS,
    )
    other = register_distributor(
        distributor_type="DBS", rate_card_class="CLASS_B", total_subscribers=800_000
    )

    payload = create_subscriber_report_payload(
        agreement["id"],
        agreement["version"],
        period_month=_JUNE,
        reported_subscribers=900_000,
        reported_tier="BASIC",
    )
    response = api.create_subscriber_report(payload, make_distributor_liaison_headers(other["id"]))
    validate_error(response, ApiErrorId.ERR_DISTRIBUTOR_SCOPE_VIOLATION.value)

    _rows, meta = validate_paginated(
        api.list_subscriber_reports(ADMIN, params={"agreement_id": agreement["id"], "limit": 10})
    )
    assert meta["total_count"] == 0, "the refused filing must not have created a report"


# ---------------------------------------------------------------------------
# Segregation of duties
# ---------------------------------------------------------------------------
def test_executing_user_cannot_review_the_agreements_report(api):
    """PRD §2.1: "The `X-User-ID` that executed a given agreement may not be the
    `X-User-ID` that reviews a subscriber report belonging to that agreement."
    PRD §2.1: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."
    PRD §3.4: "A successful acceptance stamps `billable_subscribers`,
    `rate_applied_cents_per_sub` and `license_fee_due_cents` under the final
    variant, sets `accepted_at` to the current logical instant, and moves the
    report `SUBMITTED → ACCEPTED`."
    PRD §3.4: "First, the agreement's `recognized_revenue_cents` increases by the
    newly stamped `license_fee_due_cents`, and `penetration_compliance_status` is
    re-derived as described in §3.5."

    Design: Corner/errors/segregation_of_duties_blocks_the_executing_user_from_accepting
    """
    distributor, agreement = _setup_agreement_executed_by(api, "u-rev-2", _TELCO, _TERMS)
    report = file_report(agreement["id"], distributor["id"], **_JUNE_REPORT)

    response = api.review_subscriber_report(
        report["id"], {"action": "ACCEPT"}, make_revenue_accountant_headers("u-rev-2")
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert fetch_report(report["id"])["status"] == "SUBMITTED", (
        "the refused review must leave the report in SUBMITTED"
    )

    accepted = validate_success(
        api.review_subscriber_report(report["id"], {"action": "ACCEPT"}, ACCOUNTANT)
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["license_fee_due_cents"] == _JUNE_FEE_CENTS
    assert fetch_agreement(agreement["id"])["recognized_revenue_cents"] == _JUNE_FEE_CENTS


# ---------------------------------------------------------------------------
# Revision guard on invoice creation
# ---------------------------------------------------------------------------
def test_stale_distributor_version_blocks_invoice_creation(api):
    """PRD §2.7: "`POST /carriage/invoices` requires
    `expected_distributor_version`, carrying the client's last observed `version`
    of the `Distributor` named by `distributor_id`. A mismatch is rejected with
    `ERR_STALE_DISTRIBUTOR_VERSION` (HTTP 412)."
    PRD §3.8: "Likewise a draft never claims its source reports — their
    `invoice_id` stays null — which is why two drafts for the same period can
    coexist, why only the first one to issue actually claims the reports, and why
    any later draft naming those now-claimed reports is refused with
    `ERR_REPORT_ALREADY_BILLED`."

    Design: Corner/errors/stale_distributor_version_blocks_invoice_creation
    """
    distributor, agreement, report = setup_accepted_report(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )
    stale_version = distributor["version"]
    get_success_data(
        api.patch_distributor(distributor["id"], {"credit_limit_cents": 150_000_000}, ADMIN)
    )

    response = api.create_invoice(
        create_invoice_payload(distributor["id"], agreement["id"], _JUNE, stale_version), ACCOUNTANT
    )
    validate_error(response, ApiErrorId.ERR_STALE_DISTRIBUTOR_VERSION.value)

    _rows, meta = validate_paginated(
        api.list_invoices(ACCOUNTANT, params={"agreement_id": agreement["id"], "limit": 10})
    )
    assert meta["total_count"] == 0, "the refused draft must not have created an invoice"

    invoice = validate_success(
        api.create_invoice(
            create_invoice_payload(
                distributor["id"], agreement["id"], _JUNE, distributor_version(distributor["id"])
            ),
            ACCOUNTANT,
        ),
        201,
    )
    assert invoice["status"] == "DRAFT"
    assert invoice["gross_license_fee_cents"] == _JUNE_FEE_CENTS
    assert invoice["net_due_cents"] == _JUNE_FEE_CENTS
    assert fetch_report(report["id"])["invoice_id"] is None, "a DRAFT claims no report"


# ---------------------------------------------------------------------------
# Report review state gate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("action", ["ACCEPT", "DISPUTE", "REQUEST_RESTATEMENT"])
def test_review_action_refused_once_the_report_is_accepted(api, action):
    """PRD §3.4: "The review endpoint enforces the state machine first:
    acceptance and dispute both require `SUBMITTED`, requesting a restatement
    requires `DISPUTED`, and accepting an adjustment requires `AUDIT_ADJUSTED`;
    anything else is `ERR_INVALID_REPORT_STATE`."
    PRD §3.5: "A compliant period increments `consecutive_compliant_periods` by
    one and sets `penetration_compliance_status` to `COMPLIANT`."
    PRD §2.8: "**The first rule that fails decides the response, and no side
    effect of the requested operation fires.**"

    Design: Corner/errors/review_actions_rejected_from_wrong_report_state
    """
    _distributor, agreement, report = setup_accepted_report(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )
    assert report["status"] == "ACCEPTED"

    response = api.review_subscriber_report(report["id"], {"action": action}, ACCOUNTANT)
    validate_error(response, ApiErrorId.ERR_INVALID_REPORT_STATE.value)

    after = fetch_report(report["id"])
    assert after["status"] == "ACCEPTED", f"{action} must not move an ACCEPTED report"
    assert after["version"] == report["version"], "a refused review bumps no version"
    assert after["license_fee_due_cents"] == _JUNE_FEE_CENTS, "the stamped fee is untouched"

    live_agreement = fetch_agreement(agreement["id"])
    assert live_agreement["consecutive_compliant_periods"] == 1
    assert live_agreement["recognized_revenue_cents"] == _JUNE_FEE_CENTS


# ---------------------------------------------------------------------------
# Renewal dimension gates
# ---------------------------------------------------------------------------
def test_renewing_before_an_offer_is_an_invalid_renewal_state(api):
    """PRD §3.2: "An action that is not a declared transition out of the current
    `lifecycle_status` is rejected with `ERR_INVALID_AGREEMENT_STATE`; an action
    that is not a declared transition out of the current `renewal_status` is
    rejected with `ERR_INVALID_RENEWAL_STATE`."
    PRD §3.9: "An accepted offer moves the agreement `RENEWAL_OFFERED →
    RENEWED`."

    Design: Corner/errors/renewal_actions_rejected_out_of_order_and_out_of_window
    """
    _distributor, agreement = setup_executed_agreement(
        distributor_overrides=_TELCO, agreement_overrides=_TERMS
    )
    assert agreement["renewal_status"] == "NOT_DUE"

    response = api.agreement_renewal(agreement["id"], {"action": "RENEW"}, SALES)
    validate_error(response, ApiErrorId.ERR_INVALID_RENEWAL_STATE.value)

    after = fetch_agreement(agreement["id"])
    assert after["renewal_status"] == "NOT_DUE", "the refused RENEW leaves the dimension alone"
    assert after["lifecycle_status"] == "EXECUTED", "the renewal dimension never writes lifecycle"


def test_analysis_cannot_open_before_the_renewal_window(api):
    """PRD §3.9: "An `AffiliateSalesExec` moves the agreement `NOT_DUE →
    RENEWAL_ANALYSIS`, which requires the `lifecycle_status` to be `EXECUTED` or
    `SUSPENDED` — an operator under suspension is still a renewal candidate — and
    requires the renewal window to be open: `term_end_date` must be no more than
    270 days beyond the current logical instant."
    PRD §3.9: "Opening analysis earlier is refused with
    `ERR_RENEWAL_WINDOW_NOT_OPEN`."
    PRD §3.9: "The transition stamps `renewal_analysis_started_at` with the
    current logical instant and leaves `negotiation_round` at 0."

    Design: Corner/errors/renewal_actions_rejected_out_of_order_and_out_of_window
    """
    _distributor, agreement = setup_executed_agreement(
        distributor_overrides=_TELCO, agreement_overrides=_TERMS
    )

    response = api.agreement_renewal(agreement["id"], {"action": "START_ANALYSIS"}, SALES)
    validate_error(response, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value)
    assert fetch_agreement(agreement["id"])["renewal_status"] == "NOT_DUE"

    advance_clock("2028-06-01T00:00:00Z")
    opened = validate_success(
        api.agreement_renewal(agreement["id"], {"action": "START_ANALYSIS"}, SALES)
    )
    assert opened["renewal_status"] == "RENEWAL_ANALYSIS", (
        "inside the 270-day window the same action must succeed"
    )
    # PRD §2.6: "Instants are compared at whole-second resolution."
    assert opened["renewal_analysis_started_at"].startswith("2028-06-01T00:00:00"), (
        "the transition stamps the current logical instant, got "
        f"{opened['renewal_analysis_started_at']}"
    )


# ---------------------------------------------------------------------------
# Audit engagement gates
# ---------------------------------------------------------------------------
def test_finding_refused_while_the_engagement_is_still_opened(api):
    """PRD §3.7: "Findings are recorded one at a time while the engagement is in
    `FIELDWORK`; recording one against an engagement in any other status is
    refused with `ERR_INVALID_ENGAGEMENT_STATE`."

    Design: Corner/errors/engagement_findings_and_fieldwork_guards
    """
    _distributor, agreement, report = setup_accepted_report(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )
    engagement = open_engagement(
        agreement["id"],
        sample_period_start=_JUNE,
        sample_period_end=_JUNE,
        rate_basis="PERIOD_RATE",
    )
    assert engagement["status"] == "OPENED"

    response = api.create_audit_finding(
        engagement["id"], create_audit_finding_payload(report["id"], 140_000), AUDITOR
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENGAGEMENT_STATE.value)

    after = fetch_engagement(engagement["id"])
    assert after["status"] == "OPENED", "the refused finding leaves the engagement in OPENED"
    _rows, meta = validate_paginated(
        api.list_audit_findings(AUDITOR, params={"engagement_id": engagement["id"], "limit": 10})
    )
    assert meta["total_count"] == 0, "no finding may have been persisted"


def test_finding_refused_against_a_report_outside_the_sample(api):
    """PRD §3.7: "The named report must belong to the engagement's agreement, must
    be in `ACCEPTED` or `AUDIT_ADJUSTED`, and must have a `period_month` inside
    the engagement's sample range; otherwise the finding is refused with
    `ERR_AUDIT_PERIOD_NOT_REPORTED`."
    PRD §3.7: "On creation the server snapshots the report's `period_month` and
    its `reported_subscribers` onto the finding, so a later restatement cannot
    rewrite audit history, and computes `variance_subscribers` as the audited
    count less the reported count, floored at zero — an operator that
    over-reported produces a finding of zero variance, never a negative one."

    Design: Corner/errors/engagement_findings_and_fieldwork_guards
    """
    distributor, agreement, june_report = setup_accepted_report(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
    )
    july_report = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-07",
        reported_subscribers=131_000,
        reported_tier="BASIC",
    )
    assert july_report["status"] == "SUBMITTED"

    engagement = open_engagement(
        agreement["id"],
        sample_period_start=_JUNE,
        sample_period_end=_JUNE,
        rate_basis="PERIOD_RATE",
    )
    start_fieldwork(engagement["id"])

    response = api.create_audit_finding(
        engagement["id"], create_audit_finding_payload(july_report["id"], 140_000), AUDITOR
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_PERIOD_NOT_REPORTED.value)

    finding = validate_success(
        api.create_audit_finding(
            engagement["id"], create_audit_finding_payload(june_report["id"], 140_000), AUDITOR
        ),
        201,
    )
    assert finding["period_month"] == _JUNE
    assert finding["reported_subscribers"] == 130_000
    assert finding["variance_subscribers"] == 10_000


def test_close_no_finding_refused_while_a_positive_variance_stands(api):
    """PRD §3.7: "The **close-with-no-finding** branch moves `FIELDWORK →
    CLOSED_NO_FINDING` and requires the opposite: no finding of the engagement may
    have positive `variance_subscribers`, and attempting it while one does is
    refused with `ERR_FINDINGS_PRESENT_CANNOT_CLOSE`."

    Design: Corner/errors/engagement_findings_and_fieldwork_guards
    """
    _distributor, _agreement, report, engagement = setup_engagement_in_fieldwork(
        distributor_overrides=_TELCO,
        agreement_overrides=_TERMS,
        report_overrides=_JUNE_REPORT,
        engagement_overrides={"rate_basis": "PERIOD_RATE"},
    )
    finding = record_finding(engagement["id"], report["id"], 140_000)
    assert finding["variance_subscribers"] == 10_000

    response = api.audit_engagement_lifecycle(
        engagement["id"], {"action": "CLOSE_NO_FINDING"}, AUDITOR
    )
    validate_error(response, ApiErrorId.ERR_FINDINGS_PRESENT_CANNOT_CLOSE.value)
    assert fetch_engagement(engagement["id"])["status"] == "FIELDWORK", (
        "the refused close leaves the engagement in FIELDWORK"
    )
