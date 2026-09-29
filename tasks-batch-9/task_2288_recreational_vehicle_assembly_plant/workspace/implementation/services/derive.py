"""Derived reads over the store. Nothing here mutates a row unless it says so."""
from decimal import Decimal

import constants as C
import db
from db import store
from services import calc


# ---------------------------------------------------------------------------
# small navigation helpers
# ---------------------------------------------------------------------------
def dealer_orders(dealer_id):
    return [o for o in store.unit_orders.values() if o["dealer_id"] == dealer_id]


def order_slots(order_id):
    return [s for s in store.production_slots.values() if s["unit_order_id"] == order_id]


def active_slot(order_id):
    """The order's slot in RESERVED or CONSUMED, if any."""
    rows = [s for s in order_slots(order_id) if s["status"] in ("RESERVED", "CONSUMED")]
    return db.ordered(rows)[-1] if rows else None


def reserved_slot(order_id):
    rows = [s for s in order_slots(order_id) if s["status"] == "RESERVED"]
    return db.ordered(rows)[-1] if rows else None


def build_for_order(order_id):
    rows = [b for b in store.unit_builds.values() if b["unit_order_id"] == order_id]
    return db.ordered(rows)[-1] if rows else None


def matched_chassis(order_id):
    for chassis in store.chassis_receipts.values():
        if chassis.get("matched_unit_order_id") == order_id and chassis["status"] in (
            "MATCHED",
            "INSTALLED",
        ):
            return chassis
    return None


def build_installations(build_id):
    return [i for i in store.component_installations.values() if i["unit_build_id"] == build_id]


def line_of_build(build):
    """The line of the slot the build consumed."""
    slot = active_slot(build["unit_order_id"])
    if slot is None:
        rows = order_slots(build["unit_order_id"])
        slot = db.ordered(rows)[-1] if rows else None
    if slot is None:
        return None
    return store.production_lines.get(slot["line_id"])


def selected_options(order):
    return [store.option_items[oid] for oid in order["selected_option_ids"] if oid in store.option_items]


def option_lines_current(order):
    return [
        (o["option_code"], o["category"], int(o["price_cents"])) for o in selected_options(order)
    ]


def option_lines_pinned(order):
    """FINAL_AT_SHIP reprices from the pinned price_cents."""
    lines = []
    for entry in order.get("locked_option_versions") or []:
        option = store.option_items.get(entry["option_id"])
        if option is None:
            continue
        lines.append((option["option_code"], option["category"], int(entry["price_cents"])))
    return lines


# ---------------------------------------------------------------------------
# UnitOrder derived
# ---------------------------------------------------------------------------
def order_age_days(order):
    if not order.get("funded_at"):
        return 0
    return db.whole_days_between(order["funded_at"], db.now())


def order_curtailment_due(order):
    if order["financing_status"] not in ("FLOOR_PLAN_FUNDED", "CURTAILED"):
        return 0
    if not order.get("funded_at"):
        return 0
    return calc.curtailment_due(
        int(order["financed_principal_cents"]),
        int(order["curtailment_paid_cents"]),
        order_age_days(order),
    )


def dealer_is_delinquent(dealer_id):
    for order in dealer_orders(dealer_id):
        if order["financing_status"] == "CURTAILED" and order_curtailment_due(order) > 0:
            return True
    return False


# ---------------------------------------------------------------------------
# Dealer derived
# ---------------------------------------------------------------------------
def financed_exposure(dealer_id):
    total = 0
    for order in dealer_orders(dealer_id):
        if order["financing_status"] in ("FLOOR_PLAN_FUNDED", "CURTAILED"):
            total += int(order["financed_principal_cents"]) - int(order["curtailment_paid_cents"])
    return total


def goodwill_used(dealer_id):
    total = 0
    for claim in store.warranty_claims.values():
        if claim["dealer_id"] == dealer_id and claim["status"] in ("APPROVED", "PAID"):
            total += int(claim["goodwill_authorized_cents"])
    return total


def dealer_slots(dealer_id, statuses=("RESERVED", "CONSUMED")):
    order_ids = {o["id"] for o in dealer_orders(dealer_id)}
    return [
        s
        for s in store.production_slots.values()
        if s["unit_order_id"] in order_ids and s["status"] in statuses
    ]


def month_key(instant):
    return (instant.year, instant.month)


def allocation_hours_consumed(dealer_id, month=None, exclude_slot_id=None):
    """Committed hours held by a dealer's slots.

    The monthly ceiling of §3.3 measures one calendar month — the month of the
    requested `slot_date` — so callers on that path pass ``month``. The dealer's
    reported position mirrors `allocation_slots_reserved`, which §3.3 defines as
    the plain count of that dealer's `RESERVED` or `CONSUMED` slots, so a read
    with no month sums every such slot.
    """
    total = Decimal("0")
    for slot in dealer_slots(dealer_id):
        if exclude_slot_id is not None and slot["id"] == exclude_slot_id:
            continue
        if month is not None and month_key(slot["slot_date"]) != month:
            continue
        total += calc.dec(slot["station_hours_committed"])
    return calc.rhu2(total)


def dealer_entitlement(dealer):
    return calc.entitlement_hours(list(store.production_lines.values()), dealer["allocation_share_bp"])


def dealer_position(dealer):
    exposure = financed_exposure(dealer["id"])
    bp = calc.credit_utilization_bp(exposure, int(dealer["floor_plan_credit_limit_cents"]))
    entitled = dealer_entitlement(dealer)
    return {
        "financed_exposure_cents": exposure,
        "credit_utilization_bp": bp,
        "credit_status": calc.credit_status_for(bp),
        "goodwill_used_cents": goodwill_used(dealer["id"]),
        "entitlement_hours": entitled,
        "allocation_hours_consumed": allocation_hours_consumed(dealer["id"]),
        "allocation_slots_reserved": len(dealer_slots(dealer["id"])),
    }


def dealer_credit_status(dealer):
    exposure = financed_exposure(dealer["id"])
    bp = calc.credit_utilization_bp(exposure, int(dealer["floor_plan_credit_limit_cents"]))
    return calc.credit_status_for(bp)


def dealer_goodwill_remaining(dealer):
    return int(dealer["goodwill_budget_cents"]) - goodwill_used(dealer["id"])


# ---------------------------------------------------------------------------
# Supplier derived
# ---------------------------------------------------------------------------
def supplier_events(supplier_id):
    events = []
    for campaign in store.recall_campaigns.values():
        if campaign["supplier_id"] != supplier_id:
            continue
        if campaign["status"] not in ("OPEN", "CLOSED"):
            continue
        if not campaign.get("opened_at"):
            continue
        events.append((campaign["opened_at"], C.RECALL_PENALTY_WEIGHT[campaign["severity"]]))
    for claim in store.warranty_claims.values():
        if claim["status"] not in ("APPROVED", "PAID"):
            continue
        if int(claim["supplier_chargeback_cents"]) <= 0:
            continue
        lot = store.component_lots.get(claim.get("component_lot_id"))
        if lot is None or lot["supplier_id"] != supplier_id:
            continue
        events.append((claim["created_at"], C.CHARGEBACK_CLAIM_PENALTY_WEIGHT))
    return events


def supplier_scores(supplier_id):
    return calc.supplier_scores(supplier_events(supplier_id), db.now())


def rescore_supplier(supplier):
    """Recompute and persist the ROLLING_90D score and the derived status."""
    rolling, _lifetime = supplier_scores(supplier["id"])
    status = calc.supplier_status_for(rolling)
    changed = supplier["quality_score"] != rolling or supplier["supplier_status"] != status
    supplier["quality_score"] = rolling
    supplier["supplier_status"] = status
    return changed


# ---------------------------------------------------------------------------
# chassis_match_selection
# ---------------------------------------------------------------------------
def eligible_chassis(order, floor_plan):
    needed_gvwr = int(order["config_weight_lbs"]) + C.CHASSIS_GVWR_MARGIN_LBS
    candidates = []
    for chassis in store.chassis_receipts.values():
        if chassis["status"] != "RECEIVED":
            continue
        if chassis.get("matched_unit_order_id"):
            continue
        if chassis["chassis_class"] != floor_plan["chassis_class"]:
            continue
        if int(chassis["wheelbase_in"]) != int(floor_plan["required_wheelbase_in"]):
            continue
        if int(chassis["gvwr_lbs"]) < needed_gvwr:
            continue
        supplier = store.suppliers.get(chassis["supplier_id"])
        if supplier is None or supplier["supplier_status"] not in ("ACTIVE", "PROBATION"):
            continue
        candidates.append(chassis)
    return candidates


def pick_chassis(order, floor_plan):
    candidates = eligible_chassis(order, floor_plan)
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["received_at"], int(c["gvwr_lbs"]), c["created_at"], c["_seq"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# line_day_slot_capacity
# ---------------------------------------------------------------------------
def day_occupancy(line_id, slot_date, exclude_slot_id=None):
    hours = Decimal("0")
    units = 0
    for slot in store.production_slots.values():
        if slot["line_id"] != line_id:
            continue
        if slot["slot_date"] != slot_date:
            continue
        if slot["status"] not in ("RESERVED", "CONSUMED"):
            continue
        if exclude_slot_id is not None and slot["id"] == exclude_slot_id:
            continue
        hours += calc.dec(slot["station_hours_committed"])
        units += 1
    return calc.rhu2(hours), units


# ---------------------------------------------------------------------------
# booth_window_conflict
# ---------------------------------------------------------------------------
def booth_conflict_count(booth, window_start, window_end):
    from datetime import timedelta

    buffer = timedelta(minutes=int(booth["turnaround_minutes"]))
    request_effective_end = window_end + buffer
    count = 0
    for inspection in store.quality_inspections.values():
        if inspection.get("test_booth_id") != booth["id"]:
            continue
        if inspection["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if not inspection.get("window_start") or not inspection.get("window_end"):
            continue
        other_effective_end = inspection["window_end"] + buffer
        if window_start < other_effective_end and inspection["window_start"] < request_effective_end:
            count += 1
    return count


# ---------------------------------------------------------------------------
# quality inspection helpers
# ---------------------------------------------------------------------------
def latest_completed_water_test(build_id):
    rows = [
        i
        for i in store.quality_inspections.values()
        if i["unit_build_id"] == build_id
        and i["inspection_type"] == "WATER_TEST"
        and i["status"] == "COMPLETED"
    ]
    if not rows:
        return None
    return db.ordered(rows)[-1]
