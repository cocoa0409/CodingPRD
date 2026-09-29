"""Resource serialization (PRD 2.4)."""

from decimal import Decimal

from envelope import fmt_dt


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": fmt_dt(entity["created_at"]),
        "updated_at": fmt_dt(entity["updated_at"]),
        "version": entity["version"],
    }


def room(entity):
    out = _common(entity)
    out.update(
        {
            "name": entity["name"],
            "agency_code": entity["agency_code"],
            "posture": entity["posture"],
            "open_discrepancy_count": entity["open_discrepancy_count"],
            "missing_high_risk_count": entity["missing_high_risk_count"],
            "sealed_location_count": entity["sealed_location_count"],
            "disposal_eligible_count": entity["disposal_eligible_count"],
            "escrow_balance_cents": entity["escrow_balance_cents"],
            "last_sweep_at": fmt_dt(entity["last_sweep_at"]),
        }
    )
    return out


def statute(entity):
    out = _common(entity)
    out.update(
        {
            "offense_code": entity["offense_code"],
            "description": entity["description"],
            "preservation_class": entity["preservation_class"],
            "statutory_retention_days": entity["statutory_retention_days"],
            "appeal_window_days": entity["appeal_window_days"],
            "destruction_requires_court_order": entity["destruction_requires_court_order"],
        }
    )
    return out


def location(entity):
    out = _common(entity)
    out.update(
        {
            "property_room_id": entity["property_room_id"],
            "code": entity["code"],
            "category": entity["category"],
            "capacity_slots": entity["capacity_slots"],
            "occupied_slots": entity["occupied_slots"],
            "temperature_c": _num(entity["temperature_c"]),
            "requires_dual_signature": entity["requires_dual_signature"],
            "status": entity["status"],
            "sealed_by_audit_session_id": entity["sealed_by_audit_session_id"],
        }
    )
    return out


def custodian(entity):
    out = _common(entity)
    out.update(
        {
            "property_room_id": entity["property_room_id"],
            "badge_number": entity["badge_number"],
            "full_name": entity["full_name"],
            "role_type": entity["role_type"],
            "certification_expires_at": fmt_dt(entity["certification_expires_at"]),
            "status": entity["status"],
            "suspension_reason": entity["suspension_reason"],
            "open_escort_count": entity["open_escort_count"],
        }
    )
    return out


def case(entity):
    out = _common(entity)
    out.update(
        {
            "property_room_id": entity["property_room_id"],
            "offense_statute_id": entity["offense_statute_id"],
            "case_number": entity["case_number"],
            "status": entity["status"],
            "charged_at": fmt_dt(entity["charged_at"]),
            "adjudicated_at": fmt_dt(entity["adjudicated_at"]),
            "appeal_opened_at": fmt_dt(entity["appeal_opened_at"]),
            "closed_at": fmt_dt(entity["closed_at"]),
            "item_count": entity["item_count"],
            "undisposed_item_count": entity["undisposed_item_count"],
        }
    )
    return out


def item(entity):
    out = _common(entity)
    out.update(
        {
            "case_id": entity["case_id"],
            "item_description": entity["item_description"],
            "category": entity["category"],
            "packaging_type": entity["packaging_type"],
            "appraised_value_cents": entity["appraised_value_cents"],
            "is_found_property": entity["is_found_property"],
            "seized_at": fmt_dt(entity["seized_at"]),
            "item_sequence": entity["item_sequence"],
            "barcode": entity["barcode"],
            "intake_at": fmt_dt(entity["intake_at"]),
            "required_storage_category": entity["required_storage_category"],
            "storage_location_id": entity["storage_location_id"],
            "custody_state": entity["custody_state"],
            "disposition_state": entity["disposition_state"],
            "current_holder_id": entity["current_holder_id"],
            "retention_release_at": fmt_dt(entity["retention_release_at"]),
            "retention_basis": entity["retention_basis"],
            "open_transfer_count": entity["open_transfer_count"],
        }
    )
    return out


def determination(entity):
    out = _common(entity)
    out.update(
        {
            "evidence_item_id": entity["evidence_item_id"],
            "basis": entity["basis"],
            "resolved_basis": entity["resolved_basis"],
            "anchor_at": fmt_dt(entity["anchor_at"]),
            "statute_days_applied": entity["statute_days_applied"],
            "computed_release_at": fmt_dt(entity["computed_release_at"]),
            "superseded": entity["superseded"],
        }
    )
    return out


def transfer(entity):
    out = _common(entity)
    out.update(
        {
            "evidence_item_id": entity["evidence_item_id"],
            "to_custodian_id": entity["to_custodian_id"],
            "purpose": entity["purpose"],
            "released_at": fmt_dt(entity["released_at"]),
            "due_back_at": fmt_dt(entity["due_back_at"]),
            "from_custodian_id": entity["from_custodian_id"],
            "status": entity["status"],
            "released_signature": entity["released_signature"],
            "witness_signature": entity["witness_signature"],
            "receipt_signature": entity["receipt_signature"],
            "returned_at": fmt_dt(entity["returned_at"]),
            "denial_reason": entity["denial_reason"],
        }
    )
    return out


def order(entity):
    out = _common(entity)
    out.update(
        {
            "evidence_item_id": entity["evidence_item_id"],
            "type": entity["type"],
            "requested_by_custodian_id": entity["requested_by_custodian_id"],
            "owner_claim_id": entity["owner_claim_id"],
            "reserve_price_cents": entity["reserve_price_cents"],
            "status": entity["status"],
            "auto_authorized": entity["auto_authorized"],
            "court_order_number": entity["court_order_number"],
            "estimated_net_proceeds_cents": entity["estimated_net_proceeds_cents"],
            "gross_sale_cents": entity["gross_sale_cents"],
            "commission_cents": entity["commission_cents"],
            "storage_recovery_cents": entity["storage_recovery_cents"],
            "settled_net_proceeds_cents": entity["settled_net_proceeds_cents"],
            "settlement_status": entity["settlement_status"],
            "executed_by_custodian_id": entity["executed_by_custodian_id"],
            "witness_custodian_id": entity["witness_custodian_id"],
            "authorized_at": fmt_dt(entity["authorized_at"]),
            "executed_at": fmt_dt(entity["executed_at"]),
            "settlement_deadline_at": fmt_dt(entity["settlement_deadline_at"]),
            "settled_at": fmt_dt(entity["settled_at"]),
            "payee_reference": entity["payee_reference"],
        }
    )
    return out


def claim(entity):
    out = _common(entity)
    out.update(
        {
            "evidence_item_id": entity["evidence_item_id"],
            "claimant_name": entity["claimant_name"],
            "claimant_contact": entity["claimant_contact"],
            "notice_method": entity["notice_method"],
            "notified_at": fmt_dt(entity["notified_at"]),
            "claim_deadline_at": fmt_dt(entity["claim_deadline_at"]),
            "status": entity["status"],
            "proof_document_ref": entity["proof_document_ref"],
            "verified_at": fmt_dt(entity["verified_at"]),
        }
    )
    return out


def session(entity):
    out = _common(entity)
    out.update(
        {
            "storage_location_id": entity["storage_location_id"],
            "auditor_id": entity["auditor_id"],
            "scheduled_start_at": fmt_dt(entity["scheduled_start_at"]),
            "scheduled_end_at": fmt_dt(entity["scheduled_end_at"]),
            "status": entity["status"],
            "started_at": fmt_dt(entity["started_at"]),
            "reconciled_at": fmt_dt(entity["reconciled_at"]),
            "closed_at": fmt_dt(entity["closed_at"]),
            "expected_evidence_item_ids": list(entity["expected_evidence_item_ids"]),
            "expected_item_count": entity["expected_item_count"],
            "scanned_evidence_item_ids": list(entity["scanned_evidence_item_ids"]),
            "scanned_item_count": entity["scanned_item_count"],
            "missing_count": entity["missing_count"],
            "misplaced_count": entity["misplaced_count"],
            "risk_index": _num(entity["risk_index"]),
        }
    )
    return out


def discrepancy(entity):
    out = _common(entity)
    out.update(
        {
            "evidence_item_id": entity["evidence_item_id"],
            "audit_session_id": entity["audit_session_id"],
            "kind": entity["kind"],
            "status": entity["status"],
            "weight_contribution": _num(entity["weight_contribution"]),
            "resolution_note": entity["resolution_note"],
            "resolved_at": fmt_dt(entity["resolved_at"]),
        }
    )
    return out


def chain_event(entity):
    return {
        "id": entity["id"],
        "created_at": fmt_dt(entity["created_at"]),
        "evidence_item_id": entity["evidence_item_id"],
        "actor_custodian_id": entity["actor_custodian_id"],
        "event_type": entity["event_type"],
        "sequence_no": entity["sequence_no"],
        "occurred_at": fmt_dt(entity["occurred_at"]),
        "actor_role": entity["actor_role"],
        "signature_ref": entity["signature_ref"],
        "detail": entity["detail"],
    }
