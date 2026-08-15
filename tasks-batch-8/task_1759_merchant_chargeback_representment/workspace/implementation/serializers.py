"""Per-entity serializers. Records store datetimes as aware datetimes; output
formats them as ISO 8601 UTC with three fractional digits.

Immutable record types (ReasonCodeRule, ReserveLedgerEntry, RatioSnapshot)
carry only id + created_at: no updated_at / version (PRD 2.4).
"""

from util import iso3


def _fmt(value):
    return iso3(value) if value is not None else None


def serialize_merchant(m):
    return {
        "id": m["id"],
        "legal_name": m["legal_name"],
        "merchant_category_code": m["merchant_category_code"],
        "risk_tier": m["risk_tier"],
        "reserve_mode": m["reserve_mode"],
        "reserve_rate_bps": m["reserve_rate_bps"],
        "status": m["status"],
        "clearing_balance_cents": m["clearing_balance_cents"],
        "current_count_ratio_bps": m["current_count_ratio_bps"],
        "created_at": iso3(m["created_at"]),
        "updated_at": iso3(m["updated_at"]),
        "version": m["version"],
    }


def serialize_rule(r):
    return {
        "id": r["id"],
        "network": r["network"],
        "reason_code": r["reason_code"],
        "category": r["category"],
        "required_evidence_types": list(r["required_evidence_types"]),
        "merchant_response_days": r["merchant_response_days"],
        "representment_days": r["representment_days"],
        "chargeback_fee_cents": r["chargeback_fee_cents"],
        "effective_from": iso3(r["effective_from"]),
        "effective_to": _fmt(r["effective_to"]),
        "created_at": iso3(r["created_at"]),
    }


def serialize_transaction(t):
    return {
        "id": t["id"],
        "merchant_id": t["merchant_id"],
        "external_ref": t["external_ref"],
        "network": t["network"],
        "amount_cents": t["amount_cents"],
        "occurred_at": iso3(t["occurred_at"]),
        "status": t["status"],
        "created_at": iso3(t["created_at"]),
        "updated_at": iso3(t["updated_at"]),
        "version": t["version"],
    }


def serialize_chargeback(c):
    return {
        "id": c["id"],
        "merchant_id": c["merchant_id"],
        "transaction_external_ref": c["transaction_external_ref"],
        "transaction_id": c["transaction_id"],
        "network_case_id": c["network_case_id"],
        "reason_code": c["reason_code"],
        "network": c["network"],
        "amount_cents": c["amount_cents"],
        "received_at": iso3(c["received_at"]),
        "merchant_notified_at": _fmt(c["merchant_notified_at"]),
        "merchant_response_due_at": _fmt(c["merchant_response_due_at"]),
        "representment_due_at": iso3(c["representment_due_at"]),
        "case_status": c["case_status"],
        "funds_status": c["funds_status"],
        "recredited_cents": c["recredited_cents"],
        "is_ratio_counted": c["is_ratio_counted"],
        "created_at": iso3(c["created_at"]),
        "updated_at": iso3(c["updated_at"]),
        "version": c["version"],
    }


def serialize_evidence_item(e):
    return {
        "id": e["id"],
        "chargeback_id": e["chargeback_id"],
        "evidence_type": e["evidence_type"],
        "document_uri": e["document_uri"],
        "status": e["status"],
        "created_at": iso3(e["created_at"]),
        "updated_at": iso3(e["updated_at"]),
        "version": e["version"],
    }


def serialize_representment(r):
    return {
        "id": r["id"],
        "chargeback_id": r["chargeback_id"],
        "evidence_item_ids": list(r["evidence_item_ids"]),
        "status": r["status"],
        "cure_count": r["cure_count"],
        "submitted_at": _fmt(r["submitted_at"]),
        "won_amount_cents": r["won_amount_cents"],
        "decided_at": _fmt(r["decided_at"]),
        "created_at": iso3(r["created_at"]),
        "updated_at": iso3(r["updated_at"]),
        "version": r["version"],
    }


def serialize_fee_assessment(f):
    return {
        "id": f["id"],
        "merchant_id": f["merchant_id"],
        "chargeback_id": f["chargeback_id"],
        "enrollment_id": f["enrollment_id"],
        "kind": f["kind"],
        "amount_cents": f["amount_cents"],
        "status": f["status"],
        "assessed_by_user_id": f["assessed_by_user_id"],
        "waived_by_user_id": f["waived_by_user_id"],
        "settled_at": _fmt(f["settled_at"]),
        "waived_at": _fmt(f["waived_at"]),
        "created_at": iso3(f["created_at"]),
        "updated_at": iso3(f["updated_at"]),
        "version": f["version"],
    }


def serialize_reserve_account(a):
    return {
        "id": a["id"],
        "merchant_id": a["merchant_id"],
        "held_cents": a["held_cents"],
        "target_cents": a["target_cents"],
        "last_recomputed_at": _fmt(a["last_recomputed_at"]),
        "created_at": iso3(a["created_at"]),
        "updated_at": iso3(a["updated_at"]),
        "version": a["version"],
    }


def serialize_ledger_entry(e):
    return {
        "id": e["id"],
        "reserve_account_id": e["reserve_account_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "source_kind": e["source_kind"],
        "source_id": e["source_id"],
        "release_eligible_at": _fmt(e["release_eligible_at"]),
        "created_at": iso3(e["created_at"]),
    }


def serialize_ratio_snapshot(s):
    return {
        "id": s["id"],
        "merchant_id": s["merchant_id"],
        "network": s["network"],
        "period_month": s["period_month"],
        "sales_count": s["sales_count"],
        "sales_amount_cents": s["sales_amount_cents"],
        "chargeback_count": s["chargeback_count"],
        "gross_chargeback_count": s["gross_chargeback_count"],
        "count_ratio_bps": s["count_ratio_bps"],
        "gross_count_ratio_bps": s["gross_count_ratio_bps"],
        "computed_at": iso3(s["computed_at"]),
        "created_at": iso3(s["created_at"]),
    }


def serialize_program_enrollment(e):
    return {
        "id": e["id"],
        "merchant_id": e["merchant_id"],
        "network": e["network"],
        "program_code": e["program_code"],
        "enrolled_month": e["enrolled_month"],
        "exited_month": e["exited_month"],
        "months_over_count": e["months_over_count"],
        "status": e["status"],
        "created_at": iso3(e["created_at"]),
        "updated_at": iso3(e["updated_at"]),
        "version": e["version"],
    }


def serialize_remediation_plan(p):
    return {
        "id": p["id"],
        "enrollment_id": p["enrollment_id"],
        "root_cause_codes": list(p["root_cause_codes"]),
        "corrective_actions": list(p["corrective_actions"]),
        "status": p["status"],
        "reviewed_by_user_id": p["reviewed_by_user_id"],
        "decision_note": p["decision_note"],
        "created_at": iso3(p["created_at"]),
        "updated_at": iso3(p["updated_at"]),
        "version": p["version"],
    }


def serialize_prevention_alert(a):
    return {
        "id": a["id"],
        "transaction_id": a["transaction_id"],
        "merchant_id": a["merchant_id"],
        "alert_type": a["alert_type"],
        "received_at": iso3(a["received_at"]),
        "response_due_at": iso3(a["response_due_at"]),
        "status": a["status"],
        "created_at": iso3(a["created_at"]),
        "updated_at": iso3(a["updated_at"]),
        "version": a["version"],
    }


def serialize_education_assignment(a):
    return {
        "id": a["id"],
        "merchant_id": a["merchant_id"],
        "enrollment_ref": a["enrollment_ref"],
        "module_code": a["module_code"],
        "assigned_reason": a["assigned_reason"],
        "status": a["status"],
        "assigned_at": iso3(a["assigned_at"]),
        "completed_at": _fmt(a["completed_at"]),
        "created_at": iso3(a["created_at"]),
        "updated_at": iso3(a["updated_at"]),
        "version": a["version"],
    }
