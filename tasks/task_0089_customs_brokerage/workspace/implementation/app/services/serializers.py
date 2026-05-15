"""Serialise persisted entities back into API JSON shapes."""
from __future__ import annotations

from typing import Any

from ..calculations import compute_late_interest, to_float2
from ..clock import now_iso_ms
from ..store import get_store


def _common_keys(entity: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": entity.get("id"),
        "created_at": entity.get("created_at"),
    }
    if "updated_at" in entity:
        out["updated_at"] = entity["updated_at"]
    if "version" in entity:
        out["version"] = entity["version"]
    return out


def serialize_client(c: dict[str, Any]) -> dict[str, Any]:
    out = _common_keys(c)
    out.update(
        {
            "legal_name": c.get("legal_name"),
            "tax_id": c.get("tax_id"),
            "country_code": c.get("country_code"),
            "contact_email": c.get("contact_email"),
            "default_settlement_currency": c.get("default_settlement_currency"),
            "status": c.get("status"),
        }
    )
    return out


def serialize_agreement(a: dict[str, Any]) -> dict[str, Any]:
    out = _common_keys(a)
    out.update(
        {
            "client_id": a.get("client_id"),
            "scope_of_service": a.get("scope_of_service"),
            "fee_schedule": a.get("fee_schedule"),
            "agreement_currency": a.get("agreement_currency"),
            "valid_from": a.get("valid_from"),
            "valid_until": a.get("valid_until"),
            "late_interest_daily_rate_bps": a.get("late_interest_daily_rate_bps"),
            "status": a.get("status"),
            "signed_at": a.get("signed_at"),
            "signature_token": a.get("signature_token"),
            "pinned_fee_schedule_version": a.get("pinned_fee_schedule_version"),
            "renewed_from_agreement_id": a.get("renewed_from_agreement_id"),
            "terminated_reason": a.get("terminated_reason"),
        }
    )
    return out


def serialize_declaration(d: dict[str, Any]) -> dict[str, Any]:
    out = _common_keys(d)
    out.update(
        {
            "agreement_id": d.get("agreement_id"),
            "jurisdiction_code": d.get("jurisdiction_code"),
            "shipment_reference": d.get("shipment_reference"),
            "hs_code": d.get("hs_code"),
            "country_of_origin": d.get("country_of_origin"),
            "trade_agreement_code": d.get("trade_agreement_code"),
            "declared_value_amount": to_float2(d.get("declared_value_amount")),
            "declared_currency": d.get("declared_currency"),
            "fx_rate_to_settlement": (
                float(d["fx_rate_to_settlement"])
                if d.get("fx_rate_to_settlement") is not None
                else None
            ),
            "declared_value_review_status": d.get("declared_value_review_status"),
            "form_payload": d.get("form_payload"),
            "status": d.get("status"),
            "rejection_reason_code": d.get("rejection_reason_code"),
            "amendment_count": d.get("amendment_count", 0),
            "pinned_agreement_version": d.get("pinned_agreement_version"),
        }
    )
    # Expose the latest Filing transitively so callers that need the
    # filing id (no public /filings endpoint exists) can read it from
    # the declaration response.
    store = get_store()
    filings = [
        f for f in store.filings.values() if f.get("declaration_id") == d.get("id")
    ]
    if filings:
        filings.sort(key=lambda f: f.get("submitted_at") or "")
        out["filing"] = serialize_filing(filings[-1])
    else:
        out["filing"] = None
    return out


def serialize_document(doc: dict[str, Any]) -> dict[str, Any]:
    out = _common_keys(doc)
    out.update(
        {
            "declaration_id": doc.get("declaration_id"),
            "doc_type": doc.get("doc_type"),
            "storage_uri": doc.get("storage_uri"),
            "declared_total_value": to_float2(doc.get("declared_total_value")),
            "declared_total_currency": doc.get("declared_total_currency"),
            "authenticity_score": (
                float(doc["authenticity_score"])
                if doc.get("authenticity_score") is not None
                else None
            ),
            "authenticity_status": doc.get("authenticity_status"),
            "follow_up_requested_at": doc.get("follow_up_requested_at"),
        }
    )
    return out


def serialize_filing(f: dict[str, Any]) -> dict[str, Any]:
    out = _common_keys(f)
    out.update(
        {
            "declaration_id": f.get("declaration_id"),
            "single_window_ref": f.get("single_window_ref"),
            "submitted_at": f.get("submitted_at"),
            "response_type": f.get("response_type"),
            "response_received_at": f.get("response_received_at"),
            "query_due_at": f.get("query_due_at"),
            "query_response_at": f.get("query_response_at"),
            "manifest_match_status": f.get("manifest_match_status"),
            "is_amendment": f.get("is_amendment", False),
        }
    )
    return out


def serialize_inspection_case(ic: dict[str, Any]) -> dict[str, Any]:
    out = _common_keys(ic)
    out.update(
        {
            "filing_id": ic.get("filing_id"),
            "warehouse_code": ic.get("warehouse_code"),
            "scheduled_at": ic.get("scheduled_at"),
            "sample_required": ic.get("sample_required", False),
            "sample_provided_at": ic.get("sample_provided_at"),
            "outcome": ic.get("outcome"),
            "penalty_amount": to_float2(ic.get("penalty_amount") or 0),
            "post_inspection_doc_uri": ic.get("post_inspection_doc_uri"),
        }
    )
    return out


def _live_late_interest(s: dict[str, Any]) -> float:
    """Compute the running late interest for an ADVANCED settlement;
    return frozen value for REIMBURSED settlements."""
    if s.get("status") == "REIMBURSED":
        return to_float2(s.get("late_interest_amount") or 0) or 0.0
    if s.get("status") != "ADVANCED":
        return 0.0
    store = get_store()
    decl = store.declarations.get(s.get("declaration_id"))
    if not decl:
        return 0.0
    agreement = store.agreements.get(decl.get("agreement_id"))
    if not agreement:
        return 0.0
    bps = int(agreement.get("late_interest_daily_rate_bps") or 0)
    advance_amt = s.get("advance_paid_amount") or 0
    due = s.get("reimbursement_due_at")
    return to_float2(
        compute_late_interest(advance_amt, due, now_iso_ms(), bps)
    ) or 0.0


def serialize_settlement(s: dict[str, Any]) -> dict[str, Any]:
    out = _common_keys(s)
    out.update(
        {
            "declaration_id": s.get("declaration_id"),
            "tariff_amount": to_float2(s.get("tariff_amount") or 0),
            "vat_amount": to_float2(s.get("vat_amount") or 0),
            "consumption_tax_amount": to_float2(s.get("consumption_tax_amount") or 0),
            "penalty_amount": to_float2(s.get("penalty_amount") or 0),
            "broker_fee_amount": to_float2(s.get("broker_fee_amount") or 0),
            "settlement_currency": s.get("settlement_currency"),
            "advance_paid_amount": to_float2(s.get("advance_paid_amount") or 0),
            "advance_paid_at": s.get("advance_paid_at"),
            "reimbursement_due_at": s.get("reimbursement_due_at"),
            "reimbursed_at": s.get("reimbursed_at"),
            "late_interest_amount": _live_late_interest(s),
            "voucher_uri": s.get("voucher_uri"),
            "status": s.get("status"),
        }
    )
    return out


def serialize_rejection(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r.get("id"),
        "created_at": r.get("created_at"),
        "declaration_id": r.get("declaration_id"),
        "rejection_reason_code": r.get("rejection_reason_code"),
        "archived_at": r.get("archived_at"),
        "free_text_note": r.get("free_text_note"),
        "prior_amendment_count": r.get("prior_amendment_count", 0),
    }


def serialize_audit(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": a.get("id"),
        "created_at": a.get("created_at"),
        "entity_type": a.get("entity_type"),
        "entity_id": a.get("entity_id"),
        "event_type": a.get("event_type"),
        "actor_role": a.get("actor_role"),
        "actor_id": a.get("actor_id"),
        "payload": a.get("payload") or {},
    }


def serialize_external_event(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": e.get("id"),
        "created_at": e.get("created_at"),
        "source_system": e.get("source_system"),
        "event_type": e.get("event_type"),
        "target_entity_type": e.get("target_entity_type"),
        "target_entity_id": e.get("target_entity_id"),
        "payload": e.get("payload") or {},
        "processed_at": e.get("processed_at"),
    }
