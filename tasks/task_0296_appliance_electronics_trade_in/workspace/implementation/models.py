"""Entity record construction, common-field management, and serialization.

Common fields (PRD 2.6): every persisted resource has
  - id            : server-minted UUID, no prefix
  - created_at    : ISO 8601 UTC, 3 fractional digits, set once
  - updated_at    : refreshed on every mutation
  - version       : integer, starts at 1, +1 on every mutation

`touch()` is the single mutation primitive: it refreshes updated_at and bumps
version. Per PRD 2.9 every resource touched by a cascade gets its own
updated_at/version bump.
"""
from clock import clock
from db import db
from util import new_id, iso_now


# Per-entity-type field whitelist for serialization. The order is cosmetic; the
# keys define exactly which fields appear in API output (plus the common fields).
ENTITY_FIELDS = {
    "Catalog": ["name", "currency", "price_lock_hours", "requote_tolerance_pct",
                "data_wipe_required_categories", "recycle_floor_value_cents"],
    "DeviceModel": ["catalog_id", "manufacturer", "model_code", "category",
                    "base_value_cents", "condition_multipliers", "defect_deductions",
                    "status"],
    "PromotionCampaign": ["catalog_id", "code", "category_scope", "effective_from",
                          "effective_to", "bonus_pct", "bonus_flat_cents",
                          "bonus_cap_cents", "status"],
    "Customer": ["email", "full_name", "wallet_balance_cents", "lifetime_payout_cents"],
    "TradeIn": ["customer_id", "device_model_id", "promotion_campaign_id",
                "locked_quote_id", "declared_grade", "declared_defects",
                "declared_powers_on", "status", "final_value_cents"],
    "Quote": ["trade_in_id", "kind", "graded_subtotal_cents", "promo_bonus_cents",
              "amount_cents", "lock_expires_at", "status"],
    "ShippingKit": ["trade_in_id", "tracking_number", "label_url", "status"],
    "Inspection": ["trade_in_id", "graded_at", "verified_grade", "verified_defects",
                   "verified_powers_on", "inspected_value_cents", "outcome"],
    "InspectionSlot": ["catalog_id", "lane_category", "slot_start", "slot_end",
                       "status"],
    "Payout": ["trade_in_id", "customer_id", "method", "amount_cents", "status"],
    "DataWipeCertificate": ["trade_in_id", "method", "result", "certificate_serial"],
    "DispositionRecord": ["trade_in_id", "disposition", "reason"],
}

COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]


def new_record(entity_type, fields):
    """Create a record dict with common fields stamped. Not yet stored."""
    now = iso_now(clock.now())
    rec = {
        "_type": entity_type,
        "_seq": db.next_seq(),
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Mutation primitive: refresh updated_at, bump version."""
    rec["updated_at"] = iso_now(clock.now())
    rec["version"] = rec["version"] + 1


def serialize(rec):
    """Project a stored record down to its public field set + common fields."""
    if rec is None:
        return None
    out = {}
    for f in COMMON_FIELDS:
        out[f] = rec.get(f)
    for f in ENTITY_FIELDS.get(rec["_type"], []):
        out[f] = rec.get(f)
    return out


def sort_by_created(records):
    """Ascending by created_at, ties broken by insertion sequence (PRD 2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
