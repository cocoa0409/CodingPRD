"""Serializers: record dict -> API view. Field sets follow SCAFFOLD §1.1 exactly;
computed fields are derived live at read time."""
import db
from util import fmt_dt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def owner_view(o):
    # computed: bikes_registered_count excludes MERGED bicycles (PRD §3.1)
    count = sum(
        1 for b in db.bicycles.values()
        if b["current_owner_id"] == o["id"] and b["integrity_status"] != "MERGED"
    )
    return {
        **_common(o),
        "email": o["email"],
        "full_name": o["full_name"],
        "phone": o["phone"],
        "bikes_registered_count": count,
    }


def partner_org_view(p):
    recoveries = sum(1 for i in db.intakes.values() if i["partner_org_id"] == p["id"])
    fees = sum(
        e["amount_cents"] for e in db.ledger.values()
        if e["entry_type"] == "STORAGE_FEE" and e["direction"] == "CREDIT"
        and e["partner_org_id"] == p["id"]
    )
    return {
        **_common(p),
        "name": p["name"],
        "org_type": p["org_type"],
        "jurisdiction_code": p["jurisdiction_code"],
        "contact_email": p["contact_email"],
        "status": p["status"],
        "total_recoveries_count": recoveries,
        "storage_fees_earned_cents": fees,
    }


def bicycle_view(b):
    return {
        **_common(b),
        "serial_number": b["serial_number"],
        "serial_normalized": b["serial_normalized"],
        "manufacturer": b["manufacturer"],
        "model": b["model"],
        "primary_color": b["primary_color"],
        "declared_value_cents": b["declared_value_cents"],
        "photo_url": b["photo_url"],
        "photo_hash": b["photo_hash"],
        "registration_fee_cents": b["registration_fee_cents"],
        "waiver_code_used": b["waiver_code_used"],
        "current_owner_id": b["current_owner_id"],
        "registry_status": b["registry_status"],
        "integrity_status": b["integrity_status"],
    }


def transfer_view(t):
    return {
        **_common(t),
        "bicycle_id": t["bicycle_id"],
        "from_owner_id": t["from_owner_id"],
        "to_owner_id": t["to_owner_id"],
        "to_owner_email": t["to_owner_email"],
        "sale_price_cents": t["sale_price_cents"],
        "status": t["status"],
        "expires_at": fmt_dt(t["expires_at"]),
    }


def theft_report_view(r):
    return {
        **_common(r),
        "bicycle_id": r["bicycle_id"],
        "owner_id": r["owner_id"],
        "occurred_at": fmt_dt(r["occurred_at"]),
        "theft_location": r["theft_location"],
        "police_case_number": r["police_case_number"],
        "description": r["description"],
        "status": r["status"],
        "info_request_text": r["info_request_text"],
        "response_text": r["response_text"],
        "reason_text": r.get("reason_text"),
        "flagged_at": fmt_dt(r["flagged_at"]),
    }


def intake_view(i):
    return {
        **_common(i),
        "partner_org_id": i["partner_org_id"],
        "serial_number_raw": i["serial_number_raw"],
        "serial_normalized": i["serial_normalized"],
        "manufacturer": i["manufacturer"],
        "model": i["model"],
        "primary_color": i["primary_color"],
        "photo_url": i["photo_url"],
        "photo_hash": i["photo_hash"],
        "found_at": fmt_dt(i["found_at"]),
        "found_location": i["found_location"],
        "appraised_value_cents": i["appraised_value_cents"],
        "status": i["status"],
    }


def match_view(m):
    return {
        **_common(m),
        "recovery_intake_id": m["recovery_intake_id"],
        "theft_report_id": m["theft_report_id"],
        "bicycle_id": m["bicycle_id"],
        "screening_score": m["screening_score"],
        "forensic_score": m["forensic_score"],
        "status": m["status"],
    }


def claim_view(c):
    return {
        **_common(c),
        "recovery_intake_id": c["recovery_intake_id"],
        "match_id": c["match_id"],
        "owner_id": c["owner_id"],
        "proof_text": c["proof_text"],
        "status": c["status"],
        "reason_text": c["reason_text"],
    }


def auction_view(a):
    return {
        **_common(a),
        "recovery_intake_id": a["recovery_intake_id"],
        "starts_at": fmt_dt(a["starts_at"]),
        "ends_at": fmt_dt(a["ends_at"]),
        "reserve_price_cents": a["reserve_price_cents"],
        "estimated_storage_fee_cents": a["estimated_storage_fee_cents"],
        "estimated_program_commission_cents": a["estimated_program_commission_cents"],
        "estimated_partner_payout_cents": a["estimated_partner_payout_cents"],
        "final_storage_fee_cents": a["final_storage_fee_cents"],
        "final_program_commission_cents": a["final_program_commission_cents"],
        "final_partner_payout_cents": a["final_partner_payout_cents"],
        "winning_bid_id": a["winning_bid_id"],
        "status": a["status"],
        "closed_at": fmt_dt(a["closed_at"]),
    }


def bid_view(b):
    return {
        **_common(b),
        "auction_id": b["auction_id"],
        "bidder_owner_id": b["bidder_owner_id"],
        "amount_cents": b["amount_cents"],
        "status": b["status"],
    }


def event_view(e):
    return {
        **_common(e),
        "host_org_id": e["host_org_id"],
        "title": e["title"],
        "venue": e["venue"],
        "starts_at": fmt_dt(e["starts_at"]),
        "ends_at": fmt_dt(e["ends_at"]),
        "capacity": e["capacity"],
        "registered_count": e["registered_count"],
        "status": e["status"],
    }


def registration_view(r):
    return {
        **_common(r),
        "event_id": r["event_id"],
        "owner_id": r["owner_id"],
        "status": r["status"],
        "waiver_code": r["waiver_code"],
        "waiver_used": r["waiver_used"],
    }


def duplicate_flag_view(f):
    return {
        **_common(f),
        "bicycle_a_id": f["bicycle_a_id"],
        "bicycle_b_id": f["bicycle_b_id"],
        "confidence_score": f["confidence_score"],
        "status": f["status"],
        "merged_into_bicycle_id": f["merged_into_bicycle_id"],
        "note": f["note"],
    }


def ledger_view(e):
    # LedgerEntry is append-only: id + created_at only, no updated_at/version.
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "entry_type": e["entry_type"],
        "direction": e["direction"],
        "account": e["account"],
        "amount_cents": e["amount_cents"],
        "owner_id": e["owner_id"],
        "partner_org_id": e["partner_org_id"],
        "auction_id": e["auction_id"],
        "bicycle_id": e["bicycle_id"],
        "reference_note": e["reference_note"],
    }


def notification_view(n):
    return {
        **_common(n),
        "owner_id": n["owner_id"],
        "kind": n["kind"],
        "message": n["message"],
        "related_entity_type": n["related_entity_type"],
        "related_entity_id": n["related_entity_id"],
        "read": n["read"],
    }
