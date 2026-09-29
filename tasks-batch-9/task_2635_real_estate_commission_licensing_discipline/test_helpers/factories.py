"""Request-payload builders.

Each builder emits only the client-supplied fields the PRD names for that
endpoint; server-derived fields are never sent.  Optional fields are omitted
unless the caller supplies them, so a test can prove a default.
"""

from typing import Any, Dict, Optional

from .constants import (
    PRELICENSE_HOURS_BROKER,
    PRELICENSE_HOURS_SALESPERSON,
    RETENTION_YEARS_DEFAULT,
)


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


# ------------------------------------------------------------- licensees

def licensee_payload(
    person_type: str = "SALESPERSON",
    full_name: str = "Dana Reyes",
    prelicense_hours: Optional[int] = None,
) -> Dict[str, Any]:
    if prelicense_hours is None:
        prelicense_hours = (
            PRELICENSE_HOURS_BROKER if person_type == "BROKER" else PRELICENSE_HOURS_SALESPERSON
        )
    return {
        "person_type": person_type,
        "full_name": full_name,
        "prelicense_hours": prelicense_hours,
    }


def exam_result_payload(score: int = 80, taken_on: str = "2026-08-01") -> Dict[str, Any]:
    return {"score": score, "taken_on": taken_on}


def affiliation_payload(
    brokerage_id: str,
    supervising_broker_id: str,
    expected_brokerage_version: int,
) -> Dict[str, Any]:
    return {
        "brokerage_id": brokerage_id,
        "supervising_broker_id": supervising_broker_id,
        "expected_brokerage_version": expected_brokerage_version,
    }


def status_change_payload(
    action: str,
    brokerage_id: Optional[str] = None,
    supervising_broker_id: Optional[str] = None,
    reinstatement_fee_paid_cents: Optional[int] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "action": action,
            "brokerage_id": brokerage_id,
            "supervising_broker_id": supervising_broker_id,
            "reinstatement_fee_paid_cents": reinstatement_fee_paid_cents,
        }
    )


# ------------------------------------------------------------ brokerages

def brokerage_payload(
    name: str,
    designated_broker_id: str,
    trust_account_required: bool = True,
    record_retention_years: int = RETENTION_YEARS_DEFAULT,
) -> Dict[str, Any]:
    return {
        "name": name,
        "designated_broker_id": designated_broker_id,
        "trust_account_required": trust_account_required,
        "record_retention_years": record_retention_years,
    }


def activation_payload(attestation_note: Optional[str] = None) -> Dict[str, Any]:
    return _prune({"attestation_note": attestation_note})


# --------------------------------------------------------- trust accounts

def trust_account_payload(
    bank_name: str = "Harborline Savings", account_type: str = "ESCROW"
) -> Dict[str, Any]:
    return {"bank_name": bank_name, "account_type": account_type}


def ledger_entry_payload(
    entry_type: str,
    amount_cents: int,
    effective_date: str,
    transaction_reference: str,
    expected_trust_account_version: int,
    cleared_date: Optional[str] = None,
    memo: Optional[str] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "effective_date": effective_date,
            "cleared_date": cleared_date,
            "transaction_reference": transaction_reference,
            "memo": memo,
            "expected_trust_account_version": expected_trust_account_version,
        }
    )


# ----------------------------------------------------------- trust audits

def audit_payload(
    auditor_user_id: str,
    basis: str,
    as_of_date: str,
    fieldwork_start_at: str,
    fieldwork_end_at: str,
) -> Dict[str, Any]:
    return {
        "auditor_user_id": auditor_user_id,
        "basis": basis,
        "as_of_date": as_of_date,
        "fieldwork_start_at": fieldwork_start_at,
        "fieldwork_end_at": fieldwork_end_at,
    }


def fieldwork_payload(
    bank_statement_balance_cents: Optional[int] = None,
    cleared_through_date: Optional[str] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "bank_statement_balance_cents": bank_statement_balance_cents,
            "cleared_through_date": cleared_through_date,
        }
    )


def audit_disposition_payload(
    action: str, remediation_days: Optional[int] = None, note: Optional[str] = None
) -> Dict[str, Any]:
    return _prune({"action": action, "remediation_days": remediation_days, "note": note})


# ------------------------------------------------------------- complaints

def complaint_payload(
    respondent_licensee_id: str,
    allegation_type: str = "TRUST_SHORTAGE",
    alleged_loss_cents: int = 0,
    complainant_name: str = "Marlow Estate",
    narrative: Optional[str] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "complainant_name": complainant_name,
            "respondent_licensee_id": respondent_licensee_id,
            "allegation_type": allegation_type,
            "alleged_loss_cents": alleged_loss_cents,
            "narrative": narrative,
        }
    )


def complaint_disposition_payload(
    disposition: str, investigator_user_id: Optional[str] = None, note: Optional[str] = None
) -> Dict[str, Any]:
    return _prune(
        {
            "disposition": disposition,
            "investigator_user_id": investigator_user_id,
            "note": note,
        }
    )


def amendment_payload(
    amendment_note: str = "Revised loss figure supplied by the complainant.",
    amended_alleged_loss_cents: Optional[int] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "amendment_note": amendment_note,
            "amended_alleged_loss_cents": amended_alleged_loss_cents,
        }
    )


# ------------------------------------------------------ consent agreements

def consent_offer_payload(
    proposed_sanction_type: str = "FINE",
    proposed_fine_cents: int = 250000,
    proposed_suspension_days: int = 0,
) -> Dict[str, Any]:
    return {
        "proposed_sanction_type": proposed_sanction_type,
        "proposed_fine_cents": proposed_fine_cents,
        "proposed_suspension_days": proposed_suspension_days,
    }


def respondent_response_payload(
    action: str,
    counter_fine_cents: Optional[int] = None,
    counter_suspension_days: Optional[int] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "action": action,
            "counter_fine_cents": counter_fine_cents,
            "counter_suspension_days": counter_suspension_days,
        }
    )


def commission_action_payload(
    action: str,
    proposed_fine_cents: Optional[int] = None,
    proposed_suspension_days: Optional[int] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "action": action,
            "proposed_fine_cents": proposed_fine_cents,
            "proposed_suspension_days": proposed_suspension_days,
        }
    )


# --------------------------------------------------------------- hearings

def hearing_payload(
    panel_chair_user_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    hearing_room: str = "ROOM_A",
) -> Dict[str, Any]:
    return {
        "panel_chair_user_id": panel_chair_user_id,
        "hearing_room": hearing_room,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }


def hearing_disposition_payload(
    action: str,
    finding: Optional[str] = None,
    sanction_type: Optional[str] = None,
    fine_cents: Optional[int] = None,
    suspension_days: Optional[int] = None,
    rescheduled_start_at: Optional[str] = None,
    rescheduled_end_at: Optional[str] = None,
    hearing_room: Optional[str] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "action": action,
            "finding": finding,
            "sanction_type": sanction_type,
            "fine_cents": fine_cents,
            "suspension_days": suspension_days,
            "rescheduled_start_at": rescheduled_start_at,
            "rescheduled_end_at": rescheduled_end_at,
            "hearing_room": hearing_room,
        }
    )


# ------------------------------------------------- orders and recovery fund

def fine_payment_payload(amount_cents: int, paid_on: str = "2026-08-15") -> Dict[str, Any]:
    return {"amount_cents": amount_cents, "paid_on": paid_on}


def vacatur_payload(vacatur_reason: str = "Reconsidered on the record.") -> Dict[str, Any]:
    return {"vacatur_reason": vacatur_reason}


def recovery_claim_payload(
    claimed_loss_cents: int, claimant_name: str = "Ines Vantor"
) -> Dict[str, Any]:
    return {"claimant_name": claimant_name, "claimed_loss_cents": claimed_loss_cents}


def appropriation_payload(
    amount_cents: int, appropriation_note: Optional[str] = None
) -> Dict[str, Any]:
    return _prune({"amount_cents": amount_cents, "appropriation_note": appropriation_note})


def disbursement_payload(
    sanction_order_id: str, expected_recovery_fund_version: int
) -> Dict[str, Any]:
    return {
        "sanction_order_id": sanction_order_id,
        "expected_recovery_fund_version": expected_recovery_fund_version,
    }


# ------------------------------------------------------ education oversight

def education_provider_payload(
    name: str = "Cascade Realty Institute", admin_user_id: Optional[str] = None
) -> Dict[str, Any]:
    return _prune({"name": name, "admin_user_id": admin_user_id})


def provider_approval_payload(approval_years: Optional[int] = None) -> Dict[str, Any]:
    return _prune({"approval_years": approval_years})


def instructor_payload(
    full_name: str = "Peyton Halloway",
    credential_type: str = "SUBJECT_EXPERT",
    licensee_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "licensee_id": licensee_id,
            "full_name": full_name,
            "credential_type": credential_type,
        }
    )


def instructor_approval_payload(approval_note: Optional[str] = None) -> Dict[str, Any]:
    return _prune({"approval_note": approval_note})


def course_completion_payload(
    licensee_id: str,
    instructor_id: str,
    education_provider_id: str,
    credit_hours: int = 12,
    completed_on: str = "2026-08-01",
    course_type: str = "CE_CORE",
) -> Dict[str, Any]:
    return {
        "licensee_id": licensee_id,
        "instructor_id": instructor_id,
        "education_provider_id": education_provider_id,
        "course_type": course_type,
        "credit_hours": credit_hours,
        "completed_on": completed_on,
    }


# ----------------------------------------------------- advertising names

def advertising_name_payload(
    brokerage_id: str,
    name_text: str,
    kind: str = "DBA",
    team_lead_licensee_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _prune(
        {
            "brokerage_id": brokerage_id,
            "team_lead_licensee_id": team_lead_licensee_id,
            "kind": kind,
            "name_text": name_text,
        }
    )


def advertising_review_payload(
    decision: str, rejection_reason: Optional[str] = None
) -> Dict[str, Any]:
    return _prune({"decision": decision, "rejection_reason": rejection_reason})
