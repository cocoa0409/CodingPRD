"""Derived quantities, health derivation, propagation and serializers.

Every field the scaffold marks `source: computed` is derived on read from the
stored rows, which keeps the ledger and network invariants exact by
construction.
"""
from decimal import Decimal

import store as db

GRADE_RANK = {"A": 1, "B": 2, "C": 3, "D": 4}
ITEM_CLASSES = ("APPAREL_TOP", "APPAREL_BOTTOM", "FOOTWEAR", "ACCESSORY")
SPECIFICITY_RANK = {"PROGRAM": 1, "CLUSTER": 2, "STORE": 3}


def by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def ts(value):
    """Datetimes are stored as aware datetimes and rendered on the way out."""
    return db.iso(value)


def num(value):
    """Serialise a monetary Decimal as a JSON number."""
    if value is None:
        return None
    return float(Decimal(value).quantize(Decimal("0.01")))


# --- collection helpers -------------------------------------------------------
def stores_of_program(program_id):
    return [s for s in db.stores.values() if s["program_id"] == program_id]


def items_of_program(program_id):
    return [i for i in db.items.values() if i["program_id"] == program_id]


def receipts_of_program(program_id):
    return [r for r in db.receipts.values() if r["program_id"] == program_id]


def positions_of_item(item_id):
    return [p for p in db.positions.values() if p["item_id"] == item_id]


def positions_of_store(store_id):
    return [p for p in db.positions.values() if p["store_id"] == store_id]


def position_for(store_id, item_id):
    for p in db.positions.values():
        if p["store_id"] == store_id and p["item_id"] == item_id:
            return p
    return None


def lines_of_run(run_id):
    return [l for l in db.lines.values() if l["run_id"] == run_id]


def runs_of_receipt(receipt_id):
    return [r for r in db.runs.values() if r["receipt_id"] == receipt_id]


def line_item_id(line):
    run = db.runs[line["run_id"]]
    receipt = db.receipts[run["receipt_id"]]
    return receipt["item_id"]


def line_program_id(line):
    run = db.runs[line["run_id"]]
    return db.receipts[run["receipt_id"]]["program_id"]


def program_of_item(item):
    return db.programs.get(item["program_id"])


def profile_of_item(item):
    return db.size_profiles.get(item["size_profile_id"])


# --- position derived quantities ----------------------------------------------
def in_transit_units(position):
    total = 0
    for line in db.lines.values():
        if line["store_id"] != position["store_id"]:
            continue
        if line["fulfillment_status"] != "SHIPPED":
            continue
        if line_item_id(line) != position["item_id"]:
            continue
        total += line["units_allocated"]
    for t in db.transfers.values():
        if (
            t["to_store_id"] == position["store_id"]
            and t["item_id"] == position["item_id"]
            and t["status"] == "DISPATCHED"
        ):
            total += t["units"]
    return total


def reserved_out_units(position):
    total = 0
    for t in db.transfers.values():
        if (
            t["from_store_id"] == position["store_id"]
            and t["item_id"] == position["item_id"]
            and t["status"] in ("APPROVED", "DISPATCHED")
        ):
            total += t["units"]
    return total


def available_units(position):
    return position["on_hand_units"] - reserved_out_units(position)


def size_units(size_array, size_code):
    for entry in size_array:
        if entry["size_code"] == size_code:
            return entry["units"]
    return 0


def core_sizes(item):
    profile = profile_of_item(item)
    if not profile:
        return []
    threshold = profile["core_size_min_share_bp"]
    return [e for e in profile["size_curve"] if e["share_bp"] >= threshold]


def broken_size_count(position):
    item = db.items[position["item_id"]]
    count = 0
    for entry in core_sizes(item):
        if size_units(position["size_on_hand"], entry["size_code"]) == 0:
            count += 1
    return count


def stock_status(position):
    available = available_units(position)
    if available == 0:
        return "STOCKOUT"
    if available < position["min_units"]:
        return "LOW"
    if available <= position["max_units"]:
        return "IN_STOCK"
    return "OVERSTOCK"


def assortment_status(position):
    store = db.stores.get(position["store_id"])
    if (store and store["status"] == "CLOSED") or position["consolidated_out"]:
        return "EXITED"
    broken = broken_size_count(position)
    if broken == 0:
        return "COMPLETE"
    if broken == 1:
        return "SIZE_OUT_RISK"
    return "BROKEN"


def item_broken_counts(item):
    broken = 0
    size_out = 0
    for position in positions_of_item(item["id"]):
        status = assortment_status(position)
        if status == "BROKEN":
            broken += 1
        elif status == "SIZE_OUT_RISK":
            size_out += 1
    return broken, size_out


def rederive_item_lifecycle(item):
    """Pinned order from PRD 3.3 / scaffold 1.2."""
    broken, size_out = item_broken_counts(item)
    state = item["lifecycle_state"]
    if state == "MARKDOWN":
        return
    if state == "CONSOLIDATION_PENDING":
        if broken == 0:
            item["lifecycle_state"] = "ACTIVE"
        return
    if broken >= 1:
        item["lifecycle_state"] = "BROKEN"
    elif size_out >= 1:
        item["lifecycle_state"] = "SIZE_OUT_WATCH"
    else:
        item["lifecycle_state"] = "ACTIVE"


def supersede_actions(position):
    """PRD 3.3: a position back at COMPLETE supersedes its PENDING actions."""
    for action in db.actions.values():
        if (
            action["status"] == "PENDING"
            and action["item_id"] == position["item_id"]
            and action["store_id"] == position["store_id"]
        ):
            action["status"] = "SUPERSEDED"
            db.touch(action)


def propagate_position(position):
    """Re-derive health for one position and propagate to its SKU."""
    if assortment_status(position) == "COMPLETE":
        supersede_actions(position)
    item = db.items.get(position["item_id"])
    if item:
        rederive_item_lifecycle(item)


# --- fixture plans ------------------------------------------------------------
def in_effect_plan(store_id, item_class):
    clock = db.now()
    for plan in by_created(list(db.fixture_plans.values())):
        if plan["store_id"] != store_id or plan["item_class"] != item_class:
            continue
        if plan["effective_from"] <= clock and (
            plan["effective_to"] is None or clock < plan["effective_to"]
        ):
            return plan
    return None


def headroom(position, plan):
    if plan is None:
        return 0
    return max(
        0,
        plan["capacity_units"] - available_units(position) - in_transit_units(position),
    )


# --- ledgers ------------------------------------------------------------------
def receipt_units_committed(receipt):
    total = 0
    for line in db.lines.values():
        run = db.runs[line["run_id"]]
        if run["receipt_id"] != receipt["id"]:
            continue
        if run["status"] != "COMMITTED":
            continue
        if line["fulfillment_status"] not in ("PENDING", "SHIPPED", "RECEIVED"):
            continue
        total += line["units_allocated"]
    return total


def receipt_units_unallocated(receipt):
    return receipt["units_received"] - receipt_units_committed(receipt)


def program_total_received(program):
    total = 0
    for receipt in receipts_of_program(program["id"]):
        if receipt["status"] in ("STAGED", "ALLOCATING", "ALLOCATED", "CLOSED"):
            total += receipt["units_received"]
    return total


def program_total_committed(program):
    total = 0
    for receipt in receipts_of_program(program["id"]):
        total += receipt_units_committed(receipt)
    return total


def run_units_proposed(run):
    return sum(l["units_proposed"] for l in lines_of_run(run["id"]))


def run_units_committed(run):
    if run["status"] != "COMMITTED":
        return 0
    return sum(l["units_allocated"] for l in lines_of_run(run["id"]))


# --- serializers --------------------------------------------------------------
def common(record, versioned=True):
    out = {"id": record["id"], "created_at": ts(record["created_at"])}
    if versioned:
        out["updated_at"] = ts(record["updated_at"])
        out["version"] = record["version"]
    return out


def program_out(program):
    received = program_total_received(program)
    committed = program_total_committed(program)
    out = common(program)
    out.update(
        {
            "name": program["name"],
            "season_code": program["season_code"],
            "banner_code": program["banner_code"],
            "status": program["status"],
            "transfer_min_ratio_bp": program["transfer_min_ratio_bp"],
            "scorecard_basis": program["scorecard_basis"],
            "total_units_received": received,
            "total_units_committed": committed,
            "open_reserve_units": received - committed,
            "locked_at": ts(program["locked_at"]),
            "lock_reason": program["lock_reason"],
        }
    )
    return out


def store_out(s):
    out = common(s)
    out.update(
        {
            "program_id": s["program_id"],
            "store_code": s["store_code"],
            "grade": s["grade"],
            "grade_index_bp": s["grade_index_bp"],
            "cluster_code": s["cluster_code"],
            "status": s["status"],
            "freight_flat_usd": num(s["freight_flat_usd"]),
            "historical_sell_through_bp": s["historical_sell_through_bp"],
        }
    )
    return out


def plan_out(p):
    out = common(p)
    out.update(
        {
            "store_id": p["store_id"],
            "item_class": p["item_class"],
            "effective_from": ts(p["effective_from"]),
            "effective_to": ts(p["effective_to"]),
            "fixture_count": p["fixture_count"],
            "facings_per_fixture": p["facings_per_fixture"],
            "units_per_facing": p["units_per_facing"],
            "capacity_units": p["fixture_count"]
            * p["facings_per_fixture"]
            * p["units_per_facing"],
            "presentation_min_units": p["presentation_min_units"],
        }
    )
    return out


def profile_out(sp):
    out = common(sp, versioned=False)
    curve = [
        {"size_code": e["size_code"], "share_bp": e["share_bp"]}
        for e in sp["size_curve"]
    ]
    out.update(
        {
            "program_id": sp["program_id"],
            "profile_code": sp["profile_code"],
            "item_class": sp["item_class"],
            "size_curve": curve,
            "core_size_min_share_bp": sp["core_size_min_share_bp"],
            "size_count": len(curve),
            "core_size_count": len(
                [e for e in curve if e["share_bp"] >= sp["core_size_min_share_bp"]]
            ),
        }
    )
    return out


def item_out(item):
    broken, size_out = item_broken_counts(item)
    out = common(item)
    out.update(
        {
            "program_id": item["program_id"],
            "sku_code": item["sku_code"],
            "style_code": item["style_code"],
            "item_class": item["item_class"],
            "item_type": item["item_type"],
            "size_profile_id": item["size_profile_id"],
            "unit_cost_usd": num(item["unit_cost_usd"]),
            "retail_price_usd": num(item["retail_price_usd"]),
            "replenishment_model_override": item["replenishment_model_override"],
            "replenishment_model": item["replenishment_model"],
            "lifecycle_state": item["lifecycle_state"],
            "broken_store_count": broken,
            "size_out_store_count": size_out,
        }
    )
    return out


def position_out(p):
    out = common(p)
    out.update(
        {
            "store_id": p["store_id"],
            "item_id": p["item_id"],
            "on_hand_units": p["on_hand_units"],
            "size_on_hand": [
                {"size_code": e["size_code"], "units": e["units"]}
                for e in p["size_on_hand"]
            ],
            "on_order_units": p["on_order_units"],
            "in_transit_units": in_transit_units(p),
            "reserved_out_units": reserved_out_units(p),
            "available_units": available_units(p),
            "min_units": p["min_units"],
            "max_units": p["max_units"],
            "weekly_forecast_units": p["weekly_forecast_units"],
            "trailing_4wk_sales_units": p["trailing_4wk_sales_units"],
            "stock_status": stock_status(p),
            "assortment_status": assortment_status(p),
            "broken_size_count": broken_size_count(p),
            "consolidated_out": p["consolidated_out"],
        }
    )
    return out


def receipt_out(r):
    committed = receipt_units_committed(r)
    out = common(r)
    out.update(
        {
            "program_id": r["program_id"],
            "item_id": r["item_id"],
            "reference": r["reference"],
            "units_received": r["units_received"],
            "size_received": [
                {"size_code": e["size_code"], "units": e["units"]}
                for e in r["size_received"]
            ],
            "receipt_date": ts(r["receipt_date"]),
            "status": r["status"],
            "units_committed": committed,
            "units_unallocated": r["units_received"] - committed,
        }
    )
    return out


def run_out(run):
    out = common(run)
    out.update(
        {
            "receipt_id": run["receipt_id"],
            "method": run["method"],
            "need_basis": run["need_basis"],
            "status": run["status"],
            "supersedes_run_id": run["supersedes_run_id"],
            "proposed_by_user_id": run["proposed_by_user_id"],
            "committed_by_user_id": run["committed_by_user_id"],
            "units_proposed": run_units_proposed(run),
            "units_committed": run_units_committed(run),
            "unallocated_remainder_units": run["unallocated_remainder_units"],
            "eligible_store_count": run["eligible_store_count"],
        }
    )
    return out


def line_out(line):
    out = common(line)
    out.update(
        {
            "run_id": line["run_id"],
            "store_id": line["store_id"],
            "need_units": line["need_units"],
            "units_proposed": line["units_proposed"],
            "units_allocated": line["units_allocated"],
            "size_breakdown": [
                {"size_code": e["size_code"], "units": e["units"]}
                for e in line["size_breakdown"]
            ],
            "capacity_capped_units": line["capacity_capped_units"],
            "presentation_gap_units": line["presentation_gap_units"],
            "fulfillment_status": line["fulfillment_status"],
        }
    )
    return out


def promo_out(e):
    out = common(e)
    out.update(
        {
            "program_id": e["program_id"],
            "event_code": e["event_code"],
            "scope": e["scope"],
            "cluster_code": e["cluster_code"],
            "store_id": e["store_id"],
            "item_class": e["item_class"],
            "start_date": ts(e["start_date"]),
            "end_date": ts(e["end_date"]),
            "lift_factor_bp": e["lift_factor_bp"],
            "status": e["status"],
        }
    )
    return out


def transfer_out(t):
    out = common(t)
    out.update(
        {
            "program_id": t["program_id"],
            "from_store_id": t["from_store_id"],
            "to_store_id": t["to_store_id"],
            "item_id": t["item_id"],
            "units": t["units"],
            "source_reason": t["source_reason"],
            "size_split": [
                {"size_code": e["size_code"], "units": e["units"]}
                for e in t["size_split"]
            ],
            "freight_cost_usd": num(t["freight_cost_usd"]),
            "handling_fee_usd": num(t["handling_fee_usd"]),
            "landed_cost_usd": num(t["landed_cost_usd"]),
            "benefit_usd": num(t["benefit_usd"]),
            "benefit_ratio_bp": t["benefit_ratio_bp"],
            "status": t["status"],
            "expires_at": ts(t["expires_at"]),
            "proposed_by_user_id": t["proposed_by_user_id"],
            "approved_by_user_id": t["approved_by_user_id"],
            "reject_reason": t["reject_reason"],
            "supersedes_recommendation_id": t["supersedes_recommendation_id"],
            "assortment_action_id": t["assortment_action_id"],
        }
    )
    return out


def action_out(a):
    out = common(a)
    out.update(
        {
            "item_id": a["item_id"],
            "store_id": a["store_id"],
            "trigger_reason": a["trigger_reason"],
            "action_type": a["action_type"],
            "consolidation_target_store_id": a["consolidation_target_store_id"],
            "broken_size_count": a["broken_size_count"],
            "markdown_pct_bp": a["markdown_pct_bp"],
            "units_at_detection": a["units_at_detection"],
            "status": a["status"],
            "detected_at": ts(a["detected_at"]),
        }
    )
    return out


def snapshot_out(s):
    out = common(s, versioned=False)
    out.update(
        {
            "program_id": s["program_id"],
            "cluster_code": s["cluster_code"],
            "basis": s["basis"],
            "as_of_date": ts(s["as_of_date"]),
            "store_count": s["store_count"],
            "included_position_count": s["included_position_count"],
            "in_stock_pct_bp": s["in_stock_pct_bp"],
            "sell_through_pct_bp": s["sell_through_pct_bp"],
            "allocation_accuracy_bp": s["allocation_accuracy_bp"],
        }
    )
    return out
