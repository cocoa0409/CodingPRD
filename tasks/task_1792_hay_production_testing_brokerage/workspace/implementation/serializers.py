"""Entity -> JSON dict serializers. Computed fields are evaluated at read time
against the current logical clock."""

from db import iso_ms
from domain import shrink_tonnages, compute_quote_pricing, contract_remaining
from util import D, num_out, round2, date_str


def grower_out(g):
    return {
        "id": g["id"],
        "name": g["name"],
        "region_code": g["region_code"],
        "status": g["status"],
        "settled_tons_ytd": num_out(g["settled_tons_ytd"]),
        "outstanding_balance_cents": g["outstanding_balance_cents"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def field_out(f):
    return {
        "id": f["id"],
        "grower_id": f["grower_id"],
        "name": f["name"],
        "acres": f["acres"],
        "forage_type": f["forage_type"],
        "irrigated": f["irrigated"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def cutting_out(c):
    return {
        "id": c["id"],
        "field_id": c["field_id"],
        "cutting_number": c["cutting_number"],
        "season_year": c["season_year"],
        "planned_window_start": date_str(c["planned_window_start"]),
        "planned_window_end": date_str(c["planned_window_end"]),
        "actual_cut_date": date_str(c["actual_cut_date"]) if c["actual_cut_date"] else None,
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def weather_report_out(r):
    return {
        "id": r["id"],
        "region_code": r["region_code"],
        "report_date": date_str(r["report_date"]),
        "precipitation_mm": float(D(r["precipitation_mm"])),
        "drying_index": r["drying_index"],
        "created_at": r["created_at"],
    }


def storage_site_out(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "region_code": s["region_code"],
        "capacity_tons": num_out(s["capacity_tons"]),
        "moisture_controlled": s["moisture_controlled"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def bale_lot_out(lot):
    allocatable, physical = shrink_tonnages(lot)
    return {
        "id": lot["id"],
        "cutting_id": lot["cutting_id"],
        "storage_site_id": lot["storage_site_id"],
        "bale_type": lot["bale_type"],
        "bale_count": lot["bale_count"],
        "harvested_tonnage": num_out(lot["harvested_tonnage"]),
        "harvested_date": date_str(lot["harvested_date"]),
        "quality_tier": lot["quality_tier"],
        "certified_protein_pct": float(D(lot["certified_protein_pct"])) if lot["certified_protein_pct"] is not None else None,
        "shipped_tonnage": num_out(lot["shipped_tonnage"]),
        "spoilage_tonnage": num_out(lot["spoilage_tonnage"]),
        "open_allocated_tonnage": num_out(lot["open_allocated_tonnage"]),
        "allocatable_tonnage": float(allocatable),
        "physical_tonnage": float(physical),
        "status": lot["status"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def spoilage_event_out(e):
    return {
        "id": e["id"],
        "bale_lot_id": e["bale_lot_id"],
        "event_date": date_str(e["event_date"]),
        "tons_lost": num_out(e["tons_lost"]),
        "reason": e["reason"],
        "created_at": e["created_at"],
    }


def forage_test_out(t):
    return {
        "id": t["id"],
        "bale_lot_id": t["bale_lot_id"],
        "sample_date": date_str(t["sample_date"]),
        "lab_reference": t["lab_reference"],
        "rfv": float(D(t["rfv"])) if t["rfv"] is not None else None,
        "protein_pct": float(D(t["protein_pct"])) if t["protein_pct"] is not None else None,
        "moisture_pct": float(D(t["moisture_pct"])) if t["moisture_pct"] is not None else None,
        "resulted_by_user_id": t["resulted_by_user_id"],
        "certified_by_user_id": t["certified_by_user_id"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def market_index_out(i):
    return {
        "id": i["id"],
        "region_code": i["region_code"],
        "forage_type": i["forage_type"],
        "effective_date": date_str(i["effective_date"]),
        "price_per_ton_cents": i["price_per_ton_cents"],
        "drought_regime": i["drought_regime"],
        "created_at": i["created_at"],
    }


def buyer_out(b):
    return {
        "id": b["id"],
        "name": b["name"],
        "region_code": b["region_code"],
        "credit_limit_cents": b["credit_limit_cents"],
        "credit_used_cents": b["credit_used_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def freight_lane_out(l):
    return {
        "id": l["id"],
        "origin_region_code": l["origin_region_code"],
        "dest_region_code": l["dest_region_code"],
        "distance_miles": l["distance_miles"],
        "rate_per_mile_cents": l["rate_per_mile_cents"],
        "min_charge_cents": l["min_charge_cents"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def quote_out(q):
    # DRAFT quotes reprice SPOT on every read; non-DRAFT keep frozen values.
    if q["status"] == "DRAFT":
        try:
            pricing = compute_quote_pricing(q, "SPOT")
            q["unit_price_cents"] = pricing["unit_price_cents"]
            q["commodity_cents"] = pricing["commodity_cents"]
            q["freight_cents"] = pricing["freight_cents"]
            q["total_cents"] = pricing["total_cents"]
        except Exception:
            pass  # keep last stored pricing if spot inputs are unavailable
    return {
        "id": q["id"],
        "buyer_id": q["buyer_id"],
        "forage_type": q["forage_type"],
        "quality_tier": q["quality_tier"],
        "tons": num_out(q["tons"]),
        "origin_region_code": q["origin_region_code"],
        "dest_region_code": q["dest_region_code"],
        "requested_delivery_by": date_str(q["requested_delivery_by"]),
        "pinned_market_index_id": q["pinned_market_index_id"],
        "unit_price_cents": q["unit_price_cents"],
        "commodity_cents": q["commodity_cents"],
        "freight_cents": q["freight_cents"],
        "total_cents": q["total_cents"],
        "issued_at": iso_ms(q["issued_at"]) if q["issued_at"] else None,
        "expires_at": iso_ms(q["expires_at"]) if q["expires_at"] else None,
        "status": q["status"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }


def contract_out(c):
    return {
        "id": c["id"],
        "quote_id": c["quote_id"],
        "buyer_id": c["buyer_id"],
        "quality_tier": c["quality_tier"],
        "forage_type": c["forage_type"],
        "committed_tons": num_out(c["committed_tons"]),
        "unit_price_cents": c["unit_price_cents"],
        "total_reserved_cents": c["total_reserved_cents"],
        "delivery_deadline": date_str(c["delivery_deadline"]),
        "delivered_tons": num_out(c["delivered_tons"]),
        "open_allocated_tons": num_out(c["open_allocated_tons"]),
        "remaining_tons": float(contract_remaining(c)),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def delivery_load_out(l):
    return {
        "id": l["id"],
        "carrier_name": l["carrier_name"],
        "capacity_tons": num_out(l["capacity_tons"]),
        "planned_ship_date": date_str(l["planned_ship_date"]),
        "loaded_tons": num_out(l["loaded_tons"]),
        "logistics_status": l["logistics_status"],
        "settlement_status": l["settlement_status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def load_allocation_out(a):
    return {
        "id": a["id"],
        "delivery_load_id": a["delivery_load_id"],
        "contract_id": a["contract_id"],
        "bale_lot_id": a["bale_lot_id"],
        "tons": num_out(a["tons"]),
        "settled_gross_cents": a["settled_gross_cents"],
        "settled_commission_cents": a["settled_commission_cents"],
        "settled_net_cents": a["settled_net_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def baling_service_order_out(o):
    return {
        "id": o["id"],
        "grower_id": o["grower_id"],
        "cutting_id": o["cutting_id"],
        "scheduled_date": date_str(o["scheduled_date"]) if o["scheduled_date"] else None,
        "equipment_unit": o["equipment_unit"],
        "actual_bale_count": o["actual_bale_count"],
        "baled_moisture_pct": float(D(o["baled_moisture_pct"])) if o["baled_moisture_pct"] is not None else None,
        "invoice_cents": o["invoice_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }
