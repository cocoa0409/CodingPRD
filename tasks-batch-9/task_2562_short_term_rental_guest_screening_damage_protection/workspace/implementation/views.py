"""Serialisers.  Computed fields are derived at read time (PRD 2.4)."""

from core import db, hours
import calc


def guest_view(g):
    return {
        "id": g["id"],
        "full_name": g["full_name"],
        "email": g["email"],
        "country_code": g["country_code"],
        "payment_risk_signal": g["payment_risk_signal"],
        "chargeback_count": g["chargeback_count"],
        "verification_state": calc.verification_state(g),
        "accepted_doc_count": calc.accepted_doc_count(g),
        "accepted_gov_id_count": calc.accepted_gov_id_count(g),
        "completed_stay_count": calc.completed_stay_count(g),
        "substantiated_incident_count": calc.substantiated_incident_count(g),
        "escalated_incident_count": calc.escalated_incident_count(g),
        "approved_claim_count": g["approved_claim_count"],
        "risk_score": calc.risk_score(g),
        "risk_tier": calc.risk_tier(g),
        "deposit_held_cents": calc.deposit_held_cents(g),
        "active_blocklist_scope_count": calc.active_blocklist_scope_count(g),
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def risk_profile_view(g):
    return {
        "risk_score": calc.risk_score(g),
        "risk_tier": calc.risk_tier(g),
        "verification_state": calc.verification_state(g),
        "completed_stay_count": calc.completed_stay_count(g),
        "substantiated_incident_count": calc.substantiated_incident_count(g),
        "escalated_incident_count": calc.escalated_incident_count(g),
        "approved_claim_count": g["approved_claim_count"],
        "chargeback_count": g["chargeback_count"],
        "active_blocklist_scope_count": calc.active_blocklist_scope_count(g),
    }


def host_claims(h):
    return [c for c in db.damage_claims.values() if c["host_id"] == h["id"]]


def host_view(h):
    claims = host_claims(h)
    settled = [c for c in claims if c["claim_state"] == "SETTLED"]
    closed = [c for c in claims if c["claim_state"] == "CLOSED_DENIED"]
    return {
        "id": h["id"],
        "legal_name": h["legal_name"],
        "email": h["email"],
        "payout_hold": h["payout_hold"],
        "settled_claim_count": len(settled),
        "denied_claim_count": len(closed),
        "total_recovered_cents": sum(c["recovered_cents"] for c in settled),
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def jurisdiction_rule_view(j):
    return {
        "id": j["id"],
        "jurisdiction_code": j["jurisdiction_code"],
        "min_stay_nights": j["min_stay_nights"],
        "max_occupancy_cap": j["max_occupancy_cap"],
        "events_prohibited": j["events_prohibited"],
        "registration_required": j["registration_required"],
        "indoor_camera_allowed": j["indoor_camera_allowed"],
        "indoor_audio_allowed": j["indoor_audio_allowed"],
        "sensor_notice_required": j["sensor_notice_required"],
        "noise_threshold_db": j["noise_threshold_db"],
        "created_at": j["created_at"],
    }


def property_view(p):
    return {
        "id": p["id"],
        "host_id": p["host_id"],
        "jurisdiction_rule_id": p["jurisdiction_rule_id"],
        "address_line": p["address_line"],
        "city": p["city"],
        "registration_number": p["registration_number"],
        "max_occupancy": p["max_occupancy"],
        "bedrooms": p["bedrooms"],
        "nightly_rate_cents": p["nightly_rate_cents"],
        "protection_product": p["protection_product"],
        "deposit_amount_cents": p["deposit_amount_cents"],
        "waiver_nightly_fee_cents": p["waiver_nightly_fee_cents"],
        "claim_ceiling_cents": p["claim_ceiling_cents"],
        "event_policy": p["event_policy"],
        "turnover_buffer_nights": p["turnover_buffer_nights"],
        "listing_state": p["listing_state"],
        "suspension_reason": p["suspension_reason"],
        "sensor_compliance_state": calc.sensor_compliance_state(p),
        "coverage_posture": calc.coverage_posture(p),
        "open_reservation_count": calc.open_reservation_count(p),
        "open_claim_count": calc.open_claim_count(p),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def coverage_summary_view(p):
    visible = calc.visible_layers(p)
    available = [l for l in visible if l["layer_state"] == "AVAILABLE"]
    remaining = 0
    for layer in available:
        capacity = layer["limit_cents"] - calc.layer_consumed_cents(layer)
        if capacity > 0:
            remaining += capacity
    return {
        "coverage_posture": calc.coverage_posture(p),
        "visible_layer_count": len(visible),
        "available_layer_count": len(available),
        "remaining_capacity_cents": remaining,
    }


def device_view(d):
    return {
        "id": d["id"],
        "property_id": d["property_id"],
        "device_type": d["device_type"],
        "placement_zone": d["placement_zone"],
        "records_audio": d["records_audio"],
        "guest_disclosure_text": d["guest_disclosure_text"],
        "disclosure_state": d["disclosure_state"],
        "reject_reason_code": d["reject_reason_code"],
        "reviewed_by_user_id": d["reviewed_by_user_id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def document_view(d):
    return {
        "id": d["id"],
        "guest_id": d["guest_id"],
        "doc_type": d["doc_type"],
        "issuing_country": d["issuing_country"],
        "document_ref": d["document_ref"],
        "expires_on": d["expires_on"],
        "review_state": d["review_state"],
        "reject_reason_code": d["reject_reason_code"],
        "reviewed_by_user_id": d["reviewed_by_user_id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def reservation_view(r):
    return {
        "id": r["id"],
        "guest_id": r["guest_id"],
        "property_id": r["property_id"],
        "check_in": r["check_in"],
        "check_out": r["check_out"],
        "guest_count": r["guest_count"],
        "event_declared": r["event_declared"],
        "nights": r["nights"],
        "check_in_at": r["check_in_at"],
        "check_out_at": r["check_out_at"],
        "claim_window_ends_at": r["claim_window_ends_at"],
        "screening_state": r["screening_state"],
        "screening_reason_code": r["screening_reason_code"],
        "risk_score_at_booking": r["risk_score_at_booking"],
        "risk_tier_at_booking": r["risk_tier_at_booking"],
        "screening_decided_by_user_id": r["screening_decided_by_user_id"],
        "stay_state": r["stay_state"],
        "cancel_reason_code": r["cancel_reason_code"],
        "deposit_state": r["deposit_state"],
        "deposit_hold_cents": r["deposit_hold_cents"],
        "deposit_applied_cents": r["deposit_applied_cents"],
        "deposit_refunded_cents": r["deposit_refunded_cents"],
        "accommodation_cents": r["accommodation_cents"],
        "waiver_fee_cents": r["waiver_fee_cents"],
        "pre_fee_subtotal_cents": r["pre_fee_subtotal_cents"],
        "trust_fee_pct": r["trust_fee_pct"],
        "trust_fee_cents": r["trust_fee_cents"],
        "total_charged_cents": r["total_charged_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def charge_breakdown_view(r):
    return {
        "nights": r["nights"],
        "accommodation_cents": r["accommodation_cents"],
        "waiver_fee_cents": r["waiver_fee_cents"],
        "pre_fee_subtotal_cents": r["pre_fee_subtotal_cents"],
        "trust_fee_pct": r["trust_fee_pct"],
        "trust_fee_cents": r["trust_fee_cents"],
        "total_charged_cents": r["total_charged_cents"],
        "deposit_hold_cents": r["deposit_hold_cents"],
    }


def incident_view(i):
    return {
        "id": i["id"],
        "reservation_id": i["reservation_id"],
        "sensor_device_id": i["sensor_device_id"],
        "incident_type": i["incident_type"],
        "severity": i["severity"],
        "source": i["source"],
        "detected_at": i["detected_at"],
        "description": i["description"],
        "decibel_reading": i["decibel_reading"],
        "observed_occupancy": i["observed_occupancy"],
        "complainant_ref": i["complainant_ref"],
        "incident_state": i["incident_state"],
        "substantiated": i["substantiated"],
        "escalated": i["escalated"],
        "law_enforcement_ref": i["law_enforcement_ref"],
        "response_due_at": i["response_due_at"],
        "response_sla_breached": i["response_sla_breached"],
        "dismiss_reason_code": i["dismiss_reason_code"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def claim_view(c):
    submitted = c["submitted_for_review_at"]
    decided = c["decided_at"]
    return {
        "id": c["id"],
        "reservation_id": c["reservation_id"],
        "incident_id": c["incident_id"],
        "host_id": c["host_id"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "description": c["description"],
        "claim_state": c["claim_state"],
        "evidence_round": c["evidence_round"],
        "evidence_count": len(calc.claim_evidence_rows(c["id"])),
        "submitted_for_review_at": submitted,
        "adjudication_due_at": (submitted + hours(120))
        if submitted is not None else None,
        "sla_lapsed": c["sla_lapsed"],
        "decided_at": decided,
        "decided_by_user_id": c["decided_by_user_id"],
        "decision_reason_code": c["decision_reason_code"],
        "approved_amount_cents": c["approved_amount_cents"],
        "projected_recovery_cents": c["projected_recovery_cents"],
        "deposit_applied_cents": c["deposit_applied_cents"],
        "recovered_cents": c["recovered_cents"],
        "uncovered_cents": c["uncovered_cents"],
        "host_absorbed_cents": c["host_absorbed_cents"],
        "appeal_due_at": (decided + hours(168))
        if decided is not None else None,
        "appeal_round": c["appeal_round"],
        "appealed_by_role": c["appealed_by_role"],
        "appeal_decided_by_user_id": c["appeal_decided_by_user_id"],
        "appeal_decision": c["appeal_decision"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def settlement_summary_view(c):
    live = [a for a in calc.claim_allocations(c["id"]) if not a["voided"]]
    return {
        "approved_amount_cents": c["approved_amount_cents"],
        "deposit_applied_cents": c["deposit_applied_cents"],
        "allocation_count": len(live),
        "allocated_total_cents": sum(a["allocated_cents"] for a in live),
        "recovered_cents": c["recovered_cents"],
        "uncovered_cents": c["uncovered_cents"],
        "host_absorbed_cents": c["host_absorbed_cents"],
    }


def evidence_view(e):
    return {
        "id": e["id"],
        "claim_id": e["claim_id"],
        "evidence_type": e["evidence_type"],
        "amount_cents": e["amount_cents"],
        "captured_at": e["captured_at"],
        "file_ref": e["file_ref"],
        "uploaded_by_role": e["uploaded_by_role"],
        "uploaded_by_user_id": e["uploaded_by_user_id"],
        "evidence_round": e["evidence_round"],
        "created_at": e["created_at"],
    }


def layer_view(l):
    return {
        "id": l["id"],
        "source": l["source"],
        "layer_order": l["layer_order"],
        "limit_cents": l["limit_cents"],
        "deductible_cents": l["deductible_cents"],
        "coverage_pct": l["coverage_pct"],
        "scope": l["scope"],
        "property_id": l["property_id"],
        "layer_state": l["layer_state"],
        "consumed_cents": calc.layer_consumed_cents(l),
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def allocation_view(a):
    return {
        "id": a["id"],
        "claim_id": a["claim_id"],
        "coverage_layer_id": a["coverage_layer_id"],
        "sequence_index": a["sequence_index"],
        "gross_cents": a["gross_cents"],
        "deductible_cents": a["deductible_cents"],
        "allocated_cents": a["allocated_cents"],
        "voided": a["voided"],
        "created_at": a["created_at"],
    }


def blocklist_view(b):
    return {
        "id": b["id"],
        "guest_id": b["guest_id"],
        "scope": b["scope"],
        "property_id": b["property_id"],
        "host_id": b["host_id"],
        "supersedes_entry_id": b["supersedes_entry_id"],
        "reason_code": b["reason_code"],
        "created_by_role": b["created_by_role"],
        "created_by_user_id": b["created_by_user_id"],
        "auto_generated": b["auto_generated"],
        "entry_state": b["entry_state"],
        "dispute_window_state": b["dispute_window_state"],
        "dispute_due_at": b["created_at"] + hours(336),
        "dispute_statement_code": b["dispute_statement_code"],
        "dispute_decided_by_user_id": b["dispute_decided_by_user_id"],
        "dispute_reason_code": b["dispute_reason_code"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }
