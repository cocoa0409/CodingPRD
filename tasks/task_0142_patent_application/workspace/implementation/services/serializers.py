"""Serializers — convert in-memory dict rows to wire JSON.

PRD §2.4 contract:
  - Mutable entities (Applicant, Application, OfficeAction, Response, MaintenanceFee, PCTPhase)
    carry id + created_at + updated_at + version.
  - Append-only ledger entities (FeeTransaction, AuditEvent) carry only id + created_at.
  - SystemClock has only `now`.
"""

from db import store
from services.calculations import (
    compute_applicant_risk_score,
    compute_total_fees_paid,
)


# ---------------------------------------------------------------------------
# Applicant
# ---------------------------------------------------------------------------
def serialize_applicant(applicant: dict, *, recompute_score: bool = True) -> dict:
    """Serialize an Applicant. By default we recompute the risk score on read
    per SCAFFOLD §1.5 GET /applicants/{id} side effect.
    """
    risk_score = applicant.get("applicant_risk_score", 0)
    if recompute_score:
        risk_score = compute_applicant_risk_score(
            applicant["id"], store.applications, store.office_actions, store.maintenance_fees
        )
    return {
        "id": applicant["id"],
        "name": applicant["name"],
        "entity_size": applicant["entity_size"],
        "gross_income_cents": applicant.get("gross_income_cents"),
        "prior_filings_count": applicant.get("prior_filings_count"),
        "status": applicant["status"],
        "applicant_risk_score": risk_score,
        "created_at": applicant["created_at"],
        "updated_at": applicant["updated_at"],
        "version": applicant["version"],
    }


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def serialize_application(application: dict) -> dict:
    total_fees = compute_total_fees_paid(application["id"], store.fee_transactions)
    return {
        "id": application["id"],
        "applicant_id": application["applicant_id"],
        "application_type": application["application_type"],
        "title": application["title"],
        "claim_count": application["claim_count"],
        "independent_claim_count": application["independent_claim_count"],
        "status": application["status"],
        "filed_at": application.get("filed_at"),
        "granted_at": application.get("granted_at"),
        "expires_at": application.get("expires_at"),
        "parent_application_id": application.get("parent_application_id"),
        "continuation_type": application.get("continuation_type"),
        "total_fees_paid_cents": total_fees,
        "created_at": application["created_at"],
        "updated_at": application["updated_at"],
        "version": application["version"],
    }


# ---------------------------------------------------------------------------
# OfficeAction
# ---------------------------------------------------------------------------
def serialize_office_action(oa: dict) -> dict:
    return {
        "id": oa["id"],
        "application_id": oa["application_id"],
        "action_number": oa["action_number"],
        "action_type": oa["action_type"],
        "issued_at": oa["issued_at"],
        "response_deadline_at": oa["response_deadline_at"],
        "extended_deadline_at": oa["extended_deadline_at"],
        "status": oa["status"],
        "created_at": oa["created_at"],
        "updated_at": oa["updated_at"],
        "version": oa["version"],
    }


# ---------------------------------------------------------------------------
# Response (to an Office Action)
# ---------------------------------------------------------------------------
def serialize_response(r: dict) -> dict:
    return {
        "id": r["id"],
        "office_action_id": r["office_action_id"],
        "application_id": r["application_id"],
        "filed_at": r["filed_at"],
        "months_extension": r["months_extension"],
        "extension_fee_cents": r["extension_fee_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---------------------------------------------------------------------------
# FeeTransaction (append-only, no updated_at/version)
# ---------------------------------------------------------------------------
def serialize_fee_transaction(ft: dict) -> dict:
    return {
        "id": ft["id"],
        "application_id": ft["application_id"],
        "fee_category": ft["fee_category"],
        "amount_cents": ft["amount_cents"],
        "paid_at": ft["paid_at"],
        "maintenance_fee_id": ft.get("maintenance_fee_id"),
        "office_action_id": ft.get("office_action_id"),
        "created_at": ft["created_at"],
    }


# ---------------------------------------------------------------------------
# MaintenanceFee
# ---------------------------------------------------------------------------
def serialize_maintenance_fee(mf: dict) -> dict:
    return {
        "id": mf["id"],
        "application_id": mf["application_id"],
        "stage": mf["stage"],
        "window_open_at": mf["window_open_at"],
        "due_at": mf["due_at"],
        "grace_period_end_at": mf["grace_period_end_at"],
        "status": mf["status"],
        "required_fee_cents": mf.get("required_fee_cents"),
        "created_at": mf["created_at"],
        "updated_at": mf["updated_at"],
        "version": mf["version"],
    }


# ---------------------------------------------------------------------------
# PCTPhase
# ---------------------------------------------------------------------------
def serialize_pct_phase(p: dict) -> dict:
    return {
        "id": p["id"],
        "application_id": p["application_id"],
        "pct_filed_at": p["pct_filed_at"],
        "priority_date": p["priority_date"],
        "national_phase_deadline_at": p["national_phase_deadline_at"],
        "status": p["status"],
        "national_entered_at": p.get("national_entered_at"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# ---------------------------------------------------------------------------
# AuditEvent (append-only, no updated_at/version)
# ---------------------------------------------------------------------------
def serialize_audit_event(ae: dict) -> dict:
    return {
        "id": ae["id"],
        "application_id": ae["application_id"],
        "actor_role": ae["actor_role"],
        "actor_id": ae["actor_id"],
        "action": ae["action"],
        "details": ae["details"],
        "created_at": ae["created_at"],
    }
