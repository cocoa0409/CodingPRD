"""Entity -> JSON dict serializers."""
from __future__ import annotations

from typing import Any


def _common(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_participant(d: dict[str, Any]) -> dict[str, Any]:
    out = _common(d)
    out.update(
        {
            "full_name": d["full_name"],
            "date_of_birth": d["date_of_birth"],
            "tax_status": d["tax_status"],
            "is_deceased": d["is_deceased"],
            "date_of_death": d.get("date_of_death"),
        }
    )
    return out


def serialize_account(d: dict[str, Any]) -> dict[str, Any]:
    from ..store import store
    out = _common(d)
    out.update(
        {
            "participant_id": d["participant_id"],
            "account_type": d["account_type"],
            "status": d["status"],
            "balance_cents": d["balance_cents"],
            "ytd_contribution_cents": d["ytd_contribution_cents"],
            "tax_year": d["tax_year"],
            "prior_year_end_balance_cents": d["prior_year_end_balance_cents"],
            "inherited_from_participant_id": d.get("inherited_from_participant_id"),
            "inheritance_start_date": d.get("inheritance_start_date"),
            "beneficiary_claim_id": store().claim_by_account.get(d["id"]),
        }
    )
    return out


def serialize_contribution(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "account_id": d["account_id"],
        "amount_cents": d["amount_cents"],
        "contribution_type": d["contribution_type"],
        "tax_year": d["tax_year"],
        "status": d["status"],
        "reversed_at": d.get("reversed_at"),
    }


def serialize_distribution(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "account_id": d["account_id"],
        "gross_amount_cents": d["gross_amount_cents"],
        "distribution_reason": d["distribution_reason"],
        "federal_withholding_cents": d["federal_withholding_cents"],
        "net_amount_cents": d["net_amount_cents"],
        "tax_year": d["tax_year"],
        "settled_at": d["settled_at"],
    }


def serialize_conversion(d: dict[str, Any]) -> dict[str, Any]:
    out = _common(d)
    out.update(
        {
            "participant_id": d["participant_id"],
            "source_account_id": d["source_account_id"],
            "destination_account_id": d["destination_account_id"],
            "amount_cents": d["amount_cents"],
            "backdoor_flag": d["backdoor_flag"],
            "status": d["status"],
            "approver_role_id": d.get("approver_role_id"),
            "completed_distribution_id": d.get("completed_distribution_id"),
        }
    )
    return out


def serialize_claim(d: dict[str, Any]) -> dict[str, Any]:
    out = _common(d)
    out.update(
        {
            "account_id": d["account_id"],
            "beneficiary_participant_id": d["beneficiary_participant_id"],
            "claim_date": d["claim_date"],
            "deadline_date": d["deadline_date"],
            "status": d["status"],
            "drained_amount_cents": d["drained_amount_cents"],
        }
    )
    return out


def serialize_form_1099r(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "tax_year": d["tax_year"],
        "recipient_participant_id": d["recipient_participant_id"],
        "source_event_type": d["source_event_type"],
        "source_event_id": d["source_event_id"],
        "box1_gross_distribution_cents": d["box1_gross_distribution_cents"],
        "box2a_taxable_amount_cents": d["box2a_taxable_amount_cents"],
        "box4_federal_withholding_cents": d["box4_federal_withholding_cents"],
        "box7_distribution_code": d["box7_distribution_code"],
        "status": d["status"],
    }


def serialize_excess_penalty(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "account_id": d["account_id"],
        "tax_year": d["tax_year"],
        "excess_amount_cents": d["excess_amount_cents"],
        "penalty_amount_cents": d["penalty_amount_cents"],
        "assessed_at": d["assessed_at"],
    }
