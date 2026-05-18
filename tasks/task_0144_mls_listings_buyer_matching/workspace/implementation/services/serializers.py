"""Resource serializers — convert internal entity dicts to API payloads."""
from __future__ import annotations

from utils import iso_now


def _common(entity: dict, include_mutable: bool = True) -> dict:
    """Project the common fields onto the API payload."""
    out = {
        "id": entity["id"],
        "created_at": iso_now(entity["created_at"]),
    }
    if include_mutable:
        out["updated_at"] = iso_now(entity["updated_at"])
        out["version"] = entity["version"]
    return out


def agent(a: dict) -> dict:
    out = _common(a)
    out.update({
        "full_name": a["full_name"],
        "brokerage_name": a["brokerage_name"],
        "agent_role": a["agent_role"],
        "license_number": a["license_number"],
        "brokerage_split_pct": float(a["brokerage_split_pct"]),
        "status": a["status"],
    })
    return out


def listing(l: dict) -> dict:
    out = _common(l)
    out.update({
        "listing_agent_id": l["listing_agent_id"],
        "address_line": l["address_line"],
        "zip_code": l["zip_code"],
        "list_price_cents": l["list_price_cents"],
        "bedrooms": l["bedrooms"],
        "bathrooms": float(l["bathrooms"]),
        "features": list(l.get("features") or []),
        "co_op_pct": float(l["co_op_pct"]),
        "total_commission_pct": float(l["total_commission_pct"]),
        "status": l["status"],
        "accepted_offer_id": l.get("accepted_offer_id"),
        "showing_count": l.get("showing_count", 0),
    })
    return out


def buyer(b: dict) -> dict:
    out = _common(b)
    out.update({
        "buyer_agent_id": b["buyer_agent_id"],
        "full_name": b["full_name"],
        "max_price_cents": b["max_price_cents"],
        "min_price_cents": b["min_price_cents"],
        "min_bedrooms": b["min_bedrooms"],
        "min_bathrooms": float(b["min_bathrooms"]),
        "desired_zips": list(b.get("desired_zips") or []),
        "desired_features": list(b.get("desired_features") or []),
        "status": b["status"],
    })
    return out


def lockbox(lb: dict, include_access_code: bool = True) -> dict:
    out = _common(lb)
    out.update({
        "listing_id": lb["listing_id"],
        "serial_number": lb["serial_number"],
        "status": lb["status"],
        "code_rotated_at": iso_now(lb["code_rotated_at"]),
    })
    if include_access_code:
        out["access_code"] = lb["access_code"]
    return out


def showing(s: dict) -> dict:
    out = _common(s)
    out.update({
        "listing_id": s["listing_id"],
        "buyer_agent_id": s["buyer_agent_id"],
        "buyer_id": s["buyer_id"],
        "start_at": iso_now(s["start_at"]),
        "end_at": iso_now(s["end_at"]),
        "status": s["status"],
        "lockbox_access_granted_at": (
            iso_now(s["lockbox_access_granted_at"])
            if s.get("lockbox_access_granted_at") is not None
            else None
        ),
    })
    return out


def offer(o: dict) -> dict:
    out = _common(o)
    out.update({
        "listing_id": o["listing_id"],
        "buyer_id": o["buyer_id"],
        "offer_price_cents": o["offer_price_cents"],
        "earnest_money_cents": o["earnest_money_cents"],
        "estimated_seller_concessions_cents": o.get("estimated_seller_concessions_cents", 0),
        "round_no": o["round_no"],
        "parent_counter_id": o.get("parent_counter_id"),
        "status": o["status"],
        "expires_at": iso_now(o["expires_at"]),
        "provisional_net_to_seller_cents": o.get("provisional_net_to_seller_cents"),
    })
    return out


def counter(c: dict) -> dict:
    # Counter has no updated_at / version (PRD §2.4).
    out = _common(c, include_mutable=False)
    out.update({
        "offer_id": c["offer_id"],
        "counter_price_cents": c["counter_price_cents"],
        "counter_concessions_cents": c["counter_concessions_cents"],
        "counter_expires_at": iso_now(c["counter_expires_at"]),
        "status": c["status"],
    })
    return out


def contingency(c: dict) -> dict:
    out = _common(c)
    out.update({
        "offer_id": c["offer_id"],
        "kind": c["kind"],
        "deadline_at": iso_now(c["deadline_at"]),
        "status": c["status"],
    })
    return out


def commission_split(cs: dict) -> dict:
    # CommissionSplit has no updated_at / version (PRD §2.4).
    out = _common(cs, include_mutable=False)
    out.update({
        "listing_id": cs["listing_id"],
        "offer_id": cs["offer_id"],
        "sale_price_cents": cs["sale_price_cents"],
        "gross_commission_cents": cs["gross_commission_cents"],
        "listing_side_cents": cs["listing_side_cents"],
        "buyer_side_cents": cs["buyer_side_cents"],
        "listing_agent_cents": cs["listing_agent_cents"],
        "listing_brokerage_cents": cs["listing_brokerage_cents"],
        "buyer_agent_cents": cs["buyer_agent_cents"],
        "buyer_brokerage_cents": cs["buyer_brokerage_cents"],
        "variant": cs["variant"],
    })
    return out
