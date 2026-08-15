"""Entity serializers — public views with PRD §2.4 common fields.

Decimals are converted to JSON numbers; internal bookkeeping keys (``_seq``)
are stripped.
"""

from __future__ import annotations

from util import num


def _base(rec: dict) -> dict:
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_contractor(c: dict) -> dict:
    d = _base(c)
    d.update(
        {
            "name": c["name"],
            "credit_limit_cents": c["credit_limit_cents"],
            "invoiced_balance_cents": c["invoiced_balance_cents"],
            "committed_balance_cents": c["committed_balance_cents"],
            "credit_used_cents": c["invoiced_balance_cents"] + c["committed_balance_cents"],
        }
    )
    return d


def ser_catalog_item(i: dict) -> dict:
    d = _base(i)
    d.update(
        {
            "sku": i["sku"],
            "manufacturer_name": i["manufacturer_name"],
            "sell_uom": i["sell_uom"],
            "list_price_cents": num(i["list_price_cents"]),
            "reel_length_ft": i["reel_length_ft"],
            "min_cut_ft": i["min_cut_ft"],
            "cut_charge_cents": i["cut_charge_cents"],
            "stock_on_hand": num(i["stock_on_hand"]),
            "stock_allocated": num(i["stock_allocated"]),
        }
    )
    return d


def ser_job_account(j: dict) -> dict:
    d = _base(j)
    d.update(
        {
            "contractor_id": j["contractor_id"],
            "job_name": j["job_name"],
            "jobsite_address": j["jobsite_address"],
            "pricing_mode": j["pricing_mode"],
            "escalation_cap_pct": num(j["escalation_cap_pct"]) if j["escalation_cap_pct"] is not None else None,
            "lien_waiver_required": j["lien_waiver_required"],
            "lien_waiver_expires_on": j["lien_waiver_expires_on"],
            "status": j["status"],
        }
    )
    return d


def ser_quote(q: dict) -> dict:
    d = _base(q)
    d.update(
        {
            "job_account_id": q["job_account_id"],
            "valid_until": q["valid_until"],
            "revision_no": q["revision_no"],
            "status": q["status"],
            "award_month": q["award_month"],
            "award_index_value": num(q["award_index_value"]) if q["award_index_value"] is not None else None,
        }
    )
    return d


def ser_quote_line(l: dict) -> dict:
    d = _base(l)
    d.update(
        {
            "quote_id": l["quote_id"],
            "catalog_item_id": l["catalog_item_id"],
            "qty": num(l["qty"]),
            "unit_price_cents": num(l["unit_price_cents"]),
        }
    )
    return d


def ser_substitution_request(s: dict) -> dict:
    d = _base(s)
    d.update(
        {
            "quote_line_id": s["quote_line_id"],
            "proposed_item_id": s["proposed_item_id"],
            "reason": s["reason"],
            "status": s["status"],
        }
    )
    return d


def ser_release(r: dict) -> dict:
    d = _base(r)
    d.update(
        {
            "job_account_id": r["job_account_id"],
            "quote_id": r["quote_id"],
            "status": r["status"],
            "estimated_total_cents": r["estimated_total_cents"],
            "billed_total_cents": r["billed_total_cents"],
            "truck_id": r["truck_id"],
            "delivery_date": r["delivery_date"],
            "window_start_hour": r["window_start_hour"],
            "window_end_hour": r["window_end_hour"],
            "invoiced_on": r["invoiced_on"],
        }
    )
    return d


def ser_release_line(l: dict) -> dict:
    d = _base(l)
    d.update(
        {
            "release_id": l["release_id"],
            "catalog_item_id": l["catalog_item_id"],
            "qty_requested": num(l["qty_requested"]),
            "qty_allocated": num(l["qty_allocated"]),
            "qty_shipped": num(l["qty_shipped"]),
            "billed_amount_cents": l["billed_amount_cents"],
            "status": l["status"],
        }
    )
    return d


def ser_backorder_allocation(b: dict) -> dict:
    d = _base(b)
    d.update(
        {
            "release_line_id": b["release_line_id"],
            "catalog_item_id": b["catalog_item_id"],
            "qty_open": num(b["qty_open"]),
            "status": b["status"],
        }
    )
    return d


def ser_rebate_program(p: dict) -> dict:
    d = _base(p)
    d.update(
        {
            "manufacturer_name": p["manufacturer_name"],
            "period_start": p["period_start"],
            "period_end": p["period_end"],
            "tiers": [
                {"threshold_cents": t["threshold_cents"], "rebate_pct": num(t["rebate_pct"])}
                for t in p["tiers"]
            ],
        }
    )
    return d


def ser_rebate_claim(c: dict) -> dict:
    d = _base(c)
    d.update(
        {
            "rebate_program_id": c["rebate_program_id"],
            "status": c["status"],
            "provisional_amount_cents": c["provisional_amount_cents"],
            "qualifying_base_cents": c["qualifying_base_cents"],
            "tier_pct_applied": num(c["tier_pct_applied"]) if c["tier_pct_applied"] is not None else None,
            "final_amount_cents": c["final_amount_cents"],
        }
    )
    return d
