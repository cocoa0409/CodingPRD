"""Entity construction, common-field management, and serialization.

Common fields (PRD §2.4):
  First-class resources carry id (UUID, no prefix), created_at, updated_at, and
  version (starts at 1, +1 on every mutation that changes the resource).
  First-class: ServicePlan, Customer, Site, Membership, Equipment, Technician,
               ServiceVisit, WarrantyClaim, RenewalOffer.
  Ledger entries (RefrigerantLog, PartUsage) carry only id + created_at — no
  updated_at, no version.
"""
import db

# Fields that live on the stored record but must NOT be serialized to clients.
_INTERNAL = {"_seq", "_kind"}

# Per-entity public field ordering (also defines what gets serialized).
PUBLIC_FIELDS = {
    "ServicePlan": [
        "id", "tier", "trade", "annual_fee_cents", "included_visits_per_year",
        "extra_visit_fee_cents", "sla_response_hours", "parts_discount_pct",
        "auto_renew_default", "active", "created_at", "updated_at", "version",
    ],
    "Customer": [
        "id", "full_name", "email", "billing_balance_cents",
        "created_at", "updated_at", "version",
    ],
    "Site": [
        "id", "customer_id", "address", "region_code", "access_notes",
        "created_at", "updated_at", "version",
    ],
    "Membership": [
        "id", "customer_id", "site_id", "plan_id", "status", "auto_renew",
        "term_start", "term_end", "visits_consumed", "term_index",
        "created_at", "updated_at", "version",
    ],
    "Equipment": [
        "id", "site_id", "model", "refrigerant_type", "nameplate_charge_grams",
        "current_charge_grams", "operational_status", "warranty_status",
        "warranty_expires_at", "created_at", "updated_at", "version",
    ],
    "Technician": [
        "id", "full_name", "region_code", "trade", "epa_certified",
        "daily_visit_capacity", "created_at", "updated_at", "version",
    ],
    "ServiceVisit": [
        "id", "membership_id", "site_id", "technician_id", "visit_kind",
        "status", "requested_at", "window_start", "window_end", "sla_met",
        "billable_charge_cents", "created_at", "updated_at", "version",
    ],
    "RefrigerantLog": [
        "id", "visit_id", "equipment_id", "action", "grams",
        "posted_by_tech_id", "created_at",
    ],
    "PartUsage": [
        "id", "visit_id", "part_name", "quantity", "list_price_cents",
        "charged_cents", "created_at",
    ],
    "WarrantyClaim": [
        "id", "equipment_id", "origin_visit_id", "status", "claimed_amount_cents",
        "approved_amount_cents", "denial_reason",
        "created_at", "updated_at", "version",
    ],
    "RenewalOffer": [
        "id", "membership_id", "offered_plan_id", "status",
        "offered_annual_fee_cents", "expires_at",
        "created_at", "updated_at", "version",
    ],
}

_FIRST_CLASS = {
    "ServicePlan", "Customer", "Site", "Membership", "Equipment", "Technician",
    "ServiceVisit", "WarrantyClaim", "RenewalOffer",
}


def new_record(kind, fields):
    """Create a record dict with common fields, stamping created_at on the clock."""
    now = db.iso(db.get_clock())
    rec = dict(fields)
    rec["id"] = db.new_id()
    rec["created_at"] = now
    rec["_seq"] = db.next_seq()
    rec["_kind"] = kind
    if kind in _FIRST_CLASS:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation bookkeeping: refresh updated_at and bump version by exactly one."""
    rec["updated_at"] = db.iso(db.get_clock())
    rec["version"] = rec["version"] + 1


def serialize(rec):
    """Project a stored record onto its public field set."""
    kind = rec["_kind"]
    fields = PUBLIC_FIELDS[kind]
    out = {}
    for f in fields:
        if f in rec:
            out[f] = rec[f]
    return out
