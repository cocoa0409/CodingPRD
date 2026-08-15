"""Entity -> JSON serializers. Emit plain JSON-native types only."""

from response import jn, fmt_dt


def _base(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def seller(s):
    out = _base(s)
    out.update({"full_name": s["full_name"], "email": s["email"]})
    return out


def agent(a):
    out = _base(a)
    out.update({"full_name": a["full_name"], "license_number": a["license_number"]})
    return out


def buyer(b):
    out = _base(b)
    out.update({
        "full_name": b["full_name"],
        "email": b["email"],
        "proof_of_funds_amount": jn(b["proof_of_funds_amount"]),
        "qualification_status": b["qualification_status"],
        "qualification_expires_at": b["qualification_expires_at"],
    })
    return out


def listing(l):
    out = _base(l)
    out.update({
        "seller_id": l["seller_id"],
        "agent_id": l["agent_id"],
        "title": l["title"],
        "county": l["county"],
        "state_code": l["state_code"],
        "total_gross_acres": jn(l["total_gross_acres"]),
        "packaging_strategy": l["packaging_strategy"],
        "reserve_price_total": jn(l["reserve_price_total"]),
        "status": l["status"],
    })
    return out


def tract(t):
    out = _base(t)
    out.update({
        "listing_id": t["listing_id"],
        "tract_number": t["tract_number"],
        "gross_acres": jn(t["gross_acres"]),
        "tillable_acres": jn(t["tillable_acres"]),
        "soil_productivity_index": jn(t["soil_productivity_index"]),
        "min_price": jn(t["min_price"]),
        "status": t["status"],
    })
    return out


def comparable(c):
    # ComparableSale is immutable: only id + created_at, no updated_at/version.
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "county": c["county"],
        "state_code": c["state_code"],
        "sale_date": c["sale_date"],
        "sale_price_total": jn(c["sale_price_total"]),
        "gross_acres": jn(c["gross_acres"]),
        "tillable_acres": jn(c["tillable_acres"]),
        "soil_productivity_index": jn(c["soil_productivity_index"]),
    }


def auction(a):
    out = _base(a)
    out.update({
        "listing_id": a["listing_id"],
        "agent_id": a["agent_id"],
        "method": a["method"],
        "scheduled_start": a["scheduled_start"],
        "scheduled_end": a["scheduled_end"],
        "soft_close_window_minutes": a["soft_close_window_minutes"],
        "extension_minutes": a["extension_minutes"],
        "effective_end": a["effective_end"],
        "extension_count": a["extension_count"],
        "awarded_total": jn(a["awarded_total"]) if a["awarded_total"] is not None else None,
        "status": a["status"],
    })
    return out


def bid(b):
    out = _base(b)
    out.update({
        "auction_id": b["auction_id"],
        "buyer_id": b["buyer_id"],
        # SEALED amounts are hidden (null) until the bid is REVEALED.
        "amount": None if b.get("_amount_hidden") else jn(b["amount"]),
        "tract_ids": list(b["tract_ids"]),
        "status": b["status"],
    })
    return out


def deposit(d):
    out = _base(d)
    out.update({
        "bid_id": d["bid_id"],
        "buyer_id": d["buyer_id"],
        "amount_due": jn(d["amount_due"]),
        "amount_received": jn(d["amount_received"]),
        "due_at": d["due_at"],
        "amount_refunded": jn(d["amount_refunded"]),
        "amount_forfeited": jn(d["amount_forfeited"]),
        "amount_applied": jn(d["amount_applied"]),
        "status": d["status"],
    })
    return out


def disclosure(d):
    out = _base(d)
    out.update({
        "tract_id": d["tract_id"],
        "tenant_name": d["tenant_name"],
        "lease_start_date": d["lease_start_date"],
        "lease_end_date": d["lease_end_date"],
        "annual_rent": jn(d["annual_rent"]),
        "acknowledged_by_buyer_id": d["acknowledged_by_buyer_id"],
        "status": d["status"],
    })
    return out


def rights_disposition(r):
    out = _base(r)
    out.update({
        "tract_id": r["tract_id"],
        "mineral_rights": r["mineral_rights"],
        "wind_rights": r["wind_rights"],
        "status": r["status"],
    })
    return out


def closing(c):
    out = _base(c)
    out.update({
        "auction_id": c["auction_id"],
        "target_closing_date": c["target_closing_date"],
        "payoff_amount": jn(c["payoff_amount"]),
        "title_status": c["title_status"],
        "survey_status": c["survey_status"],
        "funding_status": c["funding_status"],
        "overall_status": c["overall_status"],
    })
    return out


def statement(s):
    out = _base(s)
    out.update({
        "closing_id": s["closing_id"],
        "variant": s["variant"],
        "gross_price": jn(s["gross_price"]),
        "commission_amount": jn(s["commission_amount"]),
        "allocated_seller_costs": jn(s["allocated_seller_costs"]),
        "tract_allocations": (
            [{"tract_id": a["tract_id"], "share": jn(a["share"])} for a in s["tract_allocations"]]
            if s["tract_allocations"] is not None else None
        ),
        "payoff_amount": jn(s["payoff_amount"]),
        "rent_credit": jn(s["rent_credit"]),
        "seller_net": jn(s["seller_net"]),
        "status": s["status"],
    })
    return out
