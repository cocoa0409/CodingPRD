"""Shared utilities: pagination, serialization, time helpers."""
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO8601 UTC with 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(s):
    """Parse ISO8601 string into datetime. Handles trailing Z."""
    if not isinstance(s, str):
        raise errors.invalid_request("expected ISO8601 string")
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        return datetime.fromisoformat(s2)
    except Exception:
        raise errors.invalid_request(f"invalid ISO8601: {s!r}")


def pagination_params():
    """Read limit/offset from query, apply defaults and bounds."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be integer")
    if limit < 1 or limit > 100:
        raise errors.invalid_request("limit out of range [1,100]")
    if offset < 0:
        raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice sorted items."""
    total = len(items)
    return items[offset:offset + limit], total


def sort_by_created_at(rows):
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


# ---------- numeric helpers ----------
def to_decimal(value, field):
    """Convert numeric input to Decimal; raise ERR_INVALID_REQUEST on bad type."""
    if value is None:
        raise errors.invalid_request(f"{field} is required")
    if isinstance(value, bool):
        raise errors.invalid_request(f"{field} must be a number")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            raise errors.invalid_request(f"{field} must be a number")
    raise errors.invalid_request(f"{field} must be a number")


def to_int(value, field):
    if value is None:
        raise errors.invalid_request(f"{field} is required")
    if isinstance(value, bool):
        raise errors.invalid_request(f"{field} must be integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except Exception:
            pass
    raise errors.invalid_request(f"{field} must be integer")


def round_half_up_decimal(d, places):
    q = Decimal(1).scaleb(-places)  # e.g. Decimal('0.001')
    return d.quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_cents(d):
    q = Decimal(1)
    return int(d.quantize(q, rounding=ROUND_HALF_UP))


def as_float_3dp(d):
    """Serialize a Decimal as float with 3 decimal places (round-half-up)."""
    return float(round_half_up_decimal(d, 3))


# ---------- serialization ----------
def serialize_customer(c):
    return {
        "id": c["id"],
        "legal_name": c["legal_name"],
        "credit_hold": c["credit_hold"],
        "status": c["status"],
        "version": c["version"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
    }


def serialize_pricing_agreement(p):
    return {
        "id": p["id"],
        "customer_id": p["customer_id"],
        "pricing_mode": p["pricing_mode"],
        "tolling_base_fee_cents": p["tolling_base_fee_cents"],
        "tolling_per_kg_cents": p["tolling_per_kg_cents"],
        "formulated_price_per_kg_cents": p["formulated_price_per_kg_cents"],
        "over_yield_split_pct": p["over_yield_split_pct"],
        "effective_from": p["effective_from"],
        "effective_to": p["effective_to"],
        "status": p["status"],
        "version": p["version"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
    }


def serialize_lot(l):
    return {
        "id": l["id"],
        "customer_id": l["customer_id"],
        "material_code": l["material_code"],
        "ghS_class": l["ghS_class"],
        "quantity_kg_received": l["quantity_kg_received"],
        "quantity_kg_on_hand": l["quantity_kg_on_hand"],
        "quantity_kg_committed": l["quantity_kg_committed"],
        "quantity_kg_available": l["quantity_kg_available"],
        "storage_zone": l["storage_zone"],
        "received_at": l["received_at"],
        "version": l["version"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
    }


def serialize_recipe(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "revision": r["revision"],
        "customer_id": r["customer_id"],
        "target_density_kg_per_l": r["target_density_kg_per_l"],
        "theoretical_yield_pct": r["theoretical_yield_pct"],
        "components": r["components"],
        "highest_component_ghs": r["highest_component_ghs"],
        "status": r["status"],
        "version": r["version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def serialize_tank(t):
    return {
        "id": t["id"],
        "tank_code": t["tank_code"],
        "capacity_l": t["capacity_l"],
        "working_capacity_l": t["working_capacity_l"],
        "current_zone": t["current_zone"],
        "occupied_by_batch_id": t["occupied_by_batch_id"],
        "last_product_ghs": t["last_product_ghs"],
        "cleaning_state": t["cleaning_state"],
        "operational_state": t["operational_state"],
        "version": t["version"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
    }


def serialize_cleaning_record(c):
    return {
        "id": c["id"],
        "tank_id": c["tank_id"],
        "method": c["method"],
        "started_at": c["started_at"],
        "completed_at": c["completed_at"],
        "residue_ppm": c["residue_ppm"],
        "validated_by": c["validated_by"],
        "validation_outcome": c["validation_outcome"],
        "created_by": c["created_by"],
        "version": c["version"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
    }


def serialize_batch_job(b):
    return {
        "id": b["id"],
        "customer_id": b["customer_id"],
        "recipe_id": b["recipe_id"],
        "pricing_agreement_id": b["pricing_agreement_id"],
        "tank_id": b["tank_id"],
        "batch_size_l": b["batch_size_l"],
        "scheduled_start": b["scheduled_start"],
        "scheduled_end": b["scheduled_end"],
        "theoretical_output_kg": b["theoretical_output_kg"],
        "actual_output_kg": b["actual_output_kg"],
        "density_corrected_output_l": b["density_corrected_output_l"],
        "yield_variance_pct": b["yield_variance_pct"],
        "quoted_price_cents": b["quoted_price_cents"],
        "invoiced_price_cents": b["invoiced_price_cents"],
        "highest_component_ghs_snapshot": b["highest_component_ghs_snapshot"],
        "status": b["status"],
        "version": b["version"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
    }


def serialize_batch_charge(c):
    return {
        "id": c["id"],
        "batch_job_id": c["batch_job_id"],
        "raw_material_lot_id": c["raw_material_lot_id"],
        "charge_order": c["charge_order"],
        "charged_qty_kg": c["charged_qty_kg"],
        "status": c["status"],
        "version": c["version"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
    }


def serialize_sds(s):
    return {
        "id": s["id"],
        "batch_job_id": s["batch_job_id"],
        "authoring_revision": s["authoring_revision"],
        "ghs_classification": s["ghs_classification"],
        "signal_word": s["signal_word"],
        "hazard_statements": s["hazard_statements"],
        "authoring_consistency_flag": s["authoring_consistency_flag"],
        "status": s["status"],
        "version": s["version"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
    }


def serialize_package_config(p):
    return {
        "id": p["id"],
        "batch_job_id": p["batch_job_id"],
        "package_type": p["package_type"],
        "un_rated": p["un_rated"],
        "package_count": p["package_count"],
        "total_volume_l": p["total_volume_l"],
        "placard_required": p["placard_required"],
        "placard_class": p["placard_class"],
        "version": p["version"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
    }


def serialize_shipment(s):
    return {
        "id": s["id"],
        "batch_job_id": s["batch_job_id"],
        "carrier_name": s["carrier_name"],
        "vehicle_placards": s["vehicle_placards"],
        "departure_at": s["departure_at"],
        "shipped_volume_l": s["shipped_volume_l"],
        "status": s["status"],
        "version": s["version"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
    }


def serialize_heel_disposal(h):
    return {
        "id": h["id"],
        "batch_job_id": h["batch_job_id"],
        "raw_material_lot_id": h["raw_material_lot_id"],
        "heel_returned_kg": h["heel_returned_kg"],
        "heel_disposed_kg": h["heel_disposed_kg"],
        "disposal_method": h["disposal_method"],
        "waste_manifest_number": h["waste_manifest_number"],
        "disposed_at": h["disposed_at"],
        "status": h["status"],
        "version": h["version"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
    }


# ---------- lot derived quantity reconciliation ----------
def reconcile_lot_quantities(lot_id):
    """Recompute lot.quantity_kg_committed, quantity_kg_on_hand, quantity_kg_available
    from charge + heel-disposal state, per PRD §3.4."""
    import db
    lot = db.raw_material_lots.get(lot_id)
    if lot is None:
        return
    committed = Decimal("0")
    consumed = Decimal("0")
    for ch in db.batch_charges.values():
        if ch["raw_material_lot_id"] != lot_id:
            continue
        qty = Decimal(str(ch["charged_qty_kg"]))
        if ch["status"] == "COMMITTED":
            committed += qty
        elif ch["status"] == "CONSUMED":
            consumed += qty
    disposed = Decimal("0")
    for h in db.heel_disposals.values():
        if h["raw_material_lot_id"] != lot_id:
            continue
        if h["status"] == "POSTED":
            disposed += Decimal(str(h["heel_disposed_kg"]))
    received = Decimal(str(lot["quantity_kg_received"]))
    on_hand = received - consumed - disposed
    available = on_hand - committed
    lot["quantity_kg_committed"] = as_float_3dp(committed)
    lot["quantity_kg_on_hand"] = as_float_3dp(on_hand)
    lot["quantity_kg_available"] = as_float_3dp(available)
