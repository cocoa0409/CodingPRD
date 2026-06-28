"""Public serialization for each entity.

Each serializer emits exactly the fields the PRD/SCAFFOLD declare for that
entity, in a stable shape, omitting internal helper keys (those prefixed with
'_'). Common system fields per PRD §2.4:
  - Most entities: id, created_at, updated_at, version
  - Payment & FundLedgerEntry: id, created_at ONLY (append-only, write-once).
"""


def serialize_council(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "charter_fee_cents": c["charter_fee_cents"],
        "youth_dues_cents": c["youth_dues_cents"],
        "adult_dues_cents": c["adult_dues_cents"],
        "fund_cash_cents": c["fund_cash_cents"],
        "fund_liability_cents": c["fund_liability_cents"],
        "program_year": c["program_year"],
    }


def serialize_troop(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "council_id": t["council_id"],
        "unit_number": t["unit_number"],
        "program_type": t["program_type"],
        "charter_status": t["charter_status"],
        "recharter_posture": t["recharter_posture"],
        "registered_youth_count": t["registered_youth_count"],
        "cleared_leader_count": t["cleared_leader_count"],
        "charter_expires_at": t["charter_expires_at"],
        "dues_account_cents": t["dues_account_cents"],
    }


def serialize_member(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "troop_id": m["troop_id"],
        "member_type": m["member_type"],
        "full_name": m["full_name"],
        "birthdate": m["birthdate"],
        "rank": m["rank"],
        "registration_status": m["registration_status"],
        "dues_paid_cents": m["dues_paid_cents"],
    }


def serialize_dues_invoice(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "member_id": d["member_id"],
        "troop_id": d["troop_id"],
        "amount_cents": d["amount_cents"],
        "issued_on": d["issued_on"],
        "status": d["status"],
    }


def serialize_payment(p):
    # Append-only, write-once: only id and created_at (PRD §2.4).
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "invoice_id": p["invoice_id"],
        "member_id": p["member_id"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
    }


def serialize_leader_credential(lc):
    return {
        "id": lc["id"],
        "created_at": lc["created_at"],
        "updated_at": lc["updated_at"],
        "version": lc["version"],
        "member_id": lc["member_id"],
        "requested_by_user_id": lc["requested_by_user_id"],
        "bgcheck_status": lc["bgcheck_status"],
        "training_status": lc["training_status"],
        "training_expires_at": lc["training_expires_at"],
    }


def serialize_advancement(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "member_id": a["member_id"],
        "kind": a["kind"],
        "target": a["target"],
        "badge_code": a["badge_code"],
        "requirements_total": a["requirements_total"],
        "requirements_signed": a["requirements_signed"],
        "completion_pct": a["completion_pct"],
        "submitted_by_user_id": a["submitted_by_user_id"],
        "status": a["status"],
    }


def serialize_event(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "troop_id": e["troop_id"],
        "title": e["title"],
        "starts_at": e["starts_at"],
        "ends_at": e["ends_at"],
        "requires_health_form": e["requires_health_form"],
        "capacity": e["capacity"],
        "confirmed_count": e["confirmed_count"],
        "status": e["status"],
    }


def serialize_event_registration(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "event_id": r["event_id"],
        "member_id": r["member_id"],
        "permission_status": r["permission_status"],
        "health_status": r["health_status"],
        "status": r["status"],
    }


def serialize_fundraiser(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "council_id": f["council_id"],
        "product": f["product"],
        "unit_price_cents": f["unit_price_cents"],
        "unit_cost_cents": f["unit_cost_cents"],
        "total_inventory_units": f["total_inventory_units"],
        "allocated_units": f["allocated_units"],
        "available_units": f["available_units"],
        "status": f["status"],
    }


def serialize_fundraiser_order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "fundraiser_id": o["fundraiser_id"],
        "troop_id": o["troop_id"],
        "seller_member_id": o["seller_member_id"],
        "units": o["units"],
        "gross_cents": o["gross_cents"],
        "troop_commission_cents": o["troop_commission_cents"],
        "status": o["status"],
    }


def serialize_booth_reservation(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "fundraiser_id": b["fundraiser_id"],
        "troop_id": b["troop_id"],
        "location_code": b["location_code"],
        "starts_at": b["starts_at"],
        "ends_at": b["ends_at"],
        "status": b["status"],
    }


def serialize_fund_ledger_entry(e):
    # Append-only, write-once: only id and created_at (PRD §2.4).
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "council_id": e["council_id"],
        "troop_id": e["troop_id"],
        "account": e["account"],
        "amount_cents": e["amount_cents"],
        "source_kind": e["source_kind"],
        "source_ref_id": e["source_ref_id"],
    }
