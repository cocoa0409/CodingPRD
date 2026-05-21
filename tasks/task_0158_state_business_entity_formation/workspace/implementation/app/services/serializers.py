"""Convert internal dict rows into JSON-ready payloads."""
from __future__ import annotations

from typing import Any

from ..timeutil import iso


def _common(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": iso(row.get("created_at")),
        "updated_at": iso(row.get("updated_at")),
        "version": row.get("version"),
    }


def _lite(row: dict[str, Any]) -> dict[str, Any]:
    """For lightweight rows that only carry id + created_at."""
    return {
        "id": row["id"],
        "created_at": iso(row.get("created_at")),
    }


def business_entity(row: dict[str, Any], *, total_due_overrides: dict | None = None) -> dict[str, Any]:
    out = _common(row)
    out.update({
        "legal_name": row.get("legal_name"),
        "entity_type": row.get("entity_type"),
        "home_state": row.get("home_state"),
        "formation_date": iso(row.get("formation_date")),
        "registered_agent_id": row.get("registered_agent_id"),
        "authorized_shares": row.get("authorized_shares"),
        "total_gross_assets_cents": row.get("total_gross_assets_cents", 0),
        "total_issued_shares": row.get("total_issued_shares", 0),
        "formation_status": row.get("formation_status"),
        "compliance_status": row.get("compliance_status"),
        "next_annual_report_due_date": iso(row.get("next_annual_report_due_date")),
        "ein": row.get("ein"),
        "dissolution_date": iso(row.get("dissolution_date")),
        "credit_balance_cents": row.get("credit_balance_cents", 0),
    })
    return out


def registered_agent(row: dict[str, Any]) -> dict[str, Any]:
    out = _common(row)
    out.update({
        "agent_name": row.get("agent_name"),
        "physical_address": row.get("physical_address"),
        "service_state": row.get("service_state"),
        "status": row.get("status"),
        "resignation_effective_at": iso(row.get("resignation_effective_at")),
    })
    return out


def operating_agreement(row: dict[str, Any]) -> dict[str, Any]:
    out = _lite(row)
    out.update({
        "business_entity_id": row.get("business_entity_id"),
        "template_code": row.get("template_code"),
        "template_version": row.get("template_version"),
        "locked_template_hash": row.get("locked_template_hash"),
        "attached_at": iso(row.get("attached_at")),
    })
    return out


def ein_application(row: dict[str, Any]) -> dict[str, Any]:
    out = _common(row)
    out.update({
        "business_entity_id": row.get("business_entity_id"),
        "responsible_party_name": row.get("responsible_party_name"),
        "responsible_party_ssn_last4": row.get("responsible_party_ssn_last4"),
        "status": row.get("status"),
        "assigned_ein": row.get("assigned_ein"),
    })
    return out


def annual_report(row: dict[str, Any]) -> dict[str, Any]:
    out = _common(row)
    out.update({
        "business_entity_id": row.get("business_entity_id"),
        "report_year": row.get("report_year"),
        "principal_office_address": row.get("principal_office_address"),
        "officer_director_count": row.get("officer_director_count"),
        "status": row.get("status"),
        "submitted_at": iso(row.get("submitted_at")),
        "accepted_at": iso(row.get("accepted_at")),
        "rejection_reason": row.get("rejection_reason"),
    })
    return out


def tax_assessment(row: dict[str, Any], *, late_fee_cents: int | None = None, total_due_cents: int | None = None,
                   credit_applied_cents: int | None = None) -> dict[str, Any]:
    out = _common(row)
    out.update({
        "business_entity_id": row.get("business_entity_id"),
        "tax_year": row.get("tax_year"),
        "calculation_method": row.get("calculation_method"),
        "base_tax_cents": row.get("base_tax_cents"),
        "late_fee_cents": late_fee_cents if late_fee_cents is not None else row.get("late_fee_cents", 0),
        "total_due_cents": total_due_cents if total_due_cents is not None else row.get("total_due_cents", 0),
        "credit_applied_cents": credit_applied_cents if credit_applied_cents is not None else row.get("credit_applied_cents", 0),
        "due_date": iso(row.get("due_date")),
        "paid_at": iso(row.get("paid_at")),
        "status": row.get("status"),
    })
    return out


def foreign_qualification(row: dict[str, Any]) -> dict[str, Any]:
    out = _common(row)
    out.update({
        "business_entity_id": row.get("business_entity_id"),
        "foreign_state": row.get("foreign_state"),
        "foreign_registered_agent_id": row.get("foreign_registered_agent_id"),
        "certificate_of_good_standing_date": iso(row.get("certificate_of_good_standing_date")),
        "status": row.get("status"),
        "qualified_at": iso(row.get("qualified_at")),
        "revoked_at": iso(row.get("revoked_at")),
    })
    return out


def boi_report(row: dict[str, Any]) -> dict[str, Any]:
    out = _common(row)
    out.update({
        "business_entity_id": row.get("business_entity_id"),
        "filing_type": row.get("filing_type"),
        "status": row.get("status"),
        "filed_at": iso(row.get("filed_at")),
        "stale_at": iso(row.get("stale_at")),
        "penalty_cents": row.get("penalty_cents", 0),
        "days_stale_at_filing": row.get("days_stale_at_filing", 0),
    })
    return out


def beneficial_owner(row: dict[str, Any]) -> dict[str, Any]:
    out = _common(row)
    out.update({
        "full_legal_name": row.get("full_legal_name"),
        "date_of_birth": iso(row.get("date_of_birth")),
        "residential_address": row.get("residential_address"),
        "identifying_document_type": row.get("identifying_document_type"),
        "identifying_document_number": row.get("identifying_document_number"),
    })
    return out


def boi_ownership(row: dict[str, Any]) -> dict[str, Any]:
    out = _lite(row)
    out.update({
        "business_entity_id": row.get("business_entity_id"),
        "beneficial_owner_id": row.get("beneficial_owner_id"),
        "ownership_percent_basis_points": row.get("ownership_percent_basis_points"),
        "effective_at": iso(row.get("effective_at")),
        "terminated_at": iso(row.get("terminated_at")),
    })
    return out


def compliance_event(row: dict[str, Any]) -> dict[str, Any]:
    out = _lite(row)
    out.update({
        "business_entity_id": row.get("business_entity_id"),
        "event_type": row.get("event_type"),
        "payload": row.get("payload") or {},
        "occurred_at": iso(row.get("occurred_at")),
    })
    return out
