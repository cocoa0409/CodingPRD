"""Composite setup builders.

Every test runs against a freshly started server with an empty database, so all
preconditions are constructed here from nothing, using only the endpoints the
PRD publishes.  Builders return the decoded `data` payloads so a test can go
straight to its assertions.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import CommissionApiClient
from .test_users import (
    make_analyst_headers,
    make_auditor_headers,
    make_broker_headers,
    make_chair_headers,
    make_counsel_headers,
    make_provider_admin_headers,
    make_respondent_headers,
    make_trustee_headers,
)


# ------------------------------------------------------------------ clock

def move_clock(client: CommissionApiClient, to_iso8601: str) -> str:
    """Move the logical clock and return the instant the server now reads."""
    data = get_success_data(client.set_clock(to_iso8601, make_analyst_headers()))
    return data["current_utc"]


# -------------------------------------------------------------- licensees

def create_applicant(
    client: CommissionApiClient,
    person_type: str = "SALESPERSON",
    full_name: str = "Dana Reyes",
    prelicense_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """A licence application sitting in `APPLICANT`."""
    return get_success_data(
        client.create_licensee(
            factories.licensee_payload(person_type, full_name, prelicense_hours),
            make_analyst_headers(),
        )
    )


def create_exam_passed_licensee(
    client: CommissionApiClient,
    person_type: str = "SALESPERSON",
    full_name: str = "Dana Reyes",
    score: int = 82,
    taken_on: str = "2026-08-01",
) -> Dict[str, Any]:
    """An applicant carried through the examination gate into `EXAM_PASSED`."""
    applicant = create_applicant(client, person_type, full_name)
    return get_success_data(
        client.record_exam_result(
            applicant["id"], factories.exam_result_payload(score, taken_on), make_analyst_headers()
        )
    )


def read_licensee(client: CommissionApiClient, licensee_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_licensee(licensee_id, make_analyst_headers()))


# ------------------------------------------------------------- brokerages

def read_brokerage(client: CommissionApiClient, brokerage_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_brokerage(brokerage_id, make_analyst_headers()))


def register_brokerage(
    client: CommissionApiClient,
    designated_broker_id: str,
    name: str = "Raefield Realty",
    trust_account_required: bool = True,
    record_retention_years: int = 5,
) -> Dict[str, Any]:
    """A brokerage registered in `PENDING`."""
    return get_success_data(
        client.create_brokerage(
            factories.brokerage_payload(
                name, designated_broker_id, trust_account_required, record_retention_years
            ),
            make_analyst_headers(),
        )
    )


def open_trust_account(
    client: CommissionApiClient,
    brokerage_id: str,
    account_type: str = "ESCROW",
    bank_name: str = "Harborline Savings",
) -> Dict[str, Any]:
    """A trust account opened in `OPEN` against a pending or active brokerage."""
    return get_success_data(
        client.create_trust_account(
            brokerage_id,
            factories.trust_account_payload(bank_name, account_type),
            make_analyst_headers(),
        )
    )


def activate(client: CommissionApiClient, brokerage_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.activate_brokerage(brokerage_id, make_analyst_headers())
    )


def affiliate(
    client: CommissionApiClient,
    licensee_id: str,
    brokerage_id: str,
    supervising_broker_id: str,
    expected_brokerage_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Affiliate or transfer, reading the firm's live version when none is given."""
    if expected_brokerage_version is None:
        expected_brokerage_version = read_brokerage(client, brokerage_id)["version"]
    return get_success_data(
        client.create_affiliation(
            licensee_id,
            factories.affiliation_payload(
                brokerage_id, supervising_broker_id, expected_brokerage_version
            ),
            make_analyst_headers(),
        )
    )


def bootstrap_active_brokerage(
    client: CommissionApiClient,
    name: str = "Raefield Realty",
    broker_name: str = "Corin Raefield",
    trust_account_required: bool = True,
    open_escrow: bool = True,
    record_retention_years: int = 5,
) -> Dict[str, Any]:
    """A live firm with its designated broker seated by self-supervision.

    The broker passes the examination, registers the firm, an escrow account is
    opened while the firm is still `PENDING`, the firm is activated, and the
    broker then affiliates naming themselves — the bootstrap exemption of §3.3 —
    which is what actually issues their licence and lifts the affiliate count
    off zero.
    """
    broker = create_exam_passed_licensee(client, "BROKER", broker_name)
    brokerage = register_brokerage(
        client, broker["id"], name, trust_account_required, record_retention_years
    )
    account = open_trust_account(client, brokerage["id"]) if open_escrow else None
    brokerage = activate(client, brokerage["id"])
    broker = affiliate(client, broker["id"], brokerage["id"], broker["id"])
    return {
        "broker": broker,
        "brokerage": read_brokerage(client, brokerage["id"]),
        "account": account,
    }


def affiliate_new_salesperson(
    client: CommissionApiClient,
    brokerage_id: str,
    supervising_broker_id: str,
    full_name: str = "Dana Reyes",
) -> Dict[str, Any]:
    """A salesperson taken from application all the way to `ACTIVE`."""
    salesperson = create_exam_passed_licensee(client, "SALESPERSON", full_name)
    return affiliate(client, salesperson["id"], brokerage_id, supervising_broker_id)


# --------------------------------------------------------- trust accounting

def read_trust_account(client: CommissionApiClient, account_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_trust_account(account_id, make_analyst_headers()))


def append_ledger_entry(
    client: CommissionApiClient,
    account_id: str,
    entry_type: str,
    amount_cents: int,
    effective_date: str,
    transaction_reference: str,
    cleared_date: Optional[str] = None,
    memo: Optional[str] = None,
    expected_trust_account_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Append one immutable ledger row, reading the account's live version."""
    if expected_trust_account_version is None:
        expected_trust_account_version = read_trust_account(client, account_id)["version"]
    return get_success_data(
        client.create_ledger_entry(
            account_id,
            factories.ledger_entry_payload(
                entry_type,
                amount_cents,
                effective_date,
                transaction_reference,
                expected_trust_account_version,
                cleared_date=cleared_date,
                memo=memo,
            ),
            headers or make_analyst_headers(),
        )
    )


def list_ledger(client: CommissionApiClient, account_id: str) -> List[Dict[str, Any]]:
    body = client.list_ledger_entries(account_id, make_analyst_headers()).json()
    return body["data"]


# -------------------------------------------------------------- audits

def schedule_audit(
    client: CommissionApiClient,
    account_id: str,
    auditor_user_id: str,
    basis: str = "BOOK",
    as_of_date: str = "2026-08-31",
    fieldwork_start_at: str = "2026-08-10T09:00:00Z",
    fieldwork_end_at: str = "2026-08-10T17:00:00Z",
) -> Dict[str, Any]:
    return get_success_data(
        client.schedule_audit(
            account_id,
            factories.audit_payload(
                auditor_user_id, basis, as_of_date, fieldwork_start_at, fieldwork_end_at
            ),
            make_auditor_headers(auditor_user_id),
        )
    )


def start_fieldwork(
    client: CommissionApiClient,
    audit_id: str,
    auditor_user_id: str,
    bank_statement_balance_cents: Optional[int] = None,
    cleared_through_date: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.open_fieldwork(
            audit_id,
            factories.fieldwork_payload(bank_statement_balance_cents, cleared_through_date),
            make_auditor_headers(auditor_user_id),
        )
    )


def dispose_audit(
    client: CommissionApiClient,
    audit_id: str,
    auditor_user_id: str,
    action: str,
    remediation_days: Optional[int] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.audit_disposition(
            audit_id,
            factories.audit_disposition_payload(action, remediation_days, note),
            make_auditor_headers(auditor_user_id),
        )
    )


# ----------------------------------------------------------- complaints

def read_complaint(client: CommissionApiClient, complaint_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_complaint(complaint_id, make_analyst_headers()))


def file_complaint(
    client: CommissionApiClient,
    respondent_licensee_id: str,
    allegation_type: str = "TRUST_SHORTAGE",
    alleged_loss_cents: int = 0,
    complainant_name: str = "Marlow Estate",
    narrative: Optional[str] = None,
) -> Dict[str, Any]:
    """A complaint in `SUBMITTED`, scored under the intake variant."""
    return get_success_data(
        client.create_complaint(
            factories.complaint_payload(
                respondent_licensee_id,
                allegation_type,
                alleged_loss_cents,
                complainant_name,
                narrative,
            ),
            make_counsel_headers(),
        )
    )


def dispose_complaint(
    client: CommissionApiClient,
    complaint_id: str,
    disposition: str,
    investigator_user_id: Optional[str] = None,
    counsel_user_id: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.complaint_disposition(
            complaint_id,
            factories.complaint_disposition_payload(disposition, investigator_user_id, note),
            make_counsel_headers(counsel_user_id) if counsel_user_id else make_counsel_headers(),
        )
    )


def complaint_at_probable_cause(
    client: CommissionApiClient,
    respondent_licensee_id: str,
    allegation_type: str = "TRUST_SHORTAGE",
    alleged_loss_cents: int = 0,
    investigator_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A complaint screened into investigation and then found probable cause."""
    complaint = file_complaint(
        client, respondent_licensee_id, allegation_type, alleged_loss_cents
    )
    dispose_complaint(client, complaint["id"], "INVESTIGATE", investigator_user_id)
    return dispose_complaint(client, complaint["id"], "PROBABLE_CAUSE")


# ------------------------------------------------------ consent agreements

def offer_consent(
    client: CommissionApiClient,
    complaint_id: str,
    proposed_sanction_type: str = "FINE",
    proposed_fine_cents: int = 250000,
    proposed_suspension_days: int = 0,
    counsel_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Open consent negotiation by offering round one."""
    headers = make_counsel_headers(counsel_user_id) if counsel_user_id else make_counsel_headers()
    return get_success_data(
        client.create_consent_agreement(
            complaint_id,
            factories.consent_offer_payload(
                proposed_sanction_type, proposed_fine_cents, proposed_suspension_days
            ),
            headers,
        )
    )


def respondent_replies(
    client: CommissionApiClient,
    agreement_id: str,
    respondent_licensee_id: str,
    action: str,
    counter_fine_cents: Optional[int] = None,
    counter_suspension_days: Optional[int] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.respondent_response(
            agreement_id,
            factories.respondent_response_payload(
                action, counter_fine_cents, counter_suspension_days
            ),
            make_respondent_headers(respondent_licensee_id),
        )
    )


def commission_replies(
    client: CommissionApiClient,
    agreement_id: str,
    action: str,
    counsel_user_id: Optional[str] = None,
    proposed_fine_cents: Optional[int] = None,
    proposed_suspension_days: Optional[int] = None,
) -> Dict[str, Any]:
    headers = make_counsel_headers(counsel_user_id) if counsel_user_id else make_counsel_headers()
    return get_success_data(
        client.commission_action(
            agreement_id,
            factories.commission_action_payload(
                action, proposed_fine_cents, proposed_suspension_days
            ),
            headers,
        )
    )


# --------------------------------------------------------------- hearings

def schedule_hearing(
    client: CommissionApiClient,
    complaint_id: str,
    panel_chair_user_id: str,
    scheduled_start_at: str = "2026-08-20T09:00:00Z",
    scheduled_end_at: str = "2026-08-20T11:00:00Z",
    hearing_room: str = "ROOM_A",
    counsel_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = make_counsel_headers(counsel_user_id) if counsel_user_id else make_counsel_headers()
    return get_success_data(
        client.schedule_hearing(
            complaint_id,
            factories.hearing_payload(
                panel_chair_user_id, scheduled_start_at, scheduled_end_at, hearing_room
            ),
            headers,
        )
    )


def dispose_hearing(
    client: CommissionApiClient,
    hearing_id: str,
    panel_chair_user_id: str,
    action: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.hearing_disposition(
            hearing_id,
            factories.hearing_disposition_payload(action, **kwargs),
            make_chair_headers(panel_chair_user_id),
        )
    )


# ------------------------------------------------------- sanction orders

def read_sanction_order(client: CommissionApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_sanction_order(order_id, make_analyst_headers()))


def orders_for_complaint(client: CommissionApiClient, complaint_id: str) -> List[Dict[str, Any]]:
    body = client.list_sanction_orders(
        make_analyst_headers(), params={"complaint_id": complaint_id}
    ).json()
    return body["data"]


def only_order_for_complaint(client: CommissionApiClient, complaint_id: str) -> Dict[str, Any]:
    orders = orders_for_complaint(client, complaint_id)
    assert len(orders) == 1, f"expected exactly one order on the complaint, saw {len(orders)}"
    return orders[0]


def issue_order_by_consent(
    client: CommissionApiClient,
    complaint_id: str,
    respondent_licensee_id: str,
    sanction_type: str = "FINE",
    fine_cents: int = 250000,
    suspension_days: int = 0,
    offered_by_user_id: Optional[str] = None,
    executed_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Offer, accept and execute a consent agreement, yielding its order.

    The executing counsel must differ from the counsel who made the offer, so
    the two identities are kept apart by default.
    """
    from .test_users import COUNSEL_USER_ID, SECOND_COUNSEL_USER_ID

    offerer = offered_by_user_id or COUNSEL_USER_ID
    executor = executed_by_user_id or SECOND_COUNSEL_USER_ID
    agreement = offer_consent(
        client, complaint_id, sanction_type, fine_cents, suspension_days, counsel_user_id=offerer
    )
    respondent_replies(client, agreement["id"], respondent_licensee_id, "ACCEPT")
    commission_replies(client, agreement["id"], "EXECUTE", counsel_user_id=executor)
    return only_order_for_complaint(client, complaint_id)


def issue_order_by_hearing(
    client: CommissionApiClient,
    complaint_id: str,
    panel_chair_user_id: str,
    sanction_type: str = "REVOCATION",
    fine_cents: int = 0,
    suspension_days: int = 0,
    scheduled_start_at: str = "2026-08-20T09:00:00Z",
    scheduled_end_at: str = "2026-08-20T11:00:00Z",
    hearing_room: str = "ROOM_A",
    convene_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule, convene and decide a hearing, yielding its order and hearing."""
    hearing = schedule_hearing(
        client,
        complaint_id,
        panel_chair_user_id,
        scheduled_start_at,
        scheduled_end_at,
        hearing_room,
    )
    move_clock(client, convene_at or scheduled_start_at)
    dispose_hearing(client, hearing["id"], panel_chair_user_id, "CONVENE")
    dispose_hearing(
        client,
        hearing["id"],
        panel_chair_user_id,
        "DECIDE",
        finding="VIOLATION_FOUND",
        sanction_type=sanction_type,
        fine_cents=fine_cents,
        suspension_days=suspension_days,
    )
    return {
        "hearing": get_success_data(client.get_hearing(hearing["id"], make_analyst_headers())),
        "order": only_order_for_complaint(client, complaint_id),
    }


def pay_fine(
    client: CommissionApiClient,
    order_id: str,
    amount_cents: int,
    paid_on: str = "2026-08-15",
) -> Dict[str, Any]:
    return get_success_data(
        client.create_fine_payment(
            order_id, factories.fine_payment_payload(amount_cents, paid_on), make_analyst_headers()
        )
    )


# -------------------------------------------------------- recovery fund

def read_fund(client: CommissionApiClient) -> Dict[str, Any]:
    return get_success_data(client.get_recovery_fund(make_trustee_headers()))


def appropriate(client: CommissionApiClient, amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        client.create_appropriation(
            factories.appropriation_payload(amount_cents), make_trustee_headers()
        )
    )


def file_claim(
    client: CommissionApiClient,
    order_id: str,
    claimed_loss_cents: int,
    claimant_name: str = "Ines Vantor",
) -> Dict[str, Any]:
    return get_success_data(
        client.create_recovery_claim(
            order_id,
            factories.recovery_claim_payload(claimed_loss_cents, claimant_name),
            make_trustee_headers(),
        )
    )


def claims_for_order(client: CommissionApiClient, order_id: str) -> List[Dict[str, Any]]:
    body = client.list_recovery_claims(order_id, make_trustee_headers()).json()
    return body["data"]


def disburse(
    client: CommissionApiClient,
    order_id: str,
    expected_recovery_fund_version: Optional[int] = None,
):
    """Run the award waterfall; the raw response is returned for validation."""
    if expected_recovery_fund_version is None:
        expected_recovery_fund_version = read_fund(client)["version"]
    return client.run_disbursement(
        factories.disbursement_payload(order_id, expected_recovery_fund_version),
        make_trustee_headers(),
    )


# ------------------------------------------------------ education oversight

def read_provider(client: CommissionApiClient, provider_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_education_provider(provider_id, make_analyst_headers()))


def read_instructor(client: CommissionApiClient, instructor_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_instructor(instructor_id, make_analyst_headers()))


def register_provider(
    client: CommissionApiClient,
    name: str = "Cascade Realty Institute",
    admin_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """An education provider registered in `PENDING`."""
    return get_success_data(
        client.create_education_provider(
            factories.education_provider_payload(name, admin_user_id), make_analyst_headers()
        )
    )


def approve_provider(
    client: CommissionApiClient, provider_id: str, approval_years: Optional[int] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.approve_education_provider(
            provider_id, make_analyst_headers(), factories.provider_approval_payload(approval_years)
        )
    )


def register_instructor(
    client: CommissionApiClient,
    provider_id: str,
    full_name: str = "Peyton Halloway",
    credential_type: str = "SUBJECT_EXPERT",
    licensee_id: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_instructor(
            provider_id,
            factories.instructor_payload(full_name, credential_type, licensee_id),
            make_analyst_headers(),
        )
    )


def approve_instructor(client: CommissionApiClient, instructor_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.approve_instructor(instructor_id, make_analyst_headers())
    )


def approved_provider_with_instructor(
    client: CommissionApiClient,
    provider_name: str = "Cascade Realty Institute",
    instructor_name: str = "Peyton Halloway",
    admin_user_id: Optional[str] = None,
    credential_type: str = "SUBJECT_EXPERT",
    licensee_id: Optional[str] = None,
) -> Dict[str, Any]:
    """An `APPROVED` provider carrying one `APPROVED` instructor."""
    provider = approve_provider(
        client, register_provider(client, provider_name, admin_user_id)["id"]
    )
    instructor = register_instructor(
        client, provider["id"], instructor_name, credential_type, licensee_id
    )
    instructor = approve_instructor(client, instructor["id"])
    return {"provider": read_provider(client, provider["id"]), "instructor": instructor}


def record_completion(
    client: CommissionApiClient,
    licensee_id: str,
    instructor_id: str,
    education_provider_id: str,
    credit_hours: int = 12,
    completed_on: str = "2026-08-01",
    course_type: str = "CE_CORE",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_course_completion(
            factories.course_completion_payload(
                licensee_id,
                instructor_id,
                education_provider_id,
                credit_hours,
                completed_on,
                course_type,
            ),
            headers or make_analyst_headers(),
        )
    )


def completions_for_licensee(
    client: CommissionApiClient, licensee_id: str
) -> List[Dict[str, Any]]:
    body = client.list_course_completions(
        make_analyst_headers(), params={"licensee_id": licensee_id}
    ).json()
    return body["data"]


# ----------------------------------------------------- advertising names

def read_advertising_name(client: CommissionApiClient, name_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_advertising_name(name_id, make_analyst_headers()))


def submit_advertising_name(
    client: CommissionApiClient,
    brokerage_id: str,
    name_text: str,
    kind: str = "DBA",
    team_lead_licensee_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_advertising_name(
            factories.advertising_name_payload(
                brokerage_id, name_text, kind, team_lead_licensee_id
            ),
            headers or make_analyst_headers(),
        )
    )


def review_advertising_name(
    client: CommissionApiClient,
    name_id: str,
    decision: str,
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.review_advertising_name(
            name_id,
            factories.advertising_review_payload(decision, rejection_reason),
            make_analyst_headers(),
        )
    )


def names_for_brokerage(client: CommissionApiClient, brokerage_id: str) -> List[Dict[str, Any]]:
    body = client.list_advertising_names(
        make_analyst_headers(), params={"brokerage_id": brokerage_id}
    ).json()
    return body["data"]


# ------------------------------------------------------------- sweeps

def run_sweep(client: CommissionApiClient) -> Dict[str, Any]:
    return get_success_data(client.run_compliance_sweep(make_analyst_headers()))


# ------------------------------------------------- licence status changes

def status_change(
    client: CommissionApiClient,
    licensee_id: str,
    action: str,
    brokerage_id: Optional[str] = None,
    supervising_broker_id: Optional[str] = None,
    reinstatement_fee_paid_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
):
    """Park or revive a licence; the raw response is returned for validation."""
    return client.create_status_change(
        licensee_id,
        factories.status_change_payload(
            action, brokerage_id, supervising_broker_id, reinstatement_fee_paid_cents
        ),
        headers or make_analyst_headers(),
    )


def go_inactive(
    client: CommissionApiClient, licensee_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Park an active licence, leaving `inactive_since` stamped."""
    return get_success_data(status_change(client, licensee_id, "GO_INACTIVE", headers=headers))


def read_audit(client: CommissionApiClient, audit_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_trust_audit(audit_id, make_analyst_headers()))
