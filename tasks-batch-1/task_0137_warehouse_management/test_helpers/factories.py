"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Each factory returns the minimal valid create payload
and accepts **overrides for fields a test needs to control.
"""
import itertools

# Monotonic counters so default unique codes never collide within a single
# test's setup chain (the DB is empty at the start of every test).
_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


# ── Sku (PRD 3.1) ────────────────────────────────────────────────────────────
def create_sku_payload(**overrides) -> dict:
    defaults = {
        "sku_code": _uniq("SKU"),
        "description": "Test item",
        "abc_class": "C",
        "each_volume_cm3": 1,
        "min_qty": 1,
        "max_qty": 100,
    }
    defaults.update(overrides)
    return defaults


# ── Location (PRD 3.1) ───────────────────────────────────────────────────────
def create_location_payload(**overrides) -> dict:
    defaults = {
        "location_code": _uniq("LOC"),
        "zone": "RESERVE",
        "max_volume_cm3": 1000,
    }
    defaults.update(overrides)
    return defaults


# ── InboundAsn (PRD 3.2) ─────────────────────────────────────────────────────
def create_inbound_asn_payload(**overrides) -> dict:
    defaults = {
        "asn_number": _uniq("ASN"),
        "supplier_name": "Acme",
        "handling_mode": "PUTAWAY",
    }
    defaults.update(overrides)
    return defaults


# ── AsnLine (PRD 3.2) ────────────────────────────────────────────────────────
def create_asn_line_payload(sku_id, **overrides) -> dict:
    defaults = {
        "sku_id": sku_id,
        "expected_qty": 5,
    }
    defaults.update(overrides)
    return defaults


# ── ReceiptEvent (PRD 3.2) ───────────────────────────────────────────────────
def create_receipt_payload(asn_line_id, **overrides) -> dict:
    defaults = {
        "asn_line_id": asn_line_id,
        "received_qty": 5,
    }
    defaults.update(overrides)
    return defaults


# ── OutboundOrder (PRD 3.6) ──────────────────────────────────────────────────
def create_outbound_order_payload(**overrides) -> dict:
    defaults = {
        "order_number": _uniq("ORD"),
        "priority": 5,
    }
    defaults.update(overrides)
    return defaults


# ── OrderLine (PRD 3.6) ──────────────────────────────────────────────────────
def create_order_line_payload(sku_id, **overrides) -> dict:
    defaults = {
        "sku_id": sku_id,
        "ordered_qty": 5,
    }
    defaults.update(overrides)
    return defaults


# ── InventoryAllocation (PRD 3.6) ────────────────────────────────────────────
def create_allocation_payload(order_line_id, lpn_id, allocated_qty, expected_lpn_version, **overrides) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "lpn_id": lpn_id,
        "allocated_qty": allocated_qty,
        "expected_lpn_version": expected_lpn_version,
    }
    defaults.update(overrides)
    return defaults


# ── Wave (PRD 3.7) ───────────────────────────────────────────────────────────
def create_wave_payload(**overrides) -> dict:
    defaults = {
        "wave_label": _uniq("WAVE"),
    }
    defaults.update(overrides)
    return defaults


def add_order_to_wave_payload(order_id, **overrides) -> dict:
    defaults = {"order_id": order_id}
    defaults.update(overrides)
    return defaults


def release_wave_payload(expected_wave_version, **overrides) -> dict:
    defaults = {"expected_wave_version": expected_wave_version}
    defaults.update(overrides)
    return defaults


# ── PickTask confirm (PRD 3.9) ───────────────────────────────────────────────
def confirm_pick_payload(light_confirmed=True, **overrides) -> dict:
    defaults = {"light_confirmed": light_confirmed}
    defaults.update(overrides)
    return defaults


# ── CycleCount (PRD 3.10) ────────────────────────────────────────────────────
def create_cycle_count_payload(location_id, sku_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "sku_id": sku_id,
    }
    defaults.update(overrides)
    return defaults


def submit_cycle_count_payload(counted_qty, **overrides) -> dict:
    defaults = {"counted_qty": counted_qty}
    defaults.update(overrides)
    return defaults


# ── ReplenishmentTask (PRD 3.11) ─────────────────────────────────────────────
def create_replenishment_task_payload(sku_id, **overrides) -> dict:
    defaults = {"sku_id": sku_id}
    defaults.update(overrides)
    return defaults


# ── Clock (PRD 3.12) ─────────────────────────────────────────────────────────
def set_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
