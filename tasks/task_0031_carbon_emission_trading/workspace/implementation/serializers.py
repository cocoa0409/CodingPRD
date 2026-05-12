"""Entity-to-JSON serialization helpers."""

import clock
from helpers import fnum


def _ts(dt):
    return clock.iso_format(dt) if dt is not None else None


def enterprise_dict(e):
    return {
        "id": e["id"],
        "legal_name": e["legal_name"],
        "jurisdiction_code": e["jurisdiction_code"],
        "industry_code": e["industry_code"],
        "account_status": e["account_status"],
        "quota_balance": fnum(e["quota_balance"]),
        "paid_quota_balance": fnum(e["paid_quota_balance"]),
        "ccer_balance": fnum(e["ccer_balance"]),
        "contact_email": e["contact_email"],
        "created_at": _ts(e["created_at"]),
        "updated_at": _ts(e["updated_at"]),
        "version": e["version"],
    }


def allocation_cycle_dict(c):
    return {
        "id": c["id"],
        "cycle_year": c["cycle_year"],
        "status": c["status"],
        "free_paid_ratio": fnum(c["free_paid_ratio"]),
        "ccer_cap_pct": fnum(c["ccer_cap_pct"]),
        "publication_date": _ts(c["publication_date"]),
        "objection_deadline": _ts(c["objection_deadline"]),
        "compliance_deadline": _ts(c["compliance_deadline"]),
        "settlement_date": _ts(c["settlement_date"]),
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def allocation_dict(a):
    return {
        "id": a["id"],
        "cycle_id": a["cycle_id"],
        "enterprise_id": a["enterprise_id"],
        "method": a["method"],
        "activity_volume": fnum(a.get("activity_volume")),
        "benchmark_factor": fnum(a.get("benchmark_factor")),
        "historical_baseline": fnum(a.get("historical_baseline")),
        "total_quota": fnum(a.get("total_quota")),
        "free_quota": fnum(a.get("free_quota")),
        "paid_quota": fnum(a.get("paid_quota")),
        "status": a["status"],
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def objection_dict(o):
    return {
        "id": o["id"],
        "allocation_id": o["allocation_id"],
        "filer_enterprise_id": o["filer_enterprise_id"],
        "ground": o["ground"],
        "status": o["status"],
        "revised_total_quota": fnum(o.get("revised_total_quota")),
        "filed_at": _ts(o["filed_at"]),
        "resolved_at": _ts(o["resolved_at"]),
        "created_at": _ts(o["created_at"]),
    }


def emission_report_dict(r):
    return {
        "id": r["id"],
        "enterprise_id": r["enterprise_id"],
        "cycle_year": r["cycle_year"],
        "version": r["version"],
        "status": r["status"],
        "submission_deadline": _ts(r["submission_deadline"]),
        "submitted_at": _ts(r["submitted_at"]),
        "total_reported_emissions": fnum(r["total_reported_emissions"]),
        "total_verified_emissions": fnum(r.get("total_verified_emissions")),
        "is_current_version": r["is_current_version"],
        "supporting_document_count": r["supporting_document_count"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
    }


def emission_data_line_dict(l):
    return {
        "id": l["id"],
        "report_id": l["report_id"],
        "source_category": l["source_category"],
        "activity_data": fnum(l["activity_data"]),
        "emission_factor": fnum(l["emission_factor"]),
        "source_amount": fnum(l["source_amount"]),
        "verified_amount": fnum(l.get("verified_amount")),
        "supporting_document_id": l.get("supporting_document_id"),
        "created_at": _ts(l["created_at"]),
    }


def supporting_document_dict(d):
    return {
        "id": d["id"],
        "report_id": d["report_id"],
        "document_type": d["document_type"],
        "file_uri": d["file_uri"],
        "uploaded_at": _ts(d["uploaded_at"]),
        "created_at": _ts(d["created_at"]),
    }


def verification_assignment_dict(v):
    return {
        "id": v["id"],
        "report_id": v["report_id"],
        "agency_id": v["agency_id"],
        "scheduled_visit_at": _ts(v["scheduled_visit_at"]),
        "status": v["status"],
        "cross_check_delta_pct": fnum(v.get("cross_check_delta_pct")),
        "report_issued_at": _ts(v.get("report_issued_at")),
        "created_at": _ts(v["created_at"]),
        "updated_at": _ts(v["updated_at"]),
        "version": v["version"],
    }


def trading_order_dict(o):
    return {
        "id": o["id"],
        "enterprise_id": o["enterprise_id"],
        "side": o["side"],
        "instrument": o["instrument"],
        "order_type": o["order_type"],
        "quantity": fnum(o["quantity"]),
        "limit_price": fnum(o.get("limit_price")),
        "filled_quantity": fnum(o["filled_quantity"]),
        "status": o["status"],
        "channel": o["channel"],
        "placed_at": _ts(o["placed_at"]),
        "created_at": _ts(o["created_at"]),
        "updated_at": _ts(o["updated_at"]),
        "version": o["version"],
    }


def trade_dict(t):
    return {
        "id": t["id"],
        "buy_order_id": t["buy_order_id"],
        "sell_order_id": t["sell_order_id"],
        "instrument": t["instrument"],
        "channel": t["channel"],
        "quantity": fnum(t["quantity"]),
        "price": fnum(t["price"]),
        "gross_value": fnum(t["gross_value"]),
        "buyer_fee": fnum(t["buyer_fee"]),
        "seller_fee": fnum(t["seller_fee"]),
        "settlement_status": t["settlement_status"],
        "executed_at": _ts(t["executed_at"]),
        "created_at": _ts(t["created_at"]),
    }


def compliance_declaration_dict(d):
    return {
        "id": d["id"],
        "enterprise_id": d["enterprise_id"],
        "cycle_year": d["cycle_year"],
        "declared_offset_quota": fnum(d.get("declared_offset_quota", 0)),
        "declared_offset_ccer": fnum(d.get("declared_offset_ccer", 0)),
        "declared_borrow_amount": fnum(d.get("declared_borrow_amount", 0)),
        "declared_bank_amount": fnum(d.get("declared_bank_amount", 0)),
        "status": d["status"],
        "deficit_amount": fnum(d.get("deficit_amount", 0)),
        "surplus_amount": fnum(d.get("surplus_amount", 0)),
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def penalty_order_dict(p):
    return {
        "id": p["id"],
        "declaration_id": p["declaration_id"],
        "enterprise_id": p["enterprise_id"],
        "cycle_year": p["cycle_year"],
        "severity": p["severity"],
        "penalty_rate": fnum(p["penalty_rate"]),
        "deficit_amount": fnum(p["deficit_amount"]),
        "penalty_amount": fnum(p["penalty_amount"]),
        "mandatory_deduction_amount": fnum(p["mandatory_deduction_amount"]),
        "payment_status": p["payment_status"],
        "payment_due_at": _ts(p["payment_due_at"]),
        "paid_at": _ts(p.get("paid_at")),
        "credit_record_reported": p["credit_record_reported"],
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def annual_settlement_dict(s):
    return {
        "id": s["id"],
        "cycle_id": s["cycle_id"],
        "cycle_year": s["cycle_year"],
        "enterprise_id": s["enterprise_id"],
        "opening_quota": fnum(s["opening_quota"]),
        "net_traded_quota": fnum(s["net_traded_quota"]),
        "retired_quota": fnum(s["retired_quota"]),
        "closing_balance": fnum(s["closing_balance"]),
        "carry_forward_amount": fnum(s["carry_forward_amount"]),
        "repurchase_amount": fnum(s["repurchase_amount"]),
        "deficit_purchase_amount": fnum(s["deficit_purchase_amount"]),
        "status": s["status"],
        "created_at": _ts(s["created_at"]),
        "updated_at": _ts(s["updated_at"]),
        "version": s["version"],
    }


def audit_log_entry_dict(a):
    return {
        "id": a["id"],
        "subject_type": a["subject_type"],
        "subject_id": a["subject_id"],
        "enterprise_id": a.get("enterprise_id"),
        "action": a["action"],
        "delta_quota": fnum(a.get("delta_quota", 0)),
        "delta_ccer": fnum(a.get("delta_ccer", 0)),
        "external_system": a.get("external_system"),
        "occurred_at": _ts(a["occurred_at"]),
        "created_at": _ts(a["created_at"]),
    }
