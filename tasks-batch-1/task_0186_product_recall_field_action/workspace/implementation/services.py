"""Business logic: calculations, recomputes, cascades, mutation helpers.

All computed-field reconciliation is synchronous (PRD §2.5). Any entity touched
during a cascade independently bumps its updated_at and version (PRD §2.5).
"""
from decimal import Decimal, ROUND_HALF_UP

from db import store, iso_now


# ---------------------------------------------------------------------------
# Mutation bookkeeping (PRD §2.4 / §2.5)
# ---------------------------------------------------------------------------
def touch(entity):
    """Bump updated_at + version. AffectedLot is immutable and never touched."""
    entity["updated_at"] = iso_now()
    entity["version"] = entity["version"] + 1


def common_create_fields():
    ts = iso_now()
    return {
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


# ---------------------------------------------------------------------------
# Rounding helper (PRD §2.9 — round-half-up)
# ---------------------------------------------------------------------------
def round_half_up_int(value):
    """Round a Decimal/number to nearest integer cent, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_2dp(value):
    """Round to 2 decimal places, half up; return a float for JSON."""
    q = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Calculations (scaffold §1.3)
# ---------------------------------------------------------------------------
def classification_rule(hazard_severity, injury_reported):
    if hazard_severity == "SERIOUS" and injury_reported:
        return "CLASS_I"
    if hazard_severity == "SERIOUS" and not injury_reported:
        return "CLASS_II"
    if hazard_severity == "TEMPORARY":
        return "CLASS_II"
    return "CLASS_III"  # MINOR


def notification_window_rule(classification, regulator, injury_reported):
    if injury_reported and regulator == "CPSC":
        return 24
    if classification == "CLASS_I":
        return 24
    if classification == "CLASS_II":
        return 72 if regulator == "FDA" else 120
    return 240  # CLASS_III


def effectiveness_target(classification):
    if classification == "CLASS_I":
        return 90
    if classification == "CLASS_II":
        return 60
    return 30  # CLASS_III


def refund_amount_rule(disposition, recall):
    """Fix refund_amount_cents at the OWED -> REFUNDED transition."""
    unit = store.units[disposition["unit_id"]]
    if disposition["refund_basis"] == "SALE_PRICE":
        base_cents = unit["sale_price_cents"]
    else:  # LIST_PRICE
        lot = store.lots[unit["lot_id"]]
        product = store.products[lot["product_id"]]
        base_cents = product["unit_list_price_cents"]
    if recall["classification"] == "CLASS_I":
        return round_half_up_int(Decimal(base_cents) * Decimal("1.10"))
    return base_cents


# ---------------------------------------------------------------------------
# Affected-flag recompute (scaffold affected_unit_recompute, PRD §3.4)
# ---------------------------------------------------------------------------
def affected_lot_ids_for_recall(recall_id):
    return {
        al["lot_id"]
        for al in store.affected_lots.values()
        if al["recall_id"] == recall_id
    }


def within_serial_filter(serial_number, recall):
    lo = recall["serial_filter_start"]
    hi = recall["serial_filter_end"]
    if lo is not None and serial_number < lo:
        return False
    if hi is not None and serial_number > hi:
        return False
    return True


def recompute_affected_flags(recall):
    """Recompute affected on every unit in the recall's affected lots.

    A unit is affected iff: its lot is in the affected set, its serial is within
    the filter, AND the recall is not DRAFT. Units outside affected lots stay false.
    """
    lot_ids = affected_lot_ids_for_recall(recall["id"])
    not_draft = recall["status"] != "DRAFT"
    for unit in store.units.values():
        if unit["lot_id"] in lot_ids:
            new_val = (
                not_draft
                and within_serial_filter(unit["serial_number"], recall)
            )
            if unit["affected"] != new_val:
                unit["affected"] = new_val
                touch(unit)


def recompute_single_unit_affected(unit):
    """At unit-create time, set affected against any recall covering its lot.

    A lot may be an affected lot of at most the relevant non-DRAFT recalls; we
    evaluate against every recall whose affected-lot set contains this unit's lot.
    """
    affected = False
    for recall in store.recalls.values():
        if recall["status"] == "DRAFT":
            continue
        lot_ids = affected_lot_ids_for_recall(recall["id"])
        if unit["lot_id"] in lot_ids and within_serial_filter(
            unit["serial_number"], recall
        ):
            affected = True
            break
    unit["affected"] = affected


# ---------------------------------------------------------------------------
# Recall counter recomputes (scaffold effectiveness_recompute, refund_ledger)
# ---------------------------------------------------------------------------
def recompute_recall_counters(recall):
    """Pinned evaluation order: affected_unit_count, recovered_unit_count, pct."""
    rid = recall["id"]
    # step 1: affected universe
    affected_unit_count = sum(
        1 for u in store.units.values() if u["affected"] and _unit_in_recall(u, rid)
    )
    # step 2: recoveries — RETURNED/REPLACED dispositions on affected units
    recovered = 0
    for d in store.dispositions.values():
        if d["recall_id"] != rid:
            continue
        if d["logistics_status"] in ("RETURNED", "REPLACED"):
            unit = store.units.get(d["unit_id"])
            if unit and unit["affected"]:
                recovered += 1
    # step 3: rate
    if affected_unit_count == 0:
        eff = 0.0
    else:
        eff = pct_2dp(Decimal(recovered) / Decimal(affected_unit_count) * Decimal(100))
    recall["affected_unit_count"] = affected_unit_count
    recall["recovered_unit_count"] = recovered
    recall["effectiveness_pct"] = eff


def _unit_in_recall(unit, recall_id):
    """A unit belongs to a recall's affected universe iff its lot is an affected lot."""
    lot_ids = affected_lot_ids_for_recall(recall_id)
    return unit["lot_id"] in lot_ids


def recompute_refund_ledger(recall):
    """total_refund_cents = exact integer sum of REFUNDED dispositions' amounts."""
    rid = recall["id"]
    total = sum(
        d["refund_amount_cents"]
        for d in store.dispositions.values()
        if d["recall_id"] == rid and d["financial_status"] == "REFUNDED"
    )
    recall["total_refund_cents"] = total


# ---------------------------------------------------------------------------
# Quarantine / lot status recompute (PRD §3.7)
# ---------------------------------------------------------------------------
def recompute_lot_quarantine_status(lot):
    """HELD if any ACTIVE hold targets the lot, else RELEASED."""
    has_active = any(
        h["lot_id"] == lot["id"] and h["status"] == "ACTIVE"
        for h in store.quarantine_holds.values()
    )
    new_val = "HELD" if has_active else "RELEASED"
    if lot["quarantine_status"] != new_val:
        lot["quarantine_status"] = new_val
        touch(lot)
