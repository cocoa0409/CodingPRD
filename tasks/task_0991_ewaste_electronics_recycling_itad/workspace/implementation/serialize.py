"""Entity serializers — wire shapes per SCAFFOLD §1.1 and PRD §2.4."""

import clocktime


def _kg(value):
    """Decimal weight -> JSON number."""
    return float(value)


def account(a):
    return {
        "id": a["id"],
        "company_name": a["company_name"],
        "contact_email": a["contact_email"],
        "tier": a["tier"],
        "status": a["status"],
        "credit_balance_cents": a["credit_balance_cents"],
        "lifetime_diverted_kg": _kg(a["lifetime_diverted_kg"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def recycler(r, risk_score):
    return {
        "id": r["id"],
        "name": r["name"],
        "certification_standard": r["certification_standard"],
        "certification_expires_at": clocktime.fmt_dt(r["certification_expires_at"]),
        "accepted_categories": list(r["accepted_categories"]),
        "daily_intake_capacity_kg": _kg(r["daily_intake_capacity_kg"]),
        "violation_count": r["violation_count"],
        "total_processed_kg": _kg(r["total_processed_kg"]),
        "risk_score": risk_score,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def policy(p):
    return {
        "id": p["id"],
        "standard": p["standard"],
        "sanitization_methods_allowed": list(p["sanitization_methods_allowed"]),
        "export_allowed": p["export_allowed"],
        "resale_requires_verified_sanitization": p["resale_requires_verified_sanitization"],
        "is_active": p["is_active"],
        "weight_cert_freshness": p["weight_cert_freshness"],
        "weight_volume": p["weight_volume"],
        "weight_violations": p["weight_violations"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def manifest(m):
    return {
        "id": m["id"],
        "account_id": m["account_id"],
        "mode": m["mode"],
        "pickup_route": m.get("pickup_route"),
        "scheduled_start": clocktime.fmt_dt(m["scheduled_start"]) if m.get("scheduled_start") else None,
        "scheduled_end": clocktime.fmt_dt(m["scheduled_end"]) if m.get("scheduled_end") else None,
        "declared_item_count": m["declared_item_count"],
        "received_item_count": m["received_item_count"],
        "discrepancy_flag": m["discrepancy_flag"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def item(i):
    return {
        "id": i["id"],
        "manifest_id": i["manifest_id"],
        "serial_number": i["serial_number"],
        "category": i["category"],
        "weight_kg": _kg(i["weight_kg"]),
        "data_bearing": i["data_bearing"],
        "hazmat_flag": i["hazmat_flag"],
        "declared_grade": i["declared_grade"],
        "disposition": i["disposition"],
        "processing_status": i["processing_status"],
        "data_status": i["data_status"],
        "recycle_batch_id": i.get("recycle_batch_id"),
        "provisional_value_cents": i["provisional_value_cents"],
        "final_value_cents": i["final_value_cents"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def sanitization(s):
    return {
        "id": s["id"],
        "item_id": s["item_id"],
        "method": s["method"],
        "outcome": s["outcome"],
        "logged_by_id": s["logged_by_id"],
        "verified_by_id": s.get("verified_by_id"),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def listing(l):
    return {
        "id": l["id"],
        "item_id": l["item_id"],
        "asking_price_cents": l["asking_price_cents"],
        "floor_price_cents": l["floor_price_cents"],
        "channel": l["channel"],
        "sale_price_cents": l.get("sale_price_cents"),
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def batch(b):
    return {
        "id": b["id"],
        "recycler_id": b["recycler_id"],
        "scheduled_delivery_date": clocktime.fmt_dt(b["scheduled_delivery_date"]),
        "is_export": b["is_export"],
        "status": b["status"],
        "gross_weight_kg": _kg(b["gross_weight_kg"]),
        "item_count": b["item_count"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def custody_event(e):
    return {
        "id": e["id"],
        "subject_type": e["subject_type"],
        "subject_id": e["subject_id"],
        "event_type": e["event_type"],
        "from_location": e.get("from_location"),
        "to_location": e.get("to_location"),
        "actor_id": e["actor_id"],
        "created_at": e["created_at"],
    }


def certificate(c):
    return {
        "id": c["id"],
        "cert_type": c["cert_type"],
        "item_id": c.get("item_id"),
        "batch_id": c.get("batch_id"),
        "certificate_number": c["certificate_number"],
        "issued_by_id": c["issued_by_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def settlement(s):
    return {
        "id": s["id"],
        "manifest_id": s["manifest_id"],
        "kind": s["kind"],
        "status": s["status"],
        "supersedes_settlement_id": s.get("supersedes_settlement_id"),
        "gross_buyback_cents": s["gross_buyback_cents"],
        "total_fees_cents": s["total_fees_cents"],
        "volume_rebate_cents": s["volume_rebate_cents"],
        "net_amount_cents": s["net_amount_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ledger_entry(e):
    return {
        "id": e["id"],
        "account_id": e["account_id"],
        "settlement_id": e["settlement_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "balance_after_cents": e["balance_after_cents"],
        "created_at": e["created_at"],
    }
