"""Entity serializers: expose exactly the public fields of each resource.
Internal bookkeeping keys are prefixed with '_' and never serialized."""


def ser_carrier(c):
    return {
        "id": c["id"],
        "scac_code": c["scac_code"],
        "legal_name": c["legal_name"],
        "liability_model": c["liability_model"],
        "released_rate_cents_per_lb": c.get("released_rate_cents_per_lb"),
        "per_package_cap_cents": c.get("per_package_cap_cents"),
        "per_pound_cap_cents": c.get("per_pound_cap_cents"),
        "max_auto_settle_cents": c["max_auto_settle_cents"],
        "carmack_acknowledgment_days": c["carmack_acknowledgment_days"],
        "carmack_filing_days": c["carmack_filing_days"],
        "claims_filed_count": c["claims_filed_count"],
        "claims_paid_count": c["claims_paid_count"],
        "claim_ratio_bp": c["claim_ratio_bp"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_lane(l):
    return {
        "id": l["id"],
        "origin_zip3": l["origin_zip3"],
        "destination_zip3": l["destination_zip3"],
        "baseline_claim_ratio_bp": l["baseline_claim_ratio_bp"],
        "shipments_count": l["shipments_count"],
        "claims_count": l["claims_count"],
        "lane_claim_ratio_bp": l["lane_claim_ratio_bp"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_assignment(a):
    # Assignments are immutable: id + created_at only (no updated_at/version).
    return {
        "id": a["id"],
        "carrier_id": a["carrier_id"],
        "lane_id": a["lane_id"],
        "contracted_discount_pct": a["contracted_discount_pct"],
        "effective_from": a["effective_from"],
        "effective_to": a["effective_to"],
        "created_at": a["created_at"],
    }


def ser_shipment(s):
    return {
        "id": s["id"],
        "bol_number": s["bol_number"],
        "carrier_id": s["carrier_id"],
        "lane_id": s["lane_id"],
        "ship_date": s["ship_date"],
        "delivery_date": s["delivery_date"],
        "declared_value_cents": s["declared_value_cents"],
        "total_weight_lbs": s["total_weight_lbs"],
        "package_count": s["package_count"],
        "commodity_class": s["commodity_class"],
        "is_concealed_damage": s["is_concealed_damage"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "shipment_id": c["shipment_id"],
        "carrier_id": c["carrier_id"],
        "lane_id": c["lane_id"],
        "claim_type": c["claim_type"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "filing_received_at": c["filing_received_at"],
        "filing_deadline_at": c["filing_deadline_at"],
        "acknowledgment_due_at": c["acknowledgment_due_at"],
        "acknowledged_at": c["acknowledged_at"],
        "acknowledgment_late": c["acknowledgment_late"],
        "liability_assessment_id": c["liability_assessment_id"],
        "computed_liability_cents": c["computed_liability_cents"],
        "salvage_credit_cents": c["salvage_credit_cents"],
        "net_exposure_cents": c["net_exposure_cents"],
        "reserve_amount_cents": c["reserve_amount_cents"],
        "settlement_amount_cents": c["settlement_amount_cents"],
        "appeal_round": c["appeal_round"],
        "filing_status": c["filing_status"],
        "payment_status": c["payment_status"],
        "concurrency_token": c["concurrency_token"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_document(d):
    return {
        "id": d["id"],
        "claim_id": d["claim_id"],
        "document_kind": d["document_kind"],
        "storage_uri": d["storage_uri"],
        "captured_at": d["captured_at"],
        "verification_status": d["verification_status"],
        "rejection_reason": d["rejection_reason"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_assessment(a):
    return {
        "id": a["id"],
        "claim_id": a["claim_id"],
        "assessed_by_user_id": a["assessed_by_user_id"],
        "liability_model_applied": a["liability_model_applied"],
        "limitation_basis_cents": a["limitation_basis_cents"],
        "carrier_limit_cents": a["carrier_limit_cents"],
        "lane_discount_pct": a["lane_discount_pct"],
        "computed_liability_cents": a["computed_liability_cents"],
        "negligence_flag": a["negligence_flag"],
        "state": a["state"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_salvage(s):
    return {
        "id": s["id"],
        "claim_id": s["claim_id"],
        "disposition_kind": s["disposition_kind"],
        "gross_proceeds_cents": s["gross_proceeds_cents"],
        "handling_cost_cents": s["handling_cost_cents"],
        "net_credit_cents": s["net_credit_cents"],
        "scheduled_at": s["scheduled_at"],
        "state": s["state"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_appeal(a):
    return {
        "id": a["id"],
        "claim_id": a["claim_id"],
        "round_number": a["round_number"],
        "opened_by_user_id": a["opened_by_user_id"],
        "justification": a["justification"],
        "requested_amount_cents": a["requested_amount_cents"],
        "decision": a["decision"],
        "decided_amount_cents": a["decided_amount_cents"],
        "escalated_to_user_id": a["escalated_to_user_id"],
        "state": a["state"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_settlement(s):
    return {
        "id": s["id"],
        "claim_id": s["claim_id"],
        "round_number": s["round_number"],
        "offered_by_role": s["offered_by_role"],
        "amount_cents": s["amount_cents"],
        "authority_tier_required": s["authority_tier_required"],
        "approved_by_user_id": s["approved_by_user_id"],
        "state": s["state"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_subrogation(s):
    return {
        "id": s["id"],
        "claim_id": s["claim_id"],
        "responsible_party_kind": s["responsible_party_kind"],
        "responsible_party_name": s["responsible_party_name"],
        "target_recovery_cents": s["target_recovery_cents"],
        "recovered_cents": s["recovered_cents"],
        "recovery_ratio_bp": s["recovery_ratio_bp"],
        "state": s["state"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_reserve(r, suggested=None):
    out = {
        "id": r["id"],
        "claim_id": r["claim_id"],
        "amount_cents": r["amount_cents"],
        "posted_by_user_id": r["posted_by_user_id"],
        "posted_at": r["posted_at"],
        "released_at": r["released_at"],
        "state": r["state"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
    if suggested is not None:
        out["suggested_reserve_cents"] = suggested
    return out


def ser_event(e):
    # Events are append-only: id + created_at only (no updated_at/version).
    return {
        "id": e["id"],
        "claim_id": e["claim_id"],
        "event_kind": e["event_kind"],
        "actor_user_id": e["actor_user_id"],
        "event_at": e["event_at"],
        "payload_json": e["payload_json"],
        "created_at": e["created_at"],
    }


def ser_calendar(c):
    return {
        "id": c["id"],
        "calendar_date": c["calendar_date"],
        "is_business_day": c["is_business_day"],
        "day_kind": c["day_kind"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
