"""Resource serialisers — produce the exact output object for each entity.

Computed fields (open_bay_count, redeemed_count, reserved/settled credit,
vehicle reminders, work-order pricing) are materialised on the stored record by
the services that mutate them, so serialisation is largely a projection. A few
live-derived fields are recomputed here on read so GET always reflects current
state (PRD §3.12: open_bay_count / redeemed credit / reserved+settled live).
"""
import db
from services import fleet as fleet_svc


def shop_out(s: dict) -> dict:
    return {
        "id": s["id"],
        "name": s["name"],
        "tax_rate": s["tax_rate"],
        "target_throughput_seconds": s["target_throughput_seconds"],
        "max_discount_pct": s["max_discount_pct"],
        "open_bay_count": _open_bay_count(s["id"]),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _open_bay_count(shop_id: str) -> int:
    return sum(1 for b in db.bays.values()
              if b["shop_id"] == shop_id and b["status"] == "OPEN")


def service_package_out(p: dict) -> dict:
    return {
        "id": p["id"],
        "shop_id": p["shop_id"],
        "oil_grade": p["oil_grade"],
        "name": p["name"],
        "base_price_cents": p["base_price_cents"],
        "included_quarts": p["included_quarts"],
        "labor_minutes": p["labor_minutes"],
        "interval_miles": p["interval_miles"],
        "interval_days": p["interval_days"],
        "requires_synthetic_certified_bay": p["requires_synthetic_certified_bay"],
        "active": p["active"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def inspection_item_out(it: dict) -> dict:
    return {
        "id": it["id"],
        "shop_id": it["shop_id"],
        "code": it["code"],
        "name": it["name"],
        "price_cents": it["price_cents"],
        "labor_minutes": it["labor_minutes"],
        "active": it["active"],
        "created_at": it["created_at"],
        "updated_at": it["updated_at"],
        "version": it["version"],
    }


def coupon_out(c: dict) -> dict:
    return {
        "id": c["id"],
        "shop_id": c["shop_id"],
        "code": c["code"],
        "discount_type": c["discount_type"],
        "percent_value": c["percent_value"],
        "flat_cents": c["flat_cents"],
        "min_subtotal_cents": c["min_subtotal_cents"],
        "stackable_with_fleet": c["stackable_with_fleet"],
        "usage_limit": c["usage_limit"],
        "redeemed_count": fleet_svc.coupon_redeemed_count(c["code"], c["shop_id"]),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def fleet_account_out(f: dict) -> dict:
    return {
        "id": f["id"],
        "shop_id": f["shop_id"],
        "company_name": f["company_name"],
        "discount_pct": f["discount_pct"],
        "credit_limit_cents": f["credit_limit_cents"],
        "reserved_credit_cents": fleet_svc.reserved_credit(f["id"]),
        "settled_credit_cents": fleet_svc.settled_credit(f["id"]),
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def vehicle_out(v: dict) -> dict:
    return {
        "id": v["id"],
        "shop_id": v["shop_id"],
        "fleet_account_id": v.get("fleet_account_id"),
        "vin": v["vin"],
        "plate": v["plate"],
        "make": v["make"],
        "model": v["model"],
        "odometer": v["odometer"],
        "last_service_odometer": v.get("last_service_odometer"),
        "last_service_date": v.get("last_service_date"),
        "next_service_odometer": v.get("next_service_odometer"),
        "next_service_date": v.get("next_service_date"),
        "service_due": _service_due(v),
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def _service_due(v: dict) -> bool:
    """service_due is true once odometer >= next_service_odometer OR
    now >= next_service_date, whichever comes first; false with no history."""
    import clock
    nso = v.get("next_service_odometer")
    nsd = v.get("next_service_date")
    if nso is None and nsd is None:
        return False
    if nso is not None and v["odometer"] >= nso:
        return True
    if nsd is not None:
        try:
            if clock.now() >= clock.parse_iso(nsd):
                return True
        except Exception:
            pass
    return False


def bay_out(b: dict) -> dict:
    return {
        "id": b["id"],
        "shop_id": b["shop_id"],
        "label": b["label"],
        "synthetic_certified": b["synthetic_certified"],
        "current_work_order_id": b.get("current_work_order_id"),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def technician_out(t: dict) -> dict:
    return {
        "id": t["id"],
        "shop_id": t["shop_id"],
        "full_name": t["full_name"],
        "synthetic_certified": t["synthetic_certified"],
        "cleanup_buffer_seconds": t["cleanup_buffer_seconds"],
        "active": t["active"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def queue_ticket_out(q: dict) -> dict:
    return {
        "id": q["id"],
        "shop_id": q["shop_id"],
        "vehicle_id": q["vehicle_id"],
        "requested_package_id": q["requested_package_id"],
        "queue_seq": q["queue_seq"],
        "assigned_bay_id": q.get("assigned_bay_id"),
        "work_order_id": q.get("work_order_id"),
        "status": q["status"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }


def work_order_out(w: dict) -> dict:
    return {
        "id": w["id"],
        "shop_id": w["shop_id"],
        "vehicle_id": w["vehicle_id"],
        "bay_id": w["bay_id"],
        "package_id": w["package_id"],
        "technician_id": w.get("technician_id"),
        "queue_ticket_id": w.get("queue_ticket_id"),
        "coupon_code": w.get("coupon_code"),
        "odometer_in": w["odometer_in"],
        "service_start_at": w.get("service_start_at"),
        "service_ready_at": w.get("service_ready_at"),
        "throughput_seconds": w.get("throughput_seconds"),
        "throughput_breach": w.get("throughput_breach"),
        "package_price_cents": w["package_price_cents"],
        "lines_total_cents": w["lines_total_cents"],
        "subtotal_cents": w["subtotal_cents"],
        "coupon_discount_cents": w["coupon_discount_cents"],
        "fleet_discount_cents": w["fleet_discount_cents"],
        "total_discount_cents": w["total_discount_cents"],
        "tax_cents": w["tax_cents"],
        "total_cents": w["total_cents"],
        "payment_method": w.get("payment_method"),
        "service_status": w["service_status"],
        "payment_status": w["payment_status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def work_order_line_out(ln: dict) -> dict:
    return {
        "id": ln["id"],
        "work_order_id": ln["work_order_id"],
        "inspection_item_id": ln["inspection_item_id"],
        "code": ln["code"],
        "price_cents": ln["price_cents"],
        "labor_minutes": ln["labor_minutes"],
        "voided": ln["voided"],
        "created_at": ln["created_at"],
        "updated_at": ln["updated_at"],
        "version": ln["version"],
    }


def service_sticker_out(s: dict) -> dict:
    # Immutable record: id + created_at only (no updated_at / version).
    return {
        "id": s["id"],
        "work_order_id": s["work_order_id"],
        "vehicle_id": s["vehicle_id"],
        "service_odometer": s["service_odometer"],
        "next_service_odometer": s["next_service_odometer"],
        "next_service_date": s["next_service_date"],
        "basis": s["basis"],
        "created_at": s["created_at"],
    }


def payment_out(p: dict) -> dict:
    return {
        "id": p["id"],
        "work_order_id": p["work_order_id"],
        "method": p["method"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
