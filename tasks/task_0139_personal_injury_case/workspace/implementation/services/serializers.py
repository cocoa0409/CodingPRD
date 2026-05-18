"""Serializers that convert internal entity dicts to API-shape dicts.

Each serializer maps the in-store representation (which may carry helper
fields like `_sol_date`) to the public field set defined in SCAFFOLD §1.1.
ContingencyFeeAgreement and SettlementDisbursement explicitly omit
updated_at / version per PRD §2.4.
"""
from __future__ import annotations

from utils import iso_now


# ── Helpers ────────────────────────────────────────────────────────────────


def _ts(dt):
    return iso_now(dt) if dt is not None else None


def _common(row):
    """Standard common-fields envelope: id / created_at / updated_at / version."""
    return {
        "id": row["id"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


# ── Per-entity ─────────────────────────────────────────────────────────────


def client_to_dict(row):
    return {
        **_common(row),
        "full_name": row["full_name"],
        "date_of_birth": row["date_of_birth"],
        "is_minor_at_incident": row.get("is_minor_at_incident"),
        "contact_email": row["contact_email"],
        "state_of_residence": row["state_of_residence"],
    }


def case_to_dict(row):
    return {
        **_common(row),
        "client_id": row["client_id"],
        "incident_date": row["incident_date"],
        "incident_type": row["incident_type"],
        "jurisdiction_state": row["jurisdiction_state"],
        "status": row["status"],
        "sol_deadline": row["sol_deadline"],
        "sol_tolled_days": row["sol_tolled_days"],
        "assigned_attorney_id": row.get("assigned_attorney_id"),
        "assigned_paralegal_id": row.get("assigned_paralegal_id"),
        "gross_settlement_cents": row["gross_settlement_cents"],
        "case_costs_cents": row["case_costs_cents"],
        "filed_in_court": row["filed_in_court"],
        "disbursement_approved_by": row.get("disbursement_approved_by"),
    }


def medical_request_to_dict(row):
    return {
        **_common(row),
        "case_id": row["case_id"],
        "provider_name": row["provider_name"],
        "date_of_service_start": row["date_of_service_start"],
        "date_of_service_end": row["date_of_service_end"],
        "status": row["status"],
        "sent_at": _ts(row.get("sent_at")),
        "received_at": _ts(row.get("received_at")),
        "billed_amount_cents": row.get("billed_amount_cents", 0),
    }


def damages_to_dict(row):
    return {
        **_common(row),
        "case_id": row["case_id"],
        "medical_bills_cents": row["medical_bills_cents"],
        "lost_wages_cents": row["lost_wages_cents"],
        "property_damage_cents": row["property_damage_cents"],
        "pain_suffering_method": row["pain_suffering_method"],
        "multiplier_value": row.get("multiplier_value"),
        "per_diem_rate_cents": row.get("per_diem_rate_cents", 0),
        "per_diem_days": row.get("per_diem_days", 0),
        "pain_suffering_cents": row["pain_suffering_cents"],
        "total_damages_cents": row["total_damages_cents"],
    }


def lien_to_dict(row):
    return {
        **_common(row),
        "case_id": row["case_id"],
        "lienholder_name": row["lienholder_name"],
        "lien_type": row["lien_type"],
        "face_amount_cents": row["face_amount_cents"],
        "negotiated_amount_cents": row.get("negotiated_amount_cents"),
        "status": row["status"],
        "final_paid_amount_cents": row.get("final_paid_amount_cents"),
        "priority_rank": row.get("priority_rank"),
    }


def demand_letter_to_dict(row):
    return {
        **_common(row),
        "case_id": row["case_id"],
        "demanded_amount_cents": row["demanded_amount_cents"],
        "snapshot_total_damages_cents": row["snapshot_total_damages_cents"],
        "snapshot_damages_version": row["snapshot_damages_version"],
        "status": row["status"],
        "sent_at": _ts(row.get("sent_at")),
        "response_due_at": _ts(row.get("response_due_at")),
    }


def settlement_offer_to_dict(row):
    return {
        **_common(row),
        "case_id": row["case_id"],
        "predecessor_offer_id": row.get("predecessor_offer_id"),
        "offer_party": row["offer_party"],
        "amount_cents": row["amount_cents"],
        "status": row["status"],
        "expires_at": _ts(row["expires_at"]),
        "round_number": row["round_number"],
    }


def fee_agreement_to_dict(row):
    # PRD §2.4: ContingencyFeeAgreement carries only id + created_at.
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "pre_suit_rate_bps": row["pre_suit_rate_bps"],
        "post_suit_rate_bps": row["post_suit_rate_bps"],
        "trial_rate_bps": row["trial_rate_bps"],
        "signed_at": _ts(row["signed_at"]),
        "created_at": _ts(row["created_at"]),
    }


def court_event_to_dict(row):
    return {
        **_common(row),
        "case_id": row["case_id"],
        "event_type": row["event_type"],
        "scheduled_at": _ts(row["scheduled_at"]),
        "duration_minutes": row["duration_minutes"],
        "courtroom": row.get("courtroom"),
        "status": row["status"],
        "award_amount_cents": row.get("award_amount_cents"),
    }


def disbursement_to_dict(row):
    # PRD §2.4: SettlementDisbursement carries only id + created_at.
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "gross_amount_cents": row["gross_amount_cents"],
        "attorney_fee_cents": row["attorney_fee_cents"],
        "case_costs_cents": row["case_costs_cents"],
        "total_lien_payment_cents": row["total_lien_payment_cents"],
        "client_net_cents": row["client_net_cents"],
        "strategy": row["strategy"],
        "approved_by": row["approved_by"],
        "created_at": _ts(row["created_at"]),
    }
