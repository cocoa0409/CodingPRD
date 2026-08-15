"""Shared business logic: serializers, derived-field reconciliation (PRD 2.8),
the airworthiness posture derivation (PRD 3.7), and the pinned invoice
calculation order (PRD 3.8).

Monetary math uses Decimal with ROUND_HALF_UP, per component, never float
(PRD 2.5).
"""

import datetime
from decimal import ROUND_HALF_UP, Decimal

import clock as clockmod
import db

# ---------------------------------------------------------------------------
# Serializers -- exact public field sets (PRD 2.4).
# Internal bookkeeping keys are underscore-prefixed and never serialized.
# ---------------------------------------------------------------------------

OWNER_F = [
    "id", "full_name", "email", "phone", "approval_cap_cents", "status",
    "created_at", "updated_at", "version",
]
AIRCRAFT_F = [
    "id", "owner_id", "tail_number", "make_model", "total_time_hours",
    "airworthiness_posture", "posture_reason",
    "created_at", "updated_at", "version",
]
MECHANIC_F = [
    "id", "full_name", "certificate_number", "certificate_class",
    "hourly_rate_cents", "status", "created_at", "updated_at", "version",
]
SLOT_F = [
    "id", "hangar_code", "aircraft_id", "starts_at", "ends_at",
    "daily_rate_cents", "status", "created_at", "updated_at", "version",
]
WO_F = [
    "id", "aircraft_id", "hangar_slot_id", "opened_by_mechanic_id",
    "scope_type", "pricing_mode", "status", "open_discrepancy_count",
    "verified_discrepancy_count", "labor_hours_tenths",
    "created_at", "updated_at", "version",
]
CHECKLIST_F = [
    "id", "work_order_id", "item_code", "description", "flat_rate_cents",
    "result", "inspected_by_mechanic_id", "created_at",
]
DISCREPANCY_F = [
    "id", "work_order_id", "checklist_item_id", "description", "severity",
    "estimated_cost_cents", "status", "requires_owner_decision",
    "decided_by_owner_id", "created_at", "updated_at", "version",
]
DIRECTIVE_F = [
    "id", "aircraft_id", "directive_type", "reference_number", "description",
    "compliance_status", "evaluated_by_mechanic_id",
    "created_at", "updated_at", "version",
]
PART_F = [
    "id", "discrepancy_id", "part_number", "serial_number", "condition",
    "trace_doc_ref", "unit_cost_cents", "quantity", "status",
    "created_at", "updated_at", "version",
]
LABOR_F = [
    "id", "work_order_id", "mechanic_id", "duration_tenths", "notes",
    "status", "created_at",
]
LOGBOOK_F = [
    "id", "aircraft_id", "work_order_id", "entry_type", "narrative",
    "signed_by_mechanic_id", "signed_at", "created_at",
]
INVOICE_F = [
    "id", "work_order_id", "labor_charge_cents", "parts_charge_cents",
    "shop_supplies_cents", "hangar_fee_cents", "tax_cents", "total_cents",
    "warranty_expires_at", "status", "created_at", "updated_at", "version",
]


def pub(record, fields):
    return {k: record.get(k) for k in fields}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Statuses that count as "open" for WorkOrder.open_discrepancy_count and for
# the posture derivation (PRD 3.3 / 3.7).
DISC_OPEN_STATUSES = ("OPEN", "PENDING_OWNER_DECISION", "APPROVED", "RECTIFIED")

# Auto-created discrepancy defaults: the inspection-completion cascade creates
# an OPEN, grounding-severity finding at the shop's standard estimate for every
# FAIL checklist item that lacks one (PRD 3.3).
AUTO_DISCREPANCY_SEVERITY = "AIRWORTHINESS"
AUTO_DISCREPANCY_ESTIMATE_CENTS = 50000

# Mechanic daily capacity: 10.0 billable hours == 100 tenths (PRD 3.6).
MECHANIC_DAILY_CAP_TENTHS = 100

WARRANTY_DAYS = 90
SUPPLIES_TIER_THRESHOLD_CENTS = 50000
SUPPLIES_LOW_RATE = Decimal("0.05")
SUPPLIES_HIGH_RATE = Decimal("0.08")
TAX_RATE = Decimal("0.0825")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def wo_discrepancies(wo_id):
    return [d for d in db.DISCREPANCIES.values() if d["work_order_id"] == wo_id]


def wo_checklist_items(wo_id):
    return [c for c in db.CHECKLIST_ITEMS.values() if c["work_order_id"] == wo_id]


def wo_labor_entries(wo_id):
    return [e for e in db.LABOR_ENTRIES.values() if e["work_order_id"] == wo_id]


def aircraft_directives(aircraft_id):
    return [d for d in db.DIRECTIVES.values() if d["aircraft_id"] == aircraft_id]


def aircraft_work_orders(aircraft_id):
    return [w for w in db.WORK_ORDERS.values() if w["aircraft_id"] == aircraft_id]


def discrepancy_parts(discrepancy_id):
    return [p for p in db.PARTS.values() if p["discrepancy_id"] == discrepancy_id]


def wo_invoices(wo_id):
    return [i for i in db.INVOICES.values() if i["work_order_id"] == wo_id]


def active_invoice_for(wo_id):
    """The single non-VOIDED invoice for a work order, if any (PRD 3.8)."""
    for inv in wo_invoices(wo_id):
        if inv["status"] != "VOIDED":
            return inv
    return None


def invoice_locked(wo_id):
    """ISSUED or PAID invoice locks labor, part installs, rectification."""
    inv = active_invoice_for(wo_id)
    return inv is not None and inv["status"] in ("ISSUED", "PAID")


def aircraft_owner(aircraft):
    return db.OWNERS.get(aircraft["owner_id"])


# ---------------------------------------------------------------------------
# Derived-field reconciliation (PRD 2.8): a server-side mutation on a
# versioned resource refreshes updated_at and increments version.
# ---------------------------------------------------------------------------

def recompute_wo_counts(wo):
    open_count = sum(
        1 for d in wo_discrepancies(wo["id"]) if d["status"] in DISC_OPEN_STATUSES
    )
    verified_count = sum(
        1 for d in wo_discrepancies(wo["id"]) if d["status"] == "VERIFIED"
    )
    labor_tenths = sum(
        e["duration_tenths"]
        for e in wo_labor_entries(wo["id"])
        if e["status"] != "VOIDED"
    )
    if (
        wo["open_discrepancy_count"] != open_count
        or wo["verified_discrepancy_count"] != verified_count
        or wo["labor_hours_tenths"] != labor_tenths
    ):
        wo["open_discrepancy_count"] = open_count
        wo["verified_discrepancy_count"] = verified_count
        wo["labor_hours_tenths"] = labor_tenths
        db.touch(wo)


def derive_posture(aircraft):
    """PRD 3.7: GROUNDED on any APPLICABLE_OPEN AD or any non-terminal
    AIRWORTHINESS discrepancy; else RESTRICTED on any non-terminal
    discrepancy; else AIRWORTHY.  Considers discrepancies across all
    non-CANCELLED work orders of the aircraft."""
    ads_open = sum(
        1
        for d in aircraft_directives(aircraft["id"])
        if d["directive_type"] == "AD" and d["compliance_status"] == "APPLICABLE_OPEN"
    )
    wos = [w for w in aircraft_work_orders(aircraft["id"]) if w["status"] != "CANCELLED"]
    discs = []
    for w in wos:
        discs.extend(wo_discrepancies(w["id"]))
    air_open = sum(
        1
        for d in discs
        if d["severity"] == "AIRWORTHINESS" and d["status"] in DISC_OPEN_STATUSES
    )
    any_open = sum(1 for d in discs if d["status"] in DISC_OPEN_STATUSES)
    if ads_open > 0:
        return "GROUNDED", "GROUNDED: %d AD directive(s) APPLICABLE_OPEN" % ads_open
    if air_open > 0:
        return (
            "GROUNDED",
            "GROUNDED: %d open airworthiness discrepancy(ies)" % air_open,
        )
    if any_open > 0:
        return "RESTRICTED", "RESTRICTED: %d open discrepancy(ies)" % any_open
    return "AIRWORTHY", "AIRWORTHY: no open ADs or discrepancies"


def recompute_posture(aircraft):
    posture, reason = derive_posture(aircraft)
    if aircraft["airworthiness_posture"] != posture or aircraft["posture_reason"] != reason:
        aircraft["airworthiness_posture"] = posture
        aircraft["posture_reason"] = reason
        db.touch(aircraft)


def recompute_posture_for(aircraft_id):
    aircraft = db.AIRCRAFT.get(aircraft_id)
    if aircraft is not None:
        recompute_posture(aircraft)


def maybe_auto_advance(wo):
    """The instant no discrepancy remains OPEN or PENDING_OWNER_DECISION, an
    AWAITING_OWNER_APPROVAL work order auto-advances to APPROVED (PRD 3.5)."""
    if wo["status"] != "AWAITING_OWNER_APPROVAL":
        return
    pending = [
        d
        for d in wo_discrepancies(wo["id"])
        if d["status"] in ("OPEN", "PENDING_OWNER_DECISION")
    ]
    if not pending:
        wo["status"] = "APPROVED"
        db.touch(wo)


# ---------------------------------------------------------------------------
# Invoice computation (PRD 3.8): pinned order
#   1. parts  2. supplies(parts)  3. labor  4. hangar  5. tax  6. total
# ---------------------------------------------------------------------------


def rhu(value):
    """Round half up to whole cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_parts_charge(wo):
    """INSTALLED parts only; per-line rounding before summation."""
    total = 0
    for disc in wo_discrepancies(wo["id"]):
        for part in discrepancy_parts(disc["id"]):
            if part["status"] != "INSTALLED":
                continue
            total += rhu(part["quantity"] * part["unit_cost_cents"])
    return total


def compute_supplies_charge(parts_total):
    """Tiered on the rounded parts total: 5% below 50000, 8% at-or-above."""
    if parts_total >= SUPPLIES_TIER_THRESHOLD_CENTS:
        return rhu(Decimal(parts_total) * SUPPLIES_HIGH_RATE)
    return rhu(Decimal(parts_total) * SUPPLIES_LOW_RATE)


def compute_labor_charge(wo):
    """Variant A (HOURLY): actual hours per POSTED entry at that mechanic's
    rate, rounded per entry then summed.  Variant B (FLAT_RATE): published
    flat_rate_cents over checklist items with result in {PASS, FAIL}."""
    if wo["pricing_mode"] == "HOURLY":
        total = 0
        for entry in wo_labor_entries(wo["id"]):
            if entry["status"] != "POSTED":
                continue
            mechanic = db.MECHANICS.get(entry["mechanic_id"])
            rate = mechanic["hourly_rate_cents"] if mechanic else 0
            hours = Decimal(entry["duration_tenths"]) / Decimal(10)
            total += rhu(hours * Decimal(rate))
        return total
    return sum(
        item["flat_rate_cents"]
        for item in wo_checklist_items(wo["id"])
        if item["result"] in ("PASS", "FAIL")
    )


def compute_hangar_fee(wo):
    """Calendar days touched by the half-open slot interval, inclusive of both
    endpoints' UTC dates, times the daily rate (PRD 3.8)."""
    slot = db.HANGAR_SLOTS.get(wo["hangar_slot_id"])
    if slot is None:
        return 0
    start_date = slot["_starts"].astimezone(clockmod.UTC).date()
    end_date = slot["_ends"].astimezone(clockmod.UTC).date()
    billing_days = (end_date - start_date).days + 1
    return billing_days * slot["daily_rate_cents"]


def compute_invoice_fields(wo):
    parts = compute_parts_charge(wo)
    supplies = compute_supplies_charge(parts)
    labor = compute_labor_charge(wo)
    hangar = compute_hangar_fee(wo)
    tax = rhu(Decimal(labor + parts + supplies) * TAX_RATE)  # hangar exempt
    total = labor + parts + supplies + hangar + tax
    return {
        "labor_charge_cents": labor,
        "parts_charge_cents": parts,
        "shop_supplies_cents": supplies,
        "hangar_fee_cents": hangar,
        "tax_cents": tax,
        "total_cents": total,
    }


def create_invoice_for(wo):
    """Auto-create the DRAFT invoice at return-to-service, honouring the
    one-active-invoice invariant."""
    if active_invoice_for(wo["id"]) is not None:
        return None
    fields = compute_invoice_fields(wo)
    warranty = clockmod.now() + datetime.timedelta(days=WARRANTY_DAYS)
    invoice = {
        "work_order_id": wo["id"],
        "labor_charge_cents": fields["labor_charge_cents"],
        "parts_charge_cents": fields["parts_charge_cents"],
        "shop_supplies_cents": fields["shop_supplies_cents"],
        "hangar_fee_cents": fields["hangar_fee_cents"],
        "tax_cents": fields["tax_cents"],
        "total_cents": fields["total_cents"],
        "warranty_expires_at": clockmod.render_instant(warranty),
        "status": "DRAFT",
    }
    db.stamp_new(invoice)
    db.INVOICES[invoice["id"]] = invoice
    return invoice


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------


def acting_mechanic():
    """Resolve the entity-backed Mechanic identity (PRD 2.1)."""
    from flask import g

    from errors import ApiError

    mechanic = db.MECHANICS.get(g.user_id)
    if mechanic is None:
        raise ApiError("ERR_NOT_FOUND", "Acting mechanic record not found.")
    return mechanic


def require_active_mechanic():
    """An INACTIVE mechanic may not drive work-order transitions (PRD 3.1)."""
    from errors import ApiError

    mechanic = acting_mechanic()
    if mechanic["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Mechanic is INACTIVE.")
    return mechanic
