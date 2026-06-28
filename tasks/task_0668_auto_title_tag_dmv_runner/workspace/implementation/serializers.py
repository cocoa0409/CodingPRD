"""Resource serializers — public output shapes per entity (scaffold §1.1, PRD §2.4).

Each serializer returns only the public fields. Internal bookkeeping keys
(prefixed with '_') are never emitted. Payment omits updated_at and version
(PRD §2.4 — it is immutable, id + created_at only).
"""


def account_out(a):
    return {
        "id": a["id"],
        "account_type": a["account_type"],
        "legal_name": a["legal_name"],
        "state_code": a["state_code"],
        "credit_terms": a["credit_terms"],
        "credit_limit_cents": a["credit_limit_cents"],
        "ytd_completed_count": a["ytd_completed_count"],
        "outstanding_balance_cents": a["outstanding_balance_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def fee_schedule_out(s):
    return {
        "id": s["id"],
        "state_code": s["state_code"],
        "title_fee_cents": s["title_fee_cents"],
        "registration_fee_cents": s["registration_fee_cents"],
        "transfer_fee_cents": s["transfer_fee_cents"],
        "lien_recording_fee_cents": s["lien_recording_fee_cents"],
        "use_tax_rate_bps": s["use_tax_rate_bps"],
        "trade_in_credit_allowed": s["trade_in_credit_allowed"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def transaction_out(t):
    return {
        "id": t["id"],
        "account_id": t["account_id"],
        "transaction_type": t["transaction_type"],
        "vin": t["vin"],
        "declared_price_cents": t["declared_price_cents"],
        "trade_in_allowance_cents": t["trade_in_allowance_cents"],
        "expedite": t["expedite"],
        "lifecycle_status": t["lifecycle_status"],
        "document_status": t["document_status"],
        "rejection_round": t["rejection_round"],
        "active_quote_id": t["active_quote_id"],
        "submitted_by_user_id": t["submitted_by_user_id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def document_item_out(d):
    return {
        "id": d["id"],
        "transaction_id": d["transaction_id"],
        "checklist_code": d["checklist_code"],
        "doc_status": d["doc_status"],
        "file_ref": d["file_ref"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def fee_quote_out(q):
    return {
        "id": q["id"],
        "transaction_id": q["transaction_id"],
        "variant": q["variant"],
        "schedule_id": q["schedule_id"],
        "tax_cents": q["tax_cents"],
        "state_fees_cents": q["state_fees_cents"],
        "service_fee_cents": q["service_fee_cents"],
        "total_cents": q["total_cents"],
        "status": q["status"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }


def submission_out(s):
    return {
        "id": s["id"],
        "transaction_id": s["transaction_id"],
        "submission_status": s["submission_status"],
        "priority_class": s["priority_class"],
        "sla_deadline_at": s["sla_deadline_at"],
        "leg_id": s["leg_id"],
        "rejection_reason": s["rejection_reason"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def runner_trip_out(t):
    return {
        "id": t["id"],
        "dmv_office_code": t["dmv_office_code"],
        "trip_status": t["trip_status"],
        "capacity": t["capacity"],
        "window_start_at": t["window_start_at"],
        "window_end_at": t["window_end_at"],
        "assigned_leg_count": t["assigned_leg_count"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def runner_leg_out(l):
    return {
        "id": l["id"],
        "trip_id": l["trip_id"],
        "submission_id": l["submission_id"],
        "leg_status": l["leg_status"],
        "sequence_index": l["sequence_index"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def lien_packet_out(p):
    return {
        "id": p["id"],
        "transaction_id": p["transaction_id"],
        "lender_name": p["lender_name"],
        "lien_amount_cents": p["lien_amount_cents"],
        "packet_status": p["packet_status"],
        "perfected_by_user_id": p["perfected_by_user_id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def payment_out(p):
    # PRD §2.4: Payment carries only id and created_at — no updated_at, no version.
    return {
        "id": p["id"],
        "account_id": p["account_id"],
        "transaction_id": p["transaction_id"],
        "amount_cents": p["amount_cents"],
        "kind": p["kind"],
        "created_at": p["created_at"],
    }
