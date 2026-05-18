"""Entity-to-response serializers.

Each function returns the JSON-safe representation of an entity. PRD §2.5
states that every entity carries id + created_at, most carry updated_at +
version, and certain entities (CaseTypeConfig, VisaBulletin, CaseEvent) are
immutable and only carry id + created_at (+ their own fields).
"""
from __future__ import annotations

from utils import iso_now, date_iso


def _common_fields(entity: dict) -> dict:
    return {
        "id": entity["id"],
        "created_at": iso_now(entity["created_at"]),
        "updated_at": iso_now(entity["updated_at"]),
        "version": entity["version"],
    }


# ── Petitioner ──────────────────────────────────────────────────────────────


def serialize_petitioner(p: dict) -> dict:
    return {
        **_common_fields(p),
        "full_name": p["full_name"],
        "a_number": p.get("a_number"),
        "date_of_birth": p["date_of_birth"],
        "country_of_citizenship": p["country_of_citizenship"],
        "email": p["email"],
    }


# ── Beneficiary ─────────────────────────────────────────────────────────────


def serialize_beneficiary(b: dict) -> dict:
    return {
        **_common_fields(b),
        "petitioner_id": b["petitioner_id"],
        "full_name": b["full_name"],
        "date_of_birth": b["date_of_birth"],
        "country_of_chargeability": b["country_of_chargeability"],
        "preference_category": b["preference_category"],
        "relationship_to_petitioner": b["relationship_to_petitioner"],
    }


# ── CaseTypeConfig (immutable except for upsert) ────────────────────────────


def serialize_case_type_config(c: dict) -> dict:
    return {
        "id": c["id"],
        "created_at": iso_now(c["created_at"]),
        "case_type": c["case_type"],
        "requires_biometrics": c["requires_biometrics"],
        "requires_interview": c["requires_interview"],
        "rfe_response_window_days": c["rfe_response_window_days"],
        "requires_priority_date_current": c["requires_priority_date_current"],
        "receipt_prefix": c["receipt_prefix"],
    }


# ── Case ────────────────────────────────────────────────────────────────────


def serialize_case(c: dict) -> dict:
    return {
        **_common_fields(c),
        "petitioner_id": c["petitioner_id"],
        "beneficiary_id": c["beneficiary_id"],
        "case_type": c["case_type"],
        "receipt_number": c.get("receipt_number"),
        "priority_date": c.get("priority_date"),  # already a YYYY-MM-DD string or None
        "filing_date": iso_now(c["filing_date"]) if c.get("filing_date") else None,
        "status": c["status"],
        "priority_date_status": c["priority_date_status"],
        "rfe_deadline": iso_now(c["rfe_deadline"]) if c.get("rfe_deadline") else None,
        "linked_i130_case_id": c.get("linked_i130_case_id"),
        "decision_at": iso_now(c["decision_at"]) if c.get("decision_at") else None,
        "denial_reason": c.get("denial_reason"),
    }


# ── Biometrics ──────────────────────────────────────────────────────────────


def serialize_biometrics(b: dict) -> dict:
    return {
        **_common_fields(b),
        "case_id": b["case_id"],
        "scheduled_at": iso_now(b["scheduled_at"]),
        "location_code": b["location_code"],
        "status": b["status"],
        "reschedule_count": b["reschedule_count"],
        "completed_at": iso_now(b["completed_at"]) if b.get("completed_at") else None,
    }


# ── RFE ─────────────────────────────────────────────────────────────────────


def serialize_rfe(r: dict) -> dict:
    return {
        **_common_fields(r),
        "case_id": r["case_id"],
        "issued_at": iso_now(r["issued_at"]),
        "deadline_at": iso_now(r["deadline_at"]),
        "reason_code": r["reason_code"],
        "officer_notes": r["officer_notes"],
        "response_received_at": iso_now(r["response_received_at"]) if r.get("response_received_at") else None,
        "status": r["status"],
    }


# ── Interview ───────────────────────────────────────────────────────────────


def serialize_interview(i: dict) -> dict:
    return {
        **_common_fields(i),
        "case_id": i["case_id"],
        "scheduled_at": iso_now(i["scheduled_at"]),
        "field_office_code": i["field_office_code"],
        "status": i["status"],
        "outcome": i.get("outcome"),
    }


# ── VisaBulletin (immutable; no updated_at / version) ───────────────────────


def serialize_visa_bulletin(v: dict) -> dict:
    return {
        "id": v["id"],
        "created_at": iso_now(v["created_at"]),
        "bulletin_month": v["bulletin_month"],
        "chart_type": v["chart_type"],
        "preference_category": v["preference_category"],
        "country": v["country"],
        "cutoff_date": v["cutoff_date"],
        "published_at": iso_now(v["published_at"]),
    }


# ── CaseEvent (immutable; no updated_at / version) ──────────────────────────


def serialize_case_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": iso_now(e["created_at"]),
        "case_id": e["case_id"],
        "event_type": e["event_type"],
        "from_value": e.get("from_value"),
        "to_value": e.get("to_value"),
        "actor_role": e["actor_role"],
        "occurred_at": iso_now(e["occurred_at"]),
    }
