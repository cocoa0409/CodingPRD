"""Serialize stored records into public API views, including computed fields."""
from db import db
from services.negotiation import offer_projection


def _base(rec, with_version=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if "updated_at" in rec:
        out["updated_at"] = rec["updated_at"]
    if with_version and "version" in rec:
        out["version"] = rec["version"]
    return out


def serialize_brokerage(rec):
    out = _base(rec)
    out.update({
        "name": rec["name"],
        "default_total_commission_pct": rec["default_total_commission_pct"],
        "default_coop_split_pct": rec["default_coop_split_pct"],
    })
    return out


def serialize_agent(rec):
    out = _base(rec)
    out.update({
        "brokerage_id": rec["brokerage_id"],
        "full_name": rec["full_name"],
        "license_no": rec["license_no"],
        "status": rec["status"],
    })
    return out


def serialize_buyer(rec):
    # Buyer: only id + created_at (append-only, no updated_at/version)
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    out.update({
        "buyer_agent_id": rec["buyer_agent_id"],
        "full_name": rec["full_name"],
        "max_budget_cents": rec["max_budget_cents"],
        "prequalified_amount_cents": rec["prequalified_amount_cents"],
        "monthly_income_cents": rec["monthly_income_cents"],
        "monthly_debt_cents": rec["monthly_debt_cents"],
    })
    return out


def _listing_posture(listing):
    offers = [o for o in db.offers.values() if o["listing_id"] == listing["id"]]
    if any(o["status"] == "ACCEPTED" for o in offers):
        return "NONE"
    live = [o for o in offers if o["status"] in ("OPEN", "SELLER_COUNTERED", "BUYER_COUNTERED")]
    if len(live) == 0:
        return "NONE"
    if len(live) == 1:
        return "SINGLE"
    return "MULTIPLE"


def serialize_listing(rec):
    out = _base(rec)
    out.update({
        "listing_agent_id": rec["listing_agent_id"],
        "address": rec["address"],
        "list_price_cents": rec["list_price_cents"],
        "total_commission_pct": rec["total_commission_pct"],
        "coop_split_pct": rec["coop_split_pct"],
        "status": rec["status"],
        "offer_posture": _listing_posture(rec),
        "accepted_offer_id": rec.get("accepted_offer_id"),
        "final_sale_price_cents": rec.get("final_sale_price_cents"),
    })
    return out


def serialize_lockbox(rec):
    out = _base(rec)
    out.update({
        "listing_id": rec["listing_id"],
        "serial_no": rec["serial_no"],
        "access_mode": rec["access_mode"],
        "turnaround_minutes": rec["turnaround_minutes"],
        "status": rec["status"],
    })
    return out


def serialize_showing(rec):
    out = _base(rec)
    out.update({
        "lockbox_id": rec["lockbox_id"],
        "buyer_agent_id": rec["buyer_agent_id"],
        "buyer_id": rec["buyer_id"],
        "start_at": rec["start_at"],
        "end_at": rec["end_at"],
        "status": rec["status"],
    })
    return out


def serialize_offer(rec):
    out = _base(rec)
    proj = offer_projection(rec)
    out.update({
        "listing_id": rec["listing_id"],
        "buyer_id": rec["buyer_id"],
        "buyer_agent_id": rec["buyer_agent_id"],
        "initial_price_cents": rec["initial_price_cents"],
        "earnest_money_cents": rec["earnest_money_cents"],
        "current_price_cents": proj["current_price_cents"],
        "current_party": proj["current_party"],
        "round_count": proj["round_count"],
        "requested_contingencies": rec["requested_contingencies"],
        "status": rec["status"],
        "effective_price_cents": rec.get("effective_price_cents"),
    })
    return out


def serialize_counter(rec):
    # CounterRound: only id + created_at (append-only)
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "offer_id": rec["offer_id"],
        "round_index": rec["round_index"],
        "by_party": rec["by_party"],
        "counter_price_cents": rec["counter_price_cents"],
        "actor_agent_id": rec["actor_agent_id"],
    }


def serialize_contingency(rec):
    out = _base(rec)
    out.update({
        "offer_id": rec["offer_id"],
        "kind": rec["kind"],
        "appraised_value_cents": rec["appraised_value_cents"],
        "status": rec["status"],
    })
    return out


def serialize_ledger(rec):
    out = _base(rec)
    out.update({
        "listing_id": rec["listing_id"],
        "sale_price_cents": rec["sale_price_cents"],
        "total_commission_cents": rec["total_commission_cents"],
        "coop_commission_cents": rec["coop_commission_cents"],
        "listing_side_commission_cents": rec["listing_side_commission_cents"],
    })
    return out
