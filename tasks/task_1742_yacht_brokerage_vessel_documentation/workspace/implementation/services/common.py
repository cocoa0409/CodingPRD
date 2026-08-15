"""Shared helpers: entity creation/touch, serializers, FK resolution."""
from db import db, new_id, utc_now_iso
from errors import err_not_found


def new_entity(common=True):
    e = {"id": new_id(), "created_at": utc_now_iso()}
    if common:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    return e


def touch(entity):
    """Bump version and refresh updated_at (common-fields entities)."""
    entity["version"] = entity.get("version", 0) + 1
    entity["updated_at"] = utc_now_iso()


def get_or_404(collection, rid, label="Resource"):
    e = collection.get(rid)
    if e is None:
        raise err_not_found(f"{label} {rid} does not exist")
    return e


# ---------------------------------------------------------------------------
# Serializers (field order is irrelevant in JSON, but keep explicit copies so
# callers can't mutate the store through a returned dict)
# ---------------------------------------------------------------------------

def serialize_brokerage(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "legal_name": b["legal_name"],
        "home_state_code": b["home_state_code"],
        "default_commission_tier_code": b["default_commission_tier_code"],
        "escrow_account_ref": b["escrow_account_ref"],
        "license_no": b["license_no"],
    }


def serialize_agent(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "brokerage_id": a["brokerage_id"],
        "full_name": a["full_name"],
        "license_no": a["license_no"],
        "split_pct_basis": a["split_pct_basis"],
        "status": a["status"],
    }


def serialize_client(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "kind": c["kind"],
        "full_name": c["full_name"],
        "residency_state_code": c["residency_state_code"],
        "tax_id_last4": c["tax_id_last4"],
        "is_entity_buyer": c["is_entity_buyer"],
    }


def serialize_vessel(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "hin": v["hin"],
        "make": v["make"],
        "model": v["model"],
        "year_built": v["year_built"],
        "length_overall_ft": v["length_overall_ft"],
        "documentation_mode": v["documentation_mode"],
        "uscg_official_no": v["uscg_official_no"],
        "state_title_no": v["state_title_no"],
        "current_location_state_code": v["current_location_state_code"],
        "liens_status": v["liens_status"],
    }


def serialize_listing(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "brokerage_id": l["brokerage_id"],
        "listing_agent_id": l["listing_agent_id"],
        "seller_id": l["seller_id"],
        "vessel_id": l["vessel_id"],
        "agreement_type": l["agreement_type"],
        "list_price_cents": l["list_price_cents"],
        "commission_tier_code": l["commission_tier_code"],
        "start_date": l["start_date"],
        "end_date": l["end_date"],
        "protection_period_days": l["protection_period_days"],
        "status": l["status"],
        "syndication_status": l["syndication_status"],
    }


def serialize_syndication_event(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "listing_id": s["listing_id"],
        "channel": s["channel"],
        "payload_price_cents": s["payload_price_cents"],
        "outcome": s["outcome"],
        "sent_at": s["sent_at"],
    }


def serialize_offer(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "listing_id": o["listing_id"],
        "buyer_id": o["buyer_id"],
        "selling_agent_id": o["selling_agent_id"],
        "offer_price_cents": o["offer_price_cents"],
        "deposit_pct_basis": o["deposit_pct_basis"],
        "acceptance_deadline": o["acceptance_deadline"],
        "settlement_state_code": o["settlement_state_code"],
        "offshore_delivery": o["offshore_delivery"],
        "status": o["status"],
        "round_no": o["round_no"],
        "parent_offer_id": o["parent_offer_id"],
    }


def serialize_contingency(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "offer_id": c["offer_id"],
        "kind": c["kind"],
        "deadline": c["deadline"],
        "status": c["status"],
        "objection_note": c["objection_note"],
    }


def serialize_escrow_entry(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "offer_id": e["offer_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
        "value_date": e["value_date"],
    }


def serialize_lien(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "vessel_id": l["vessel_id"],
        "lienholder_name": l["lienholder_name"],
        "instrument_type": l["instrument_type"],
        "amount_cents": l["amount_cents"],
        "payoff_amount_cents": l["payoff_amount_cents"],
        "priority_rank": l["priority_rank"],
        "status": l["status"],
    }


def serialize_doc_record(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "vessel_id": d["vessel_id"],
        "record_kind": d["record_kind"],
        "instrument_no": d["instrument_no"],
        "issue_date": d["issue_date"],
        "status": d["status"],
    }


def serialize_statement(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "offer_id": s["offer_id"],
        "gross_price_cents": s["gross_price_cents"],
        "commission_cents": s["commission_cents"],
        "listing_side_cents": s["listing_side_cents"],
        "selling_side_cents": s["selling_side_cents"],
        "tax_cents": s["tax_cents"],
        "prorations_cents": s["prorations_cents"],
        "escrow_applied_cents": s["escrow_applied_cents"],
        "lien_payoff_total_cents": s["lien_payoff_total_cents"],
        "seller_net_cents": s["seller_net_cents"],
        "buyer_due_cents": s["buyer_due_cents"],
        "rounding_mode": s["rounding_mode"],
        "status": s["status"],
    }


def serialize_tax_assessment(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "closing_statement_id": t["closing_statement_id"],
        "assessment_kind": t["assessment_kind"],
        "situs_state_code": t["situs_state_code"],
        "basis_cents": t["basis_cents"],
        "amount_cents": t["amount_cents"],
        "exemption_code": t["exemption_code"],
        "status": t["status"],
    }


def serialize_title_transfer(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "closing_statement_id": t["closing_statement_id"],
        "vessel_id": t["vessel_id"],
        "from_client_id": t["from_client_id"],
        "to_client_id": t["to_client_id"],
        "warranty_of_title": t["warranty_of_title"],
        "executed_at": t["executed_at"],
        "status": t["status"],
    }


def serialize_domain_event(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "aggregate_type": e["aggregate_type"],
        "aggregate_id": e["aggregate_id"],
        "event_type": e["event_type"],
        "actor_role": e["actor_role"],
        "actor_id": e["actor_id"],
        "payload": e["payload"],
    }
