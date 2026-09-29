"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient `get_success_data` validator so a broken
precondition surfaces as a setup failure rather than a confusing assertion.

Identity discipline: `DistributorLiaison` calls always use
`make_distributor_liaison_headers(distributor["id"])`; the five opaque roles use
the shared constants from `test_users`.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_payload,
    create_agreement_payload,
    create_audit_engagement_payload,
    create_audit_finding_payload,
    create_blackout_rule_payload,
    create_content_title_payload,
    create_distributor_payload,
    create_invoice_payload,
    create_marketing_commitment_payload,
    create_mfn_clause_payload,
    create_rate_card_entry_payload,
    create_renewal_analysis_payload,
    create_rights_window_payload,
    create_subscriber_report_payload,
    earn_payload,
)
from .test_users import TEST_USERS, make_distributor_liaison_headers

ADMIN = TEST_USERS["network_admin_headers"]
SALES = TEST_USERS["affiliate_sales_exec_headers"]
SALES_2 = TEST_USERS["affiliate_sales_exec_2_headers"]
ACCOUNTANT = TEST_USERS["revenue_accountant_headers"]
ACCOUNTANT_2 = TEST_USERS["revenue_accountant_2_headers"]
AUDITOR = TEST_USERS["audit_manager_headers"]
AUDITOR_2 = TEST_USERS["audit_manager_2_headers"]
RIGHTS = TEST_USERS["rights_administrator_headers"]


# --------------------------------------------------------------------------
# Tier 0: current-state reads (OCC guards need the live parent revision)
# --------------------------------------------------------------------------
def fetch_distributor(distributor_id: str) -> dict:
    return get_success_data(api_client.get_distributor(distributor_id, ADMIN))


def fetch_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, SALES))


def fetch_report(report_id: str) -> dict:
    return get_success_data(api_client.get_subscriber_report(report_id, ACCOUNTANT))


def fetch_engagement(engagement_id: str) -> dict:
    return get_success_data(api_client.get_audit_engagement(engagement_id, AUDITOR))


def fetch_title(title_id: str) -> dict:
    return get_success_data(api_client.get_content_title(title_id, RIGHTS))


def fetch_window(window_id: str) -> dict:
    return get_success_data(api_client.get_rights_window(window_id, RIGHTS))


def fetch_blackout_rule(rule_id: str) -> dict:
    return get_success_data(api_client.get_blackout_rule(rule_id, RIGHTS))


def fetch_commitment(commitment_id: str) -> dict:
    return get_success_data(api_client.get_marketing_commitment(commitment_id, SALES))


def fetch_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, ACCOUNTANT))


def agreement_version(agreement_id: str) -> int:
    return fetch_agreement(agreement_id)["version"]


def distributor_version(distributor_id: str) -> int:
    return fetch_distributor(distributor_id)["version"]


def advance_clock(to_iso8601: str) -> dict:
    """Move the logical clock forward, running the pinned sweep."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def read_clock() -> dict:
    return get_success_data(api_client.get_clock(ADMIN))


# --------------------------------------------------------------------------
# Tier 1: single-resource creation
# --------------------------------------------------------------------------
def register_distributor(**overrides) -> dict:
    """Register one operator. Starts ACTIVE with version 1."""
    return get_success_data(
        api_client.create_distributor(create_distributor_payload(**overrides), ADMIN)
    )


def publish_rate_card_entry(**overrides) -> dict:
    return get_success_data(
        api_client.create_rate_card_entry(create_rate_card_entry_payload(**overrides), ADMIN)
    )


def draft_agreement(distributor_id: str, **overrides) -> dict:
    """Draft one agreement; opens in DRAFT / NOT_DUE."""
    return get_success_data(
        api_client.create_agreement(create_agreement_payload(distributor_id, **overrides), SALES)
    )


def register_title(rights_status: str = None, **overrides) -> dict:
    """Register a content title, optionally driving its rights_status onwards."""
    title = get_success_data(
        api_client.create_content_title(create_content_title_payload(**overrides), RIGHTS)
    )
    if rights_status:
        title = get_success_data(
            api_client.set_title_rights_status(
                title["id"], {"rights_status": rights_status}, RIGHTS
            )
        )
    return title


def register_cleared_title(**overrides) -> dict:
    """A title whose rights_status is OWNED_CLEARED — the only status that
    permits a window on it to be cleared."""
    return register_title(rights_status="OWNED_CLEARED", **overrides)


# --------------------------------------------------------------------------
# Tier 2: agreement lifecycle progression
# --------------------------------------------------------------------------
def submit_agreement_for_negotiation(agreement_id: str) -> dict:
    return get_success_data(
        api_client.agreement_lifecycle(
            agreement_id, {"action": "SUBMIT_FOR_NEGOTIATION"}, SALES
        )
    )


def execute_agreement(agreement_id: str) -> dict:
    """Walk DRAFT → NEGOTIATING → EXECUTED."""
    submit_agreement_for_negotiation(agreement_id)
    return get_success_data(
        api_client.agreement_lifecycle(agreement_id, {"action": "EXECUTE"}, SALES)
    )


def suspend_agreement(agreement_id: str, suspension_reason: str = None) -> dict:
    payload = {"action": "SUSPEND"}
    if suspension_reason is not None:
        payload["suspension_reason"] = suspension_reason
    return get_success_data(api_client.agreement_lifecycle(agreement_id, payload, SALES))


def reinstate_agreement(agreement_id: str) -> dict:
    return get_success_data(
        api_client.agreement_lifecycle(agreement_id, {"action": "REINSTATE"}, SALES)
    )


def setup_executed_agreement(distributor_overrides=None, agreement_overrides=None):
    """Operator + agreement walked through to EXECUTED.

    Returns (distributor, agreement) with both freshly read back, so
    `distributor["version"]` and `agreement["version"]` are current.
    """
    distributor = register_distributor(**(distributor_overrides or {}))
    agreement = draft_agreement(distributor["id"], **(agreement_overrides or {}))
    agreement = execute_agreement(agreement["id"])
    distributor = fetch_distributor(distributor["id"])
    return distributor, agreement


def setup_suspended_agreement(distributor_overrides=None, agreement_overrides=None):
    """Executed agreement then manually suspended (suspension_reason
    MANUAL_SUSPENSION). Returns (distributor, agreement)."""
    distributor, agreement = setup_executed_agreement(distributor_overrides, agreement_overrides)
    agreement = suspend_agreement(agreement["id"])
    return fetch_distributor(distributor["id"]), agreement


def setup_draft_agreement(distributor_overrides=None, agreement_overrides=None):
    distributor = register_distributor(**(distributor_overrides or {}))
    agreement = draft_agreement(distributor["id"], **(agreement_overrides or {}))
    return distributor, agreement


def setup_negotiating_agreement(distributor_overrides=None, agreement_overrides=None):
    distributor, agreement = setup_draft_agreement(distributor_overrides, agreement_overrides)
    agreement = submit_agreement_for_negotiation(agreement["id"])
    return distributor, agreement


# --------------------------------------------------------------------------
# Tier 3: subscriber reporting
# --------------------------------------------------------------------------
def file_report(agreement_id: str, distributor_id: str = None, headers=None, **overrides) -> dict:
    """File one subscriber report, threading the agreement's live `version`
    into `expected_agreement_version` unless the caller overrides it.

    When `distributor_id` is given the filing is made by that operator's
    liaison; otherwise the accountant files it.
    """
    expected = overrides.pop("expected_agreement_version", None)
    if expected is None:
        expected = agreement_version(agreement_id)
    payload = create_subscriber_report_payload(agreement_id, expected, **overrides)
    if headers is None:
        headers = (
            make_distributor_liaison_headers(distributor_id) if distributor_id else ACCOUNTANT
        )
    return get_success_data(api_client.create_subscriber_report(payload, headers))


def accept_report(report_id: str, note: str = None) -> dict:
    payload = {"action": "ACCEPT"}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.review_subscriber_report(report_id, payload, ACCOUNTANT))


def dispute_report(report_id: str, note: str = None) -> dict:
    payload = {"action": "DISPUTE"}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.review_subscriber_report(report_id, payload, ACCOUNTANT))


def request_restatement(report_id: str) -> dict:
    return get_success_data(
        api_client.review_subscriber_report(report_id, {"action": "REQUEST_RESTATEMENT"}, ACCOUNTANT)
    )


def accept_adjustment(report_id: str) -> dict:
    return get_success_data(
        api_client.review_subscriber_report(report_id, {"action": "ACCEPT_ADJUSTMENT"}, ACCOUNTANT)
    )


def setup_accepted_report(
    distributor_overrides=None,
    agreement_overrides=None,
    report_overrides=None,
):
    """Executed agreement with one ACCEPTED subscriber report.

    Returns (distributor, agreement, report), each read back after the
    acceptance cascade so counters and versions are current.
    """
    distributor, agreement = setup_executed_agreement(distributor_overrides, agreement_overrides)
    report = file_report(agreement["id"], distributor["id"], **(report_overrides or {}))
    report = accept_report(report["id"])
    return fetch_distributor(distributor["id"]), fetch_agreement(agreement["id"]), report


def setup_restated_report(distributor_overrides=None, agreement_overrides=None, report_overrides=None):
    """Executed agreement with one report walked SUBMITTED → DISPUTED → RESTATED.

    Returns (distributor, agreement, report).
    """
    distributor, agreement = setup_executed_agreement(distributor_overrides, agreement_overrides)
    report = file_report(agreement["id"], distributor["id"], **(report_overrides or {}))
    dispute_report(report["id"])
    report = request_restatement(report["id"])
    return distributor, fetch_agreement(agreement["id"]), report


def file_and_accept_report(agreement_id: str, distributor_id: str, **overrides) -> dict:
    """One more accepted period on an existing agreement."""
    report = file_report(agreement_id, distributor_id, **overrides)
    return accept_report(report["id"])


# --------------------------------------------------------------------------
# Tier 4: audit engagements, findings and recovery
# --------------------------------------------------------------------------
def open_engagement(agreement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_audit_engagement(
            create_audit_engagement_payload(agreement_id, **overrides), AUDITOR
        )
    )


def start_fieldwork(engagement_id: str) -> dict:
    return get_success_data(
        api_client.audit_engagement_lifecycle(engagement_id, {"action": "START_FIELDWORK"}, AUDITOR)
    )


def issue_findings(engagement_id: str) -> dict:
    return get_success_data(
        api_client.audit_engagement_lifecycle(engagement_id, {"action": "ISSUE_FINDINGS"}, AUDITOR)
    )


def close_no_finding(engagement_id: str) -> dict:
    return get_success_data(
        api_client.audit_engagement_lifecycle(engagement_id, {"action": "CLOSE_NO_FINDING"}, AUDITOR)
    )


def record_finding(engagement_id: str, subscriber_report_id: str, audited_subscribers: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_audit_finding(
            engagement_id,
            create_audit_finding_payload(subscriber_report_id, audited_subscribers, **overrides),
            AUDITOR,
        )
    )


def setup_engagement_in_fieldwork(
    distributor_overrides=None,
    agreement_overrides=None,
    report_overrides=None,
    engagement_overrides=None,
):
    """Accepted report plus an engagement over that period, in FIELDWORK.

    Returns (distributor, agreement, report, engagement).
    """
    distributor, agreement, report = setup_accepted_report(
        distributor_overrides, agreement_overrides, report_overrides
    )
    period = report["period_month"]
    overrides = {"sample_period_start": period, "sample_period_end": period}
    overrides.update(engagement_overrides or {})
    engagement = open_engagement(agreement["id"], **overrides)
    engagement = start_fieldwork(engagement["id"])
    return distributor, agreement, report, engagement


def setup_engagement_with_findings_issued(
    audited_subscribers: int,
    distributor_overrides=None,
    agreement_overrides=None,
    report_overrides=None,
    engagement_overrides=None,
):
    """Full audit chain up to FINDINGS_ISSUED, with one finding whose
    `audited_subscribers` the caller pins to drive the variance arithmetic.

    Returns (distributor, agreement, report, engagement, finding), with the
    distributor, report and engagement re-read after the issuance cascade.
    """
    distributor, agreement, report, engagement = setup_engagement_in_fieldwork(
        distributor_overrides, agreement_overrides, report_overrides, engagement_overrides
    )
    finding = record_finding(engagement["id"], report["id"], audited_subscribers)
    engagement = issue_findings(engagement["id"])
    return (
        fetch_distributor(distributor["id"]),
        fetch_agreement(agreement["id"]),
        fetch_report(report["id"]),
        engagement,
        finding,
    )


# --------------------------------------------------------------------------
# Tier 5: content rights, windows and blackouts
# --------------------------------------------------------------------------
def plan_window(agreement_id: str, content_title_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rights_window(
            create_rights_window_payload(agreement_id, content_title_id, **overrides), RIGHTS
        )
    )


def clear_window(window_id: str) -> dict:
    return get_success_data(
        api_client.rights_window_lifecycle(window_id, {"action": "CLEAR"}, RIGHTS)
    )


def block_window(window_id: str, block_reason: str = None) -> dict:
    payload = {"action": "BLOCK"}
    if block_reason is not None:
        payload["block_reason"] = block_reason
    return get_success_data(api_client.rights_window_lifecycle(window_id, payload, RIGHTS))


def unblock_window(window_id: str) -> dict:
    return get_success_data(
        api_client.rights_window_lifecycle(window_id, {"action": "UNBLOCK"}, RIGHTS)
    )


def set_title_rights(title_id: str, rights_status: str) -> dict:
    return get_success_data(
        api_client.set_title_rights_status(title_id, {"rights_status": rights_status}, RIGHTS)
    )


def setup_cleared_window(
    distributor_overrides=None,
    agreement_overrides=None,
    title_overrides=None,
    window_overrides=None,
):
    """Executed agreement, OWNED_CLEARED title, and one window in CLEARED.

    Returns (distributor, agreement, title, window); the title is re-read after
    clearance so `cleared_window_count` and coverage are current.
    """
    distributor, agreement = setup_executed_agreement(distributor_overrides, agreement_overrides)
    title = register_cleared_title(**(title_overrides or {}))
    window = plan_window(agreement["id"], title["id"], **(window_overrides or {}))
    window = clear_window(window["id"])
    return distributor, agreement, fetch_title(title["id"]), window


def schedule_blackout(agreement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_blackout_rule(
            create_blackout_rule_payload(agreement_id, **overrides), RIGHTS
        )
    )


def enforce_blackout(rule_id: str) -> dict:
    return get_success_data(
        api_client.blackout_rule_lifecycle(rule_id, {"action": "ENFORCE"}, RIGHTS)
    )


def waive_blackout(rule_id: str) -> dict:
    return get_success_data(
        api_client.blackout_rule_lifecycle(rule_id, {"action": "WAIVE"}, RIGHTS)
    )


# --------------------------------------------------------------------------
# Tier 6: marketing commitments
# --------------------------------------------------------------------------
def create_commitment(agreement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_marketing_commitment(
            create_marketing_commitment_payload(agreement_id, **overrides), SALES
        )
    )


def earn_commitment(commitment_id: str, earned_cents: int, proof_reference: str = "PROOF-001") -> dict:
    return get_success_data(
        api_client.earn_marketing_commitment(
            commitment_id, earn_payload(earned_cents, proof_reference), SALES
        )
    )


def spawned_commitments(agreement_id: str) -> list:
    """Every commitment attached to one agreement, oldest first."""
    response = api_client.list_marketing_commitments(SALES, params={"agreement_id": agreement_id})
    data = get_success_data(response)
    rows = data if isinstance(data, list) else data.get("data", data)
    return sorted(rows, key=lambda row: row["created_at"])


def commitment_of_type(agreement_id: str, commitment_type: str) -> dict:
    for row in spawned_commitments(agreement_id):
        if row["commitment_type"] == commitment_type:
            return row
    raise AssertionError(f"no {commitment_type} commitment on agreement {agreement_id}")


# --------------------------------------------------------------------------
# Tier 7: invoicing and payment
# --------------------------------------------------------------------------
def draft_invoice(
    distributor_id: str,
    agreement_id: str,
    period_month: str,
    headers=None,
    **overrides,
) -> dict:
    """Create an invoice, threading the operator's live `version` into
    `expected_distributor_version` unless the caller overrides it."""
    expected = overrides.pop("expected_distributor_version", None)
    if expected is None:
        expected = distributor_version(distributor_id)
    payload = create_invoice_payload(
        distributor_id, agreement_id, period_month, expected, **overrides
    )
    return get_success_data(api_client.create_invoice(payload, headers or ACCOUNTANT))


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.invoice_lifecycle(invoice_id, {"action": "ISSUE"}, ACCOUNTANT))


def record_payment(invoice_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.invoice_lifecycle(
            invoice_id, {"action": "RECORD_PAYMENT", "amount_cents": amount_cents}, ACCOUNTANT
        )
    )


def write_off_invoice(invoice_id: str) -> dict:
    return get_success_data(
        api_client.invoice_lifecycle(invoice_id, {"action": "WRITE_OFF"}, ACCOUNTANT)
    )


def void_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.invoice_lifecycle(invoice_id, {"action": "VOID"}, ACCOUNTANT))


def setup_license_fee_invoice(
    distributor_overrides=None,
    agreement_overrides=None,
    report_overrides=None,
    invoice_overrides=None,
):
    """Accepted report then a DRAFT license-fee invoice for that same period.

    Returns (distributor, agreement, report, invoice).
    """
    distributor, agreement, report = setup_accepted_report(
        distributor_overrides, agreement_overrides, report_overrides
    )
    invoice = draft_invoice(
        distributor["id"],
        agreement["id"],
        report["period_month"],
        **(invoice_overrides or {}),
    )
    return fetch_distributor(distributor["id"]), agreement, report, invoice


def setup_issued_invoice(
    distributor_overrides=None,
    agreement_overrides=None,
    report_overrides=None,
    invoice_overrides=None,
):
    """As above but with the invoice pushed to ISSUED, so the operator's
    receivable balance and credit posture cascade have run.

    Returns (distributor, agreement, report, invoice).
    """
    distributor, agreement, report, invoice = setup_license_fee_invoice(
        distributor_overrides, agreement_overrides, report_overrides, invoice_overrides
    )
    invoice = issue_invoice(invoice["id"])
    return fetch_distributor(distributor["id"]), agreement, report, invoice


def setup_audit_recovery_invoice(
    audited_subscribers: int,
    distributor_overrides=None,
    agreement_overrides=None,
    report_overrides=None,
    engagement_overrides=None,
):
    """Audit chain to FINDINGS_ISSUED, then the single recovery invoice.

    The recovery invoice bills the month in which the findings were issued —
    the month of the current logical instant — not the reported month.

    Returns (distributor, agreement, report, engagement, invoice).
    """
    distributor, agreement, report, engagement, _finding = setup_engagement_with_findings_issued(
        audited_subscribers,
        distributor_overrides,
        agreement_overrides,
        report_overrides,
        engagement_overrides,
    )
    findings_month = read_clock()["current_utc"][:7]
    invoice = draft_invoice(
        distributor["id"],
        agreement["id"],
        findings_month,
        invoice_kind="AUDIT_RECOVERY",
        audit_engagement_id=engagement["id"],
    )
    return (
        fetch_distributor(distributor["id"]),
        agreement,
        report,
        fetch_engagement(engagement["id"]),
        invoice,
    )


# --------------------------------------------------------------------------
# Tier 8: renewal
# --------------------------------------------------------------------------
def start_renewal_analysis(agreement_id: str) -> dict:
    return get_success_data(
        api_client.agreement_renewal(agreement_id, {"action": "START_ANALYSIS"}, SALES)
    )


def offer_renewal(agreement_id: str) -> dict:
    return get_success_data(api_client.agreement_renewal(agreement_id, {"action": "OFFER"}, SALES))


def reopen_renewal_analysis(agreement_id: str) -> dict:
    return get_success_data(
        api_client.agreement_renewal(agreement_id, {"action": "REOPEN_ANALYSIS"}, SALES)
    )


def renew_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.agreement_renewal(agreement_id, {"action": "RENEW"}, SALES))


def lapse_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.agreement_renewal(agreement_id, {"action": "LAPSE"}, SALES))


def run_renewal_analysis(agreement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_renewal_analysis(
            create_renewal_analysis_payload(agreement_id, **overrides), SALES
        )
    )


def setup_agreement_in_renewal_analysis(
    distributor_overrides=None,
    agreement_overrides=None,
    report_overrides=None,
):
    """An executed agreement inside its renewal window, with one accepted
    report to anchor the leverage inputs, moved to RENEWAL_ANALYSIS.

    Returns (distributor, agreement, report).
    """
    distributor, agreement, report = setup_accepted_report(
        distributor_overrides, agreement_overrides, report_overrides
    )
    agreement = start_renewal_analysis(agreement["id"])
    return fetch_distributor(distributor["id"]), agreement, report


# --------------------------------------------------------------------------
# Tier 9: MFN clauses and benchmark peers
# --------------------------------------------------------------------------
def attach_mfn_clause(agreement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_mfn_clause(create_mfn_clause_payload(agreement_id, **overrides), SALES)
    )


def reset_mfn(clause_id: str, expected_agreement_version: int, action: str = "RESET") -> dict:
    """Re-run the benchmark (`RESET`) or waive the clause (`WAIVE`), guarded on
    the owning agreement's revision."""
    return get_success_data(
        api_client.reset_mfn_clause(
            clause_id,
            {"action": action, "expected_agreement_version": expected_agreement_version},
            SALES,
        )
    )


def waive_mfn(clause_id: str, expected_agreement_version: int) -> dict:
    return reset_mfn(clause_id, expected_agreement_version, action="WAIVE")


def setup_peer_agreement(
    base_license_fee_cents_per_sub: float,
    distributor_type: str = "CABLE_MSO",
    total_subscribers: int = 4_000_000,
    **agreement_overrides,
):
    """A second executed agreement, priced and typed so it can qualify (or be
    excluded) as an MFN benchmark peer. Returns (distributor, agreement)."""
    overrides = {"base_license_fee_cents_per_sub": base_license_fee_cents_per_sub}
    overrides.update(agreement_overrides)
    return setup_executed_agreement(
        {"distributor_type": distributor_type, "total_subscribers": total_subscribers},
        overrides,
    )
