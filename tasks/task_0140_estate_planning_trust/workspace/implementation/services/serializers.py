"""Entity → JSON dict serializers.

The probate_posture on Estate is computed live on serialization so it always
reflects the latest filing / fiduciary / phase state without persisting a
derived field.
"""
from __future__ import annotations

from db import store
from utils import iso_now


def _ts(value):
    if value is None:
        return None
    return iso_now(value)


def serialize_estate(estate: dict) -> dict:
    from services.calculations import compute_probate_posture
    return {
        "id": estate["id"],
        "testator_name": estate["testator_name"],
        "domicile_state": estate["domicile_state"],
        "filing_court_id": estate["filing_court_id"],
        "gross_estate_value_cents": estate.get("gross_estate_value_cents", 0),
        "net_estate_value_cents": estate.get("net_estate_value_cents", 0),
        "admin_phase": estate["admin_phase"],
        "probate_posture": compute_probate_posture(estate),
        "petition_filed_at": _ts(estate.get("petition_filed_at")),
        "settlement_due_at": _ts(estate.get("settlement_due_at")),
        "contested_at": _ts(estate.get("contested_at")),
        "created_at": _ts(estate["created_at"]),
        "updated_at": _ts(estate["updated_at"]),
        "version": estate["version"],
    }


def serialize_asset(asset: dict) -> dict:
    return {
        "id": asset["id"],
        "estate_id": asset["estate_id"],
        "asset_class": asset["asset_class"],
        "description": asset["description"],
        "declared_value_cents": asset["declared_value_cents"],
        "appraised_value_cents": asset.get("appraised_value_cents"),
        "status": asset["status"],
        "distribution_id": asset.get("distribution_id"),
        "requires_poa_for_mutation": asset.get("requires_poa_for_mutation", False),
        "created_at": _ts(asset["created_at"]),
        "updated_at": _ts(asset["updated_at"]),
        "version": asset["version"],
    }


def serialize_beneficiary(b: dict) -> dict:
    return {
        "id": b["id"],
        "estate_id": b["estate_id"],
        "full_name": b["full_name"],
        "relationship": b["relationship"],
        "is_minor": b.get("is_minor", False),
        "guardianship_id": b.get("guardianship_id"),
        "status": b["status"],
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def serialize_designation(d: dict) -> dict:
    # BeneficiaryDesignation has no version / updated_at (PRD §2.4 — append-only).
    return {
        "id": d["id"],
        "estate_id": d["estate_id"],
        "asset_id": d["asset_id"],
        "beneficiary_id": d["beneficiary_id"],
        "share_basis_points": d["share_basis_points"],
        "priority_rank": d["priority_rank"],
        "status": d["status"],
        "created_at": _ts(d["created_at"]),
    }


def serialize_fiduciary(f: dict) -> dict:
    return {
        "id": f["id"],
        "estate_id": f["estate_id"],
        "scope_type": f["scope_type"],
        "full_name": f["full_name"],
        "contact_user_id": f["contact_user_id"],
        "status": f["status"],
        "bond_amount_cents": f.get("bond_amount_cents"),
        "court_confirmation_at": _ts(f.get("court_confirmation_at")),
        "created_at": _ts(f["created_at"]),
        "updated_at": _ts(f["updated_at"]),
        "version": f["version"],
    }


def serialize_guardianship(g: dict) -> dict:
    return {
        "id": g["id"],
        "estate_id": g["estate_id"],
        "minor_beneficiary_id": g["minor_beneficiary_id"],
        "guardian_fiduciary_id": g["guardian_fiduciary_id"],
        "effective_at": _ts(g["effective_at"]),
        "status": g["status"],
        "created_at": _ts(g["created_at"]),
        "updated_at": _ts(g["updated_at"]),
        "version": g["version"],
    }


def serialize_hipaa(h: dict) -> dict:
    return {
        "id": h["id"],
        "estate_id": h["estate_id"],
        "authorized_recipient": h["authorized_recipient"],
        "scope": h["scope"],
        "signed_at": _ts(h["signed_at"]),
        "expires_at": _ts(h.get("expires_at")),
        "status": h["status"],
        "created_at": _ts(h["created_at"]),
        "updated_at": _ts(h["updated_at"]),
        "version": h["version"],
    }


def serialize_poa(p: dict) -> dict:
    return {
        "id": p["id"],
        "estate_id": p["estate_id"],
        "poa_type": p["poa_type"],
        "agent_fiduciary_id": p["agent_fiduciary_id"],
        "asset_class_scope": p["asset_class_scope"],
        "effective_at": _ts(p["effective_at"]),
        "revoked_at": _ts(p.get("revoked_at")),
        "status": p["status"],
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def serialize_directive(d: dict) -> dict:
    return {
        "id": d["id"],
        "estate_id": d["estate_id"],
        "directive_type": d["directive_type"],
        "instructions": d["instructions"],
        "requires_hipaa_scope": d["requires_hipaa_scope"],
        "status": d["status"],
        "supersedes_directive_id": d.get("supersedes_directive_id"),
        "executed_at": _ts(d.get("executed_at")),
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def serialize_filing(f: dict) -> dict:
    return {
        "id": f["id"],
        "estate_id": f["estate_id"],
        "filing_type": f["filing_type"],
        "filed_by_fiduciary_id": f["filed_by_fiduciary_id"],
        "status": f["status"],
        "court_response_at": _ts(f.get("court_response_at")),
        "rejection_reason": f.get("rejection_reason"),
        "created_at": _ts(f["created_at"]),
        "updated_at": _ts(f["updated_at"]),
        "version": f["version"],
    }


def serialize_distribution(d: dict) -> dict:
    return {
        "id": d["id"],
        "estate_id": d["estate_id"],
        "beneficiary_id": d["beneficiary_id"],
        "planned_amount_cents": d["planned_amount_cents"],
        "actual_amount_cents": d.get("actual_amount_cents"),
        "status": d["status"],
        "executed_at": _ts(d.get("executed_at")),
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }
