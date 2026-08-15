"""Business logic: stamping, serializers, and shared calculation helpers.

All money is integer cents. All percentages are numbers with 2 decimal
places, rounded half up (PRD section 2.5).
"""

from decimal import Decimal, ROUND_HALF_UP

import db
import errors as E
from errors import ApiError
from util import fmt_dt, utcnow

# Pinned calculation constants (SCAFFOLD.yaml section 1.3)
HOLD_WASTE_MULTIPLIER = Decimal("1.5")
CONSIGNMENT_WASTE_MULTIPLIER = Decimal("1.0")
OPEN_WASTE_MULTIPLIER = Decimal("1.0")
WASTE_FLAG_THRESHOLD_PCT = Decimal("20.0")
SURGEON_TURNOVER_MINUTES = 30

PCT_Q = Decimal("0.01")


# ---------------------------------------------------------------------------
# Entity bookkeeping
# ---------------------------------------------------------------------------

def stamp_new(entity):
    now = utcnow()
    entity["id"] = db.new_id()
    entity["_seq"] = db.next_seq()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def bump(entity):
    """Every mutation increments version by one and refreshes updated_at."""
    entity["updated_at"] = utcnow()
    entity["version"] = entity.get("version", 1) + 1


def round_pct(value):
    """Round a Decimal to 2 decimal places, half up; return as a JSON number."""
    return float(value.quantize(PCT_Q, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_or_404(store, rid, label="Resource"):
    obj = store.get(rid)
    if obj is None:
        raise ApiError(E.ERR_NOT_FOUND, f"{label} '{rid}' not found", 404)
    return obj


def pick_list_for_case(case_id):
    for pl in db.pick_lists.values():
        if pl["case_id"] == case_id:
            return pl
    return None


def lines_of_card(card_id):
    out = [l for l in db.card_lines.values() if l["card_id"] == card_id]
    out.sort(key=lambda l: (l["pick_sequence"], l["created_at"], l["_seq"]))
    return out


def lines_of_pick_list(pick_list_id):
    out = [l for l in db.pick_list_lines.values() if l["pick_list_id"] == pick_list_id]
    out.sort(key=lambda l: (l["pick_sequence"], l["created_at"], l["_seq"]))
    return out


def picked_item_of_line(line):
    """The item a pick line drew stock from: the substitute when SUBSTITUTED."""
    if line["status"] == "SUBSTITUTED" and line["substituted_item_id"]:
        return db.supply_items.get(line["substituted_item_id"])
    return db.supply_items.get(line["supply_item_id"])


def recompute_card_estimated_cost(card):
    """card_estimated_cost: SUM over current lines of qty x item unit cost."""
    total = 0
    for line in db.card_lines.values():
        if line["card_id"] != card["id"]:
            continue
        item = db.supply_items.get(line["supply_item_id"])
        if item is not None:
            total += line["quantity"] * item["unit_cost_cents"]
    card["estimated_cost_cents"] = total


def waste_charge_for(usage, item, designation):
    """waste_charge: per-line round_half_up to whole cents (never summed raw)."""
    qty_wasted = usage["qty_wasted"]
    if qty_wasted == 0:
        return 0
    if item is not None and item["consignment_flag"]:
        mult = CONSIGNMENT_WASTE_MULTIPLIER
    elif designation == "HOLD":
        mult = HOLD_WASTE_MULTIPLIER
    else:
        mult = OPEN_WASTE_MULTIPLIER
    raw = Decimal(qty_wasted) * Decimal(usage["unit_cost_cents"]) * mult
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_surgeon(s):
    out = {
        "full_name": s["full_name"],
        "specialty": s["specialty"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_supply_item(i):
    out = {
        "sku": i["sku"],
        "name": i["name"],
        "unit_cost_cents": i["unit_cost_cents"],
        "substitute_group": i["substitute_group"],
        "consignment_flag": i["consignment_flag"],
        "on_hand_quantity": i["on_hand_quantity"],
        "status": i["status"],
    }
    out.update(_common(i))
    return out


def ser_card(c):
    out = {
        "surgeon_id": c["surgeon_id"],
        "procedure_name": c["procedure_name"],
        "version_number": c["version_number"],
        "status": c["status"],
        "estimated_cost_cents": c["estimated_cost_cents"],
        "flagged_audit_count": c["flagged_audit_count"],
        "rolling_line_match_pct": c["rolling_line_match_pct"],
    }
    out.update(_common(c))
    return out


def ser_card_line(l):
    out = {
        "card_id": l["card_id"],
        "supply_item_id": l["supply_item_id"],
        "quantity": l["quantity"],
        "designation": l["designation"],
        "pick_sequence": l["pick_sequence"],
        "notes": l["notes"],
    }
    out.update(_common(l))
    return out


def ser_case(c):
    out = {
        "surgeon_id": c["surgeon_id"],
        "card_id": c["card_id"],
        "pinned_card_version_number": c["pinned_card_version_number"],
        "procedure_name": c["procedure_name"],
        "scheduled_start": fmt_dt(c["scheduled_start"]),
        "expected_duration_min": c["expected_duration_min"],
        "room": c["room"],
        "consignment_budget_cents": c["consignment_budget_cents"],
        "status": c["status"],
        "standard_cost_cents": c["standard_cost_cents"],
        "actual_cost_cents": c["actual_cost_cents"],
        "waste_cost_cents": c["waste_cost_cents"],
        "pick_exception_count": c["pick_exception_count"],
    }
    out.update(_common(c))
    return out


def ser_pick_list(p):
    out = {
        "case_id": p["case_id"],
        "card_id": p["card_id"],
        "card_version_number": p["card_version_number"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def ser_pick_list_line(l):
    out = {
        "pick_list_id": l["pick_list_id"],
        "supply_item_id": l["supply_item_id"],
        "designation": l["designation"],
        "qty_requested": l["qty_requested"],
        "qty_picked": l["qty_picked"],
        "qty_returned_unopened": l["qty_returned_unopened"],
        "unit_cost_cents": l["unit_cost_cents"],
        "pick_sequence": l["pick_sequence"],
        "status": l["status"],
        "substituted_item_id": l["substituted_item_id"],
        "short_reason_code": l["short_reason_code"],
    }
    out.update(_common(l))
    return out


def ser_usage_record(u):
    out = {
        "case_id": u["case_id"],
        "pick_list_line_id": u["pick_list_line_id"],
        "supply_item_id": u["supply_item_id"],
        "qty_opened": u["qty_opened"],
        "qty_used": u["qty_used"],
        "qty_wasted": u["qty_wasted"],
        "unit_cost_cents": u["unit_cost_cents"],
        "waste_charge_cents": u["waste_charge_cents"],
    }
    out.update(_common(u))
    return out


def ser_audit(a):
    out = {
        "case_id": a["case_id"],
        "card_id": a["card_id"],
        "card_version_number": a["card_version_number"],
        "matched_line_count": a["matched_line_count"],
        "total_line_count": a["total_line_count"],
        "line_match_pct": a["line_match_pct"],
        "spend_match_pct": a["spend_match_pct"],
        "waste_pct": a["waste_pct"],
        "waste_flag": a["waste_flag"],
        "status": a["status"],
        "dispute_comment": a["dispute_comment"],
    }
    out.update(_common(a))
    return out


def ser_product_request(r):
    out = {
        "surgeon_id": r["surgeon_id"],
        "proposed_item_name": r["proposed_item_name"],
        "proposed_sku": r["proposed_sku"],
        "estimated_unit_cost_cents": r["estimated_unit_cost_cents"],
        "rationale": r["rationale"],
        "substitute_group": r["substitute_group"],
        "consignment_flag": r["consignment_flag"],
        "replaces_item_id": r["replaces_item_id"],
        "status": r["status"],
        "reviewing_officer_id": r["reviewing_officer_id"],
        "endorser_ids": list(r["endorser_ids"]),
        "endorsements_count": r["endorsements_count"],
        "rejection_reason": r["rejection_reason"],
        "created_item_id": r["created_item_id"],
    }
    out.update(_common(r))
    return out


def ser_consignment_count(c):
    out = {
        "supply_item_id": c["supply_item_id"],
        "counted_qty": c["counted_qty"],
        "system_qty_at_count": c["system_qty_at_count"],
        "variance_qty": c["variance_qty"],
        "variance_value_cents": c["variance_value_cents"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def ser_consignment_charge(c):
    out = {
        "case_id": c["case_id"],
        "usage_record_id": c["usage_record_id"],
        "supply_item_id": c["supply_item_id"],
        "qty_billed": c["qty_billed"],
        "unit_cost_cents": c["unit_cost_cents"],
        "amount_cents": c["amount_cents"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out
