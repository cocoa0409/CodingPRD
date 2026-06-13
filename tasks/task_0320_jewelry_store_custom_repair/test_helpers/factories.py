"""Payload factories — one per creatable entity, input fields only (PRD §3, §4).

Only ``source: input`` fields appear here. Computed and system fields
(status, totals, version, document_number, etc.) are never supplied.
"""
import itertools

_seq = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


# --------------------------------------------------------------------- Customer
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": _unique("customer") + "@example.com",
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------- InventoryItem
def create_inventory_item_payload(**overrides) -> dict:
    defaults = {
        "sku": _unique("SKU"),
        "title": "Test Piece",
        "metal_karat": "K18",
        "list_price_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------- Workbench
def create_workbench_payload(**overrides) -> dict:
    defaults = {"label": _unique("Bench")}
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------- Appraisal
def create_appraisal_payload(inventory_item_id: str, **overrides) -> dict:
    defaults = {
        "inventory_item_id": inventory_item_id,
        "appraiser_name": _unique("Appraiser"),
        "appointment_start": "2026-08-01T10:00:00Z",
        "appointment_end": "2026-08-01T10:30:00Z",
        "market_value_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- CustomDesignOrder
def create_custom_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "description": "Test custom commission",
        "estimated_materials_cents": 200_000,
        "design_fee_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------ RepairTicket
def create_repair_ticket_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "repair_kind": "POLISH",
        "rush": False,
        "promised_at": "2026-08-15T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------------- LayawayPlan
def create_layaway_plan_payload(customer_id: str, inventory_item_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "inventory_item_id": inventory_item_id,
        "installment_count": 4,
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- TradeInOffer
def create_trade_in_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "metal_karat": "K18",
        "metal_weight_grams": 10.0,
        "metal_spot_price_cents_per_gram": 6_000,
        "gemstone_value_cents": 0,
        "condition": "GOOD",
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------------- SpecialOrder
def create_special_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "vendor_name": "Test Vendor",
        "catalog_ref": _unique("CAT"),
        "quoted_price_cents": 300_000,
    }
    defaults.update(overrides)
    return defaults


# ----------------------------------------------------------------------- Payment
def create_payment_payload(target_type: str, **overrides) -> dict:
    """``target_type`` must be one of CUSTOM_ORDER / LAYAWAY / SPECIAL_ORDER; the
    matching FK is supplied via overrides (custom_order_id / layaway_plan_id /
    special_order_id)."""
    defaults = {
        "target_type": target_type,
        "amount_cents": 1_000,
    }
    defaults.update(overrides)
    return defaults


# ----------------------------------------------------------------- WarrantyClaim
def create_warranty_claim_payload(inventory_item_id: str, customer_id: str, **overrides) -> dict:
    defaults = {
        "inventory_item_id": inventory_item_id,
        "customer_id": customer_id,
        "defect_description": "Reported defect",
    }
    defaults.update(overrides)
    return defaults


# ------------------------------------------------------------- CreditLedgerEntry
def create_ledger_entry_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "direction": "CREDIT",
        "amount_cents": 1_000,
        "reason": "MANUAL_ADJUSTMENT",
    }
    defaults.update(overrides)
    return defaults
