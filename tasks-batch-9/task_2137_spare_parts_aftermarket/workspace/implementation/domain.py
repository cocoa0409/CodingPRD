"""Shared domain services: stock arithmetic, pricing cascades, ledger, lookups."""
from decimal import Decimal

import calc
import store
from errors import ApiError


# ------------------------------------------------------------- lookups -----
def get_part(part_id):
    rec = store.parts.get(part_id)
    if rec is None:
        raise ApiError("ERR_PART_NOT_FOUND")
    return rec


def get_model(model_id):
    rec = store.equipment_models.get(model_id)
    if rec is None:
        raise ApiError("ERR_MODEL_NOT_FOUND")
    return rec


def get_installed_unit(unit_id):
    rec = store.installed_units.get(unit_id)
    if rec is None:
        raise ApiError("ERR_INSTALLED_UNIT_NOT_FOUND")
    return rec


def get_dealer(dealer_id):
    rec = store.dealers.get(dealer_id)
    if rec is None:
        raise ApiError("ERR_DEALER_NOT_FOUND")
    return rec


def get_work_order(wo_id):
    rec = store.work_orders.get(wo_id)
    if rec is None:
        raise ApiError("ERR_WORK_ORDER_NOT_FOUND")
    return rec


def get_part_line(line_id):
    rec = store.part_lines.get(line_id)
    if rec is None:
        raise ApiError("ERR_PART_LINE_NOT_FOUND")
    return rec


def get_campaign(campaign_id):
    rec = store.campaigns.get(campaign_id)
    if rec is None:
        raise ApiError("ERR_CAMPAIGN_NOT_FOUND")
    return rec


def get_allocation_request(req_id):
    rec = store.allocation_requests.get(req_id)
    if rec is None:
        raise ApiError("ERR_ALLOCATION_REQUEST_NOT_FOUND")
    return rec


def get_replenishment_order(order_id):
    rec = store.replenishment_orders.get(order_id)
    if rec is None:
        raise ApiError("ERR_REPLENISHMENT_ORDER_NOT_FOUND")
    return rec


def get_return(return_id):
    rec = store.return_authorizations.get(return_id)
    if rec is None:
        raise ApiError("ERR_RETURN_NOT_FOUND")
    return rec


def get_applicability(app_id):
    rec = store.part_applicabilities.get(app_id)
    if rec is None:
        raise ApiError("ERR_APPLICABILITY_NOT_FOUND")
    return rec


def unique_or_400(collection, field, value):
    for rec in collection.values():
        if rec.get(field) == value:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be unique." % field)


# --------------------------------------------------- stock position math ---
def available_units(part):
    return part["on_hand_units"] - part["allocated_units"]


def replenishment_status(part):
    for order in store.replenishment_orders.values():
        if order["part_id"] != part["id"]:
            continue
        if order["approval_status"] != "REJECTED" and order["logistics_status"] != "RECEIVED":
            return "ON_ORDER"
    if part["reorder_point_units"] > 0 and available_units(part) <= part["reorder_point_units"]:
        return "BELOW_REORDER_POINT"
    return "NORMAL"


def append_ledger(part, entry_type, delta_units, source_ref_type, source_ref_id):
    entry = store.new_record("StockLedgerEntry", {
        "part_id": part["id"],
        "entry_type": entry_type,
        "delta_units": delta_units,
        "balance_after_units": part["on_hand_units"] + part["quarantine_units"],
        "source_ref_type": source_ref_type,
        "source_ref_id": source_ref_id,
        "occurred_at": store.now(),
    }, common=False)
    store.ledger_entries[entry["id"]] = entry
    return entry


# ------------------------------------------------------------- pricing -----
def active_price_rule(criticality_class):
    for rule in store.price_rules.values():
        if rule["criticality_class"] == criticality_class and rule["rule_status"] == "ACTIVE":
            return rule
    return None


def price_for(part, qty, rule=None):
    rule = rule or active_price_rule(part["criticality_class"])
    if rule is None:
        return None
    return calc.price_uplift(part["unit_cost_cents"], part["lifecycle_state"], rule, qty)


def reprice_part(part):
    """Recompute the part's two catalogue price fields. No-op when no ACTIVE rule."""
    figures = price_for(part, 1)
    if figures is None:
        return False
    part["current_effective_uplift_pct"] = figures["effective_uplift_pct"]
    part["current_list_unit_price_cents"] = figures["list_unit_price_cents"]
    return True


OPEN_LINE_STATES = ("REQUESTED", "RESERVED", "BACKORDERED")


def lines_for_part(part_id, statuses=None):
    rows = [l for l in store.part_lines.values() if l["part_id"] == part_id]
    if statuses is not None:
        rows = [l for l in rows if l["line_status"] in statuses]
    return store.sort_created(rows)


def lines_for_work_order(work_order_id, statuses=None):
    rows = [l for l in store.part_lines.values() if l["work_order_id"] == work_order_id]
    if statuses is not None:
        rows = [l for l in rows if l["line_status"] in statuses]
    return store.sort_created(rows)


def requote_open_lines(part):
    """Re-quote every REQUESTED / RESERVED / BACKORDERED line on the part."""
    rule = active_price_rule(part["criticality_class"])
    if rule is None:
        return
    for line in lines_for_part(part["id"], OPEN_LINE_STATES):
        figures = calc.price_uplift(part["unit_cost_cents"], part["lifecycle_state"],
                                    rule, line["qty_requested"])
        line.update(figures)
        store.touch(line)


def set_lifecycle_state(part, new_state, requote=True):
    """A lifecycle hop: change state, re-price the part, re-quote its open lines."""
    part["lifecycle_state"] = new_state
    reprice_part(part)
    if requote:
        requote_open_lines(part)


# ------------------------------------------------------------- dealers -----
def recompute_credit_hold(dealer):
    dealer["credit_hold"] = dealer["outstanding_balance_cents"] > dealer["credit_limit_cents"]


def credit_dealer(dealer, final_credit_cents, restocking_fee_cents, loyalty_rebate_cents):
    dealer["outstanding_balance_cents"] -= final_credit_cents
    dealer["lifetime_restocking_fee_cents"] += restocking_fee_cents
    dealer["lifetime_rebate_cents"] += loyalty_rebate_cents
    recompute_credit_hold(dealer)
    store.touch(dealer)


# ------------------------------------------------------- applicability -----
def active_applicabilities(part_id, model_id=None):
    rows = [a for a in store.part_applicabilities.values()
            if a["part_id"] == part_id and a["applicability_status"] == "ACTIVE"]
    if model_id is not None:
        rows = [a for a in rows if a["model_id"] == model_id]
    return store.sort_created(rows)


def covers(row, build_revision):
    if row["effective_from_build_revision"] > build_revision:
        return False
    upper = row["effective_to_build_revision"]
    if upper is not None and build_revision > upper:
        return False
    return True


def covering_row(part_id, model_id, build_revision):
    for row in active_applicabilities(part_id, model_id):
        if covers(row, build_revision):
            return row
    return None


def covered_units(part_id, dealer_id=None):
    """ACTIVE installed units covered by an ACTIVE applicability row for the part.

    Returns a list of (unit, covering_row) pairs in unit creation order.
    """
    result = []
    units = store.sort_created([u for u in store.installed_units.values()
                                if u["status"] == "ACTIVE"])
    for unit in units:
        if dealer_id is not None and unit["dealer_id"] != dealer_id:
            continue
        row = covering_row(part_id, unit["model_id"], unit["build_revision"])
        if row is not None:
            result.append((unit, row))
    return result


# ------------------------------------------------------------ forecasts ----
def current_forecast(part_id, horizon_months):
    rows = [f for f in store.forecasts.values()
            if f["part_id"] == part_id
            and f["horizon_months"] == horizon_months
            and f["forecast_status"] == "CURRENT"]
    if not rows:
        return None
    return store.sort_created(rows)[-1]


def consumed_lines_in_window(part_id, lookback_days):
    """CONSUMED lines on CLOSED work orders whose closed_at is in ( now - lookback, now ]."""
    now = store.now()
    lower = now - store.days(lookback_days)
    result = []
    for line in store.part_lines.values():
        if line["part_id"] != part_id or line["line_status"] != "CONSUMED":
            continue
        wo = store.work_orders.get(line["work_order_id"])
        if wo is None or wo["status"] != "CLOSED" or wo["closed_at"] is None:
            continue
        if wo["closed_at"] > lower and wo["closed_at"] <= now:
            result.append((line, wo))
    return store.sort_created([l for l, _ in result]), result


# --------------------------------------------------- work order status -----
def sync_work_order_backorders(work_order):
    """A work order leaves PARTS_PENDING for OPEN when no BACKORDERED line remains."""
    if work_order["status"] != "PARTS_PENDING":
        return
    remaining = [l for l in store.part_lines.values()
                 if l["work_order_id"] == work_order["id"]
                 and l["line_status"] == "BACKORDERED"]
    if not remaining:
        work_order["status"] = "OPEN"
        store.touch(work_order)


def promote_backorders(part):
    """Single greedy pass over BACKORDERED lines on the part (calculation C8)."""
    candidates = [l for l in store.part_lines.values()
                  if l["part_id"] == part["id"] and l["line_status"] == "BACKORDERED"]

    def sort_key(line):
        wo = store.work_orders.get(line["work_order_id"])
        rank = calc.DOWNTIME_RANK.get(wo["downtime_priority"], 99) if wo else 99
        return (rank, line["qty_requested"], line["created_at"], line["_seq"])

    touched_orders = set()
    for line in sorted(candidates, key=sort_key):
        if available_units(part) >= line["qty_requested"]:
            line["line_status"] = "RESERVED"
            part["allocated_units"] += line["qty_requested"]
            store.touch(line)
            touched_orders.add(line["work_order_id"])

    for wo_id in touched_orders:
        wo = store.work_orders.get(wo_id)
        if wo is not None:
            sync_work_order_backorders(wo)


def auto_stock_replenishment(part):
    """Cascade hop 3 of consume: raise a STOCK order when the part fell below its
    reorder point and its stocking policy calls for automatic replenishment."""
    if part["stocking_policy"] not in ("STOCK_TO_MAX", "MIN_MAX"):
        return None
    if replenishment_status(part) != "BELOW_REORDER_POINT":
        return None
    qty = max(1, part["max_stock_units"] - available_units(part) - part["in_transit_units"])
    order = store.new_record("ReplenishmentOrder", {
        "part_id": part["id"],
        "order_type": "STOCK",
        "qty": qty,
        "unit_cost_cents": part["unit_cost_cents"],
        "freight_cost_cents": 0,
        "total_landed_cost_cents": part["unit_cost_cents"] * qty,
        "approval_status": "PENDING",
        "logistics_status": "NOT_STARTED",
        "auto_generated": True,
        "rejection_reason": None,
    })
    store.replenishment_orders[order["id"]] = order
    return order
