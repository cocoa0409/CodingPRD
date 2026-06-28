"""Serializers: shape each stored entity dict for the API response body.

Computed/derived fields (PRD §2.8, §2.4) are recomputed at serialization time
from the live store so reads always reflect current state. Internal helper keys
(prefixed with '_') are stripped.

Order of fields is not contractually significant (JSON), but we present id and
audit fields consistently.
"""
from db import store


# ---- common audit projection ----
def _audit(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def serialize_client(rec):
    out = _audit(rec)
    out.update({
        "name": rec["name"],
        "storage_rate_per_pallet_cents": rec["storage_rate_per_pallet_cents"],
        "handling_rate_per_order_cents": rec["handling_rate_per_order_cents"],
        "handling_rate_per_extra_unit_cents": rec["handling_rate_per_extra_unit_cents"],
        "handling_surcharge_per_extra_carton_cents": rec["handling_surcharge_per_extra_carton_cents"],
        "carrier_discount_bps": rec["carrier_discount_bps"],
        "storage_balance_cents": rec["storage_balance_cents"],
        "handling_balance_cents": rec["handling_balance_cents"],
        "status": rec["status"],
    })
    return out


def serialize_sku(rec):
    out = _audit(rec)
    out.update({
        "client_id": rec["client_id"],
        "code": rec["code"],
        "unit_volume_cc": rec["unit_volume_cc"],
        "unit_cost_cents": rec["unit_cost_cents"],
        "hazmat": rec["hazmat"],
        "status": rec["status"],
    })
    return out


def compute_bin_occupied_cc(bin_id):
    """Sum over every lot in the bin of on_hand_qty * sku.unit_volume_cc."""
    total = 0
    for lot in store.inventory_lots.values():
        if lot["bin_id"] == bin_id:
            sku = store.skus.get(lot["sku_id"])
            vol = sku["unit_volume_cc"] if sku else 0
            total += lot["on_hand_qty"] * vol
    return total


def serialize_bin(rec):
    out = _audit(rec)
    out.update({
        "location_code": rec["location_code"],
        "bin_type": rec["bin_type"],
        "capacity_cc": rec["capacity_cc"],
        "occupied_cc": compute_bin_occupied_cc(rec["id"]),
        "status": rec["status"],
    })
    return out


def serialize_lot(rec):
    out = _audit(rec)
    out.update({
        "client_id": rec["client_id"],
        "sku_id": rec["sku_id"],
        "bin_id": rec["bin_id"],
        "receipt_id": rec["receipt_id"],
        "on_hand_qty": rec["on_hand_qty"],
        "reserved_qty": rec["reserved_qty"],
        "available_qty": rec["on_hand_qty"] - rec["reserved_qty"],
    })
    return out


def serialize_receipt(rec):
    out = _audit(rec)
    out.update({
        "client_id": rec["client_id"],
        "sku_id": rec["sku_id"],
        "bin_id": rec["bin_id"],
        "expected_qty": rec["expected_qty"],
        "received_qty": rec["received_qty"],
        "status": rec["status"],
    })
    return out


def serialize_order(rec):
    out = _audit(rec)
    total_units = sum(line["qty"] for line in rec["lines"])
    out.update({
        "client_id": rec["client_id"],
        "wave_id": rec["wave_id"],
        "ship_to_zone": rec["ship_to_zone"],
        "lines": [{"sku_id": l["sku_id"], "qty": l["qty"]} for l in rec["lines"]],
        "total_units": total_units,
        "estimated_handling_cents": rec["estimated_handling_cents"],
        "billed_handling_cents": rec["billed_handling_cents"],
        "status": rec["status"],
    })
    return out


def serialize_wave(rec):
    out = _audit(rec)
    order_count = sum(1 for o in store.orders.values() if o["wave_id"] == rec["id"])
    out.update({
        "client_id": rec["client_id"],
        "order_count": order_count,
        "status": rec["status"],
    })
    return out


def serialize_pick_task(rec):
    out = _audit(rec)
    out.update({
        "order_id": rec["order_id"],
        "lot_id": rec["lot_id"],
        "sku_id": rec["sku_id"],
        "qty": rec["qty"],
        "picked_qty": rec["picked_qty"],
        "status": rec["status"],
    })
    return out


def serialize_carton(rec):
    out = _audit(rec)
    out.update({
        "order_id": rec["order_id"],
        "packed_units": rec["packed_units"],
        "fill_volume_cc": rec["fill_volume_cc"],
        "carton_size": rec["carton_size"],
        "status": rec["status"],
    })
    return out


def serialize_shipment(rec):
    out = _audit(rec)
    out.update({
        "order_id": rec["order_id"],
        "carrier": rec["carrier"],
        "quoted_cost_cents": rec["quoted_cost_cents"],
        "tracking_number": rec["tracking_number"],
        "status": rec["status"],
    })
    return out


def serialize_return(rec):
    out = _audit(rec)
    out.update({
        "order_id": rec["order_id"],
        "client_id": rec["client_id"],
        "sku_id": rec["sku_id"],
        "bin_id": rec["bin_id"],
        "qty": rec["qty"],
        "grade": rec["grade"],
        "status": rec["status"],
    })
    return out


def serialize_cycle_count(rec):
    out = _audit(rec)
    out.update({
        "lot_id": rec["lot_id"],
        "expected_lot_version": rec["expected_lot_version"],
        "counted_qty": rec["counted_qty"],
        "variance_qty": rec["variance_qty"],
        "status": rec["status"],
    })
    return out


def serialize_charge(rec):
    # Append-only ledger event: id + created_at only (PRD §2.4).
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "client_id": rec["client_id"],
        "charge_type": rec["charge_type"],
        "amount_cents": rec["amount_cents"],
        "source_order_id": rec["source_order_id"],
        "posted": rec["posted"],
    }
