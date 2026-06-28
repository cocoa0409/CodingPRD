"""Entity -> JSON serializers (scaffold §1.1 entities, PRD §2.4/§2.5).

Computed fields are recomputed fresh on read here, except Campaign
school_profit_cents / vendor_payable_cents, which are frozen snapshots stored on
the campaign at reconcile and never move thereafter.
"""

from services import calc


def _common(resource):
    return {
        "id": resource["id"],
        "created_at": resource["created_at"],
        "updated_at": resource["updated_at"],
        "version": resource["version"],
    }


def campaign(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "campaign_type": c["campaign_type"],
        "goal_cents": c["goal_cents"],
        "profit_split_pct": c["profit_split_pct"],
        "vendor_name": c["vendor_name"],
        "starts_at": c["starts_at"],
        "ends_at": c["ends_at"],
        "posture": c["posture"],
        "gross_collected_cents": calc.compute_campaign_gross_collected(c),
        "forecast_gross_cents": calc.compute_campaign_forecast_gross(c),
        "school_profit_cents": c["school_profit_cents"],
        "vendor_payable_cents": c["vendor_payable_cents"],
        "reconciled_at": c["reconciled_at"],
    })
    return out


def prize_tier(t):
    out = _common(t)
    out.update({
        "campaign_id": t["campaign_id"],
        "label": t["label"],
        "threshold_cents": t["threshold_cents"],
        "prize_description": t["prize_description"],
    })
    return out


def seller(s):
    out = _common(s)
    credited = calc.compute_seller_credited(s)
    out.update({
        "campaign_id": s["campaign_id"],
        "display_name": s["display_name"],
        "guardian_email": s["guardian_email"],
        "share_slug": s["share_slug"],
        "status": s["status"],
        "credited_cents": credited,
        "earned_prize_tier_id": calc.compute_earned_prize_tier_id(s, credited),
    })
    return out


def seller_forecast(s):
    """Forward-looking projection read (does not persist). Mirrors seller() but
    swaps the final credited figure for the forecast variant."""
    out = _common(s)
    forecast = calc.compute_forecast_credited(s)
    # The prize tier on this read reflects the same final credited figure as the
    # canonical seller read (earned prize is defined over FINAL credited_cents).
    final_credited = calc.compute_seller_credited(s)
    out.update({
        "campaign_id": s["campaign_id"],
        "display_name": s["display_name"],
        "guardian_email": s["guardian_email"],
        "share_slug": s["share_slug"],
        "status": s["status"],
        "credited_cents": final_credited,
        "forecast_credited_cents": forecast,
        "earned_prize_tier_id": calc.compute_earned_prize_tier_id(s, final_credited),
    })
    return out


def product(p):
    out = _common(p)
    out.update({
        "campaign_id": p["campaign_id"],
        "sku": p["sku"],
        "name": p["name"],
        "unit_price_cents": p["unit_price_cents"],
        "unit_cost_cents": p["unit_cost_cents"],
        "stock_qty": p["stock_qty"],
        "reserved_qty": calc.compute_reserved_qty(p),
    })
    return out


def order(o):
    out = _common(o)
    out.update({
        "campaign_id": o["campaign_id"],
        "seller_id": o["seller_id"],
        "buyer_name": o["buyer_name"],
        "buyer_email": o["buyer_email"],
        "lines": [{"product_id": l["product_id"], "quantity": l["quantity"]}
                  for l in o["lines"]],
        "payment_status": o["payment_status"],
        "fulfillment_status": o["fulfillment_status"],
        "gross_cents": o["gross_cents"],
        "tax_cents": o["tax_cents"],
        "total_charged_cents": o["total_charged_cents"],
        "receipt_number": o["receipt_number"],
    })
    return out


def pledge(p):
    out = _common(p)
    out.update({
        "campaign_id": p["campaign_id"],
        "seller_id": p["seller_id"],
        "donor_name": p["donor_name"],
        "donor_email": p["donor_email"],
        "per_unit_cents": p["per_unit_cents"],
        "flat_cents": p["flat_cents"],
        "cap_cents": p["cap_cents"],
        "units_recorded": p["units_recorded"],
        "status": p["status"],
        "pledged_amount_cents": calc.compute_pledged_amount(p),
        "collected_cents": p["collected_cents"],
        "receipt_number": p["receipt_number"],
    })
    return out


def volunteer(v):
    out = _common(v)
    out.update({
        "campaign_id": v["campaign_id"],
        "full_name": v["full_name"],
        "email": v["email"],
        "committed_minutes": calc.compute_committed_minutes(v),
    })
    return out


def shift(s):
    out = _common(s)
    out.update({
        "campaign_id": s["campaign_id"],
        "volunteer_id": s.get("volunteer_id"),
        "role_label": s["role_label"],
        "starts_at": s["starts_at"],
        "ends_at": s["ends_at"],
        "setup_buffer_minutes": s["setup_buffer_minutes"],
        "status": s["status"],
    })
    return out


def disbursement(d):
    out = _common(d)
    out.update({
        "campaign_id": d["campaign_id"],
        "school_amount_cents": d["school_amount_cents"],
        "vendor_amount_cents": d["vendor_amount_cents"],
        "memo": d["memo"],
        "status": d["status"],
    })
    return out
