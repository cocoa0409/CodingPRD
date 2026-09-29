"""The wall-to-wall physical inventory: blackout geometry, passes, waterfall (PRD 3.9)."""

from flask import Blueprint

import calc
from db import clock_now_iso, db, new_id
from errors import ApiError
from middleware import (acting_role, acting_user, require_read, require_roles,
                        scope_counter_firm)
from response import created, ok, ok_list, paginate, read_pagination
from validate import (S, body_json, filter_bool, filter_int, filter_enum, filter_str,
                      lookup, parse_body)

bp = Blueprint("physical", __name__)
PREFIX = "/inventory-integrity"

PI_STATUSES = ("PLANNED", "COUNTING", "FIRST_PASS_COMPLETE", "RECONCILING",
               "CERTIFIED", "ABANDONED")

NOTE_SPECS = [S("note", "str", required=False, max_len=2000)]

PI_SPECS = [
    S("scheduled_start_date", "date"),
    S("scheduled_end_date", "date"),
    S("recount_threshold_bps", "int", required=False, default=150, min=1, max=10000),
]


def _bad_state(message):
    raise ApiError("ERR_PHYSICAL_INVENTORY_INVALID_STATE", message)


def _counter_scope(inventory):
    """A ThirdPartyCounter may only act on its own firm's inventory."""
    if acting_role() == "ThirdPartyCounter":
        scope_counter_firm(inventory["counter_firm_id"])


@bp.post(PREFIX + "/physical-inventories")
def create_physical_inventory():
    require_roles("ShrinkController", "SystemAdmin")
    body = body_json()
    store = lookup("stores", body.get("store_id"))
    firm = lookup("counter_firms", body.get("counter_firm_id"))
    data = parse_body(body, PI_SPECS)
    start = data["scheduled_start_date"]
    end = data["scheduled_end_date"]
    # Rejection tier 8 (business constraint) precedes tier 10 (temporal).
    if calc.blackout_conflict(store["id"], start, end) is not None:
        raise ApiError("ERR_PHYSICAL_INVENTORY_BLACKOUT_CONFLICT",
                       "the padded blackout interval of another physical inventory collides")
    if end < start:
        raise ApiError("ERR_INVALID_PERIOD_RANGE",
                       "scheduled_end_date must be on or after scheduled_start_date")
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "store_id": store["id"],
        "counter_firm_id": firm["id"],
        "scheduled_start_date": start.isoformat(),
        "scheduled_end_date": end.isoformat(),
        "recount_threshold_bps": data["recount_threshold_bps"],
        "status": "PLANNED",
        "recount_round": 0,
        "line_count": 0,
        "book_value_cents": 0,
        "counted_value_cents": 0,
        "net_variance_cents": 0,
        "net_variance_bps": 0,
        "certified_at": None,
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.physical_inventories[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/physical-inventories/<physical_inventory_id>")
def get_physical_inventory(physical_inventory_id):
    require_read()
    return ok(lookup("physical_inventories", physical_inventory_id))


@bp.get(PREFIX + "/physical-inventories")
def list_physical_inventories():
    require_read()
    status = filter_enum("status", PI_STATUSES)
    predicates = []
    for param in ("store_id", "counter_firm_id"):
        value = filter_str(param)
        if value is not None:
            predicates.append((param, value))
    if status is not None:
        predicates.append(("status", status))
    matched = [r for r in db.physical_inventories.values()
               if all(r.get(key) == value for key, value in predicates)]
    limit, offset = read_pagination()
    page, total = paginate(calc.newest_first(matched), limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post(PREFIX + "/physical-inventories/<physical_inventory_id>/start")
def start_physical_inventory(physical_inventory_id):
    require_roles("ThirdPartyCounter", "ShrinkController")
    inventory = lookup("physical_inventories", physical_inventory_id)
    _counter_scope(inventory)
    parse_body(body_json(), [])
    if inventory["status"] != "PLANNED":
        _bad_state("only a PLANNED physical inventory may be started")
    inventory["status"] = "COUNTING"
    calc.touch(inventory)
    return ok(inventory)


# --------------------------------------------------------------------------
# lines: supersede geometry and the per-pass capacity cap
# --------------------------------------------------------------------------

def _pass_lines(inventory_id, pass_round, only_live=True):
    out = []
    for line in calc.rows("physical_inventory_lines"):
        if line["physical_inventory_id"] != inventory_id:
            continue
        if line["pass_round"] != pass_round:
            continue
        if only_live and line["superseded"]:
            continue
        out.append(line)
    return out


def _recount_line_count(inventory):
    inventory["line_count"] = len(_pass_lines(inventory["id"], inventory["recount_round"]))


LINE_SPECS = [
    S("counted_units", "int", min=0),
    S("expected_physical_inventory_version", "int"),
]


@bp.post(PREFIX + "/physical-inventories/<physical_inventory_id>/lines")
def create_physical_inventory_line(physical_inventory_id):
    require_roles("ThirdPartyCounter", "ShrinkController")
    inventory = lookup("physical_inventories", physical_inventory_id)
    _counter_scope(inventory)
    body = body_json()
    item = lookup("items", body.get("item_id"))
    data = parse_body(body, LINE_SPECS)
    if data["expected_physical_inventory_version"] != inventory["version"]:
        raise ApiError("ERR_STALE_PHYSICAL_INVENTORY_VERSION",
                       "expected_physical_inventory_version does not match the stored version")
    if inventory["status"] != "COUNTING":
        _bad_state("lines may only be submitted against a COUNTING physical inventory")
    position = calc.position_for(inventory["store_id"], item["id"])
    if position is None:
        raise ApiError("ERR_ITEM_NOT_STOCKED_AT_STORE",
                       "no stock position exists for this store and SKU")
    firm = db.counter_firms[inventory["counter_firm_id"]]
    live = _pass_lines(inventory["id"], inventory["recount_round"])
    superseding = [line for line in live if line["item_id"] == item["id"]]
    # A superseding line replaces rather than adds, so it consumes no new capacity.
    projected = len(live) + (0 if superseding else 1)
    if projected > firm["max_lines_per_pass"]:
        raise ApiError("ERR_MAX_LINES_PER_PASS_EXCEEDED",
                       "the counting firm's max_lines_per_pass would be exceeded")

    book_units = position["on_hand_units"]
    book_value = book_units * item["unit_cost_cents"]
    variance_units = data["counted_units"] - book_units
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "physical_inventory_id": inventory["id"],
        "item_id": item["id"],
        "counted_units": data["counted_units"],
        "book_units_snapshot": book_units,
        "book_value_snapshot_cents": book_value,
        # Pure book cost: the category's landed-cost uplift is NOT applied here.
        "variance_units": variance_units,
        "variance_value_cents": variance_units * item["unit_cost_cents"],
        "pass_round": inventory["recount_round"],
        "superseded": False,
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    for earlier in superseding:
        earlier["superseded"] = True
        calc.touch(earlier)
    db.physical_inventory_lines[record["id"]] = record
    _recount_line_count(inventory)
    calc.touch(inventory)
    return created(record)


@bp.get(PREFIX + "/physical-inventory-lines/<physical_inventory_line_id>")
def get_physical_inventory_line(physical_inventory_line_id):
    require_read()
    return ok(lookup("physical_inventory_lines", physical_inventory_line_id))


@bp.get(PREFIX + "/physical-inventory-lines")
def list_physical_inventory_lines():
    require_read()
    predicates = []
    for param in ("physical_inventory_id", "item_id"):
        value = filter_str(param)
        if value is not None:
            predicates.append((param, value))
    pass_round = filter_int("pass_round")
    if pass_round is not None:
        predicates.append(("pass_round", pass_round))
    superseded = filter_bool("superseded")
    if superseded is not None:
        predicates.append(("superseded", superseded))
    matched = [r for r in db.physical_inventory_lines.values()
               if all(r.get(key) == value for key, value in predicates)]
    limit, offset = read_pagination()
    page, total = paginate(calc.newest_first(matched), limit, offset)
    return ok_list(page, limit, offset, total)


# --------------------------------------------------------------------------
# pass closure, recount, reconciliation and certification
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/physical-inventories/<physical_inventory_id>/complete-pass")
def complete_pass(physical_inventory_id):
    require_roles("ThirdPartyCounter", "ShrinkController")
    inventory = lookup("physical_inventories", physical_inventory_id)
    _counter_scope(inventory)
    parse_body(body_json(), [])
    if inventory["status"] != "COUNTING":
        _bad_state("only a COUNTING physical inventory may complete a pass")
    lines = _pass_lines(inventory["id"], inventory["recount_round"])
    if not lines:
        raise ApiError("ERR_NO_COUNT_LINES", "the current pass carries no lines")
    book_value = 0
    counted_value = 0
    for line in lines:
        item = db.items[line["item_id"]]
        book_value += line["book_value_snapshot_cents"]
        counted_value += line["counted_units"] * item["unit_cost_cents"]
    inventory["book_value_cents"] = book_value
    inventory["counted_value_cents"] = counted_value
    inventory["net_variance_cents"] = counted_value - book_value
    inventory["net_variance_bps"] = calc.net_variance_bps(inventory["net_variance_cents"],
                                                          book_value)
    inventory["line_count"] = len(lines)
    inventory["status"] = "FIRST_PASS_COMPLETE"
    calc.touch(inventory)
    return ok(inventory)


@bp.post(PREFIX + "/physical-inventories/<physical_inventory_id>/order-recount")
def order_recount(physical_inventory_id):
    require_roles("ShrinkController", "InventorySupervisor")
    inventory = lookup("physical_inventories", physical_inventory_id)
    parse_body(body_json(), NOTE_SPECS)
    if inventory["status"] != "FIRST_PASS_COMPLETE":
        _bad_state("only a FIRST_PASS_COMPLETE physical inventory may be re-counted")
    if inventory["recount_round"] >= calc.MAX_RECOUNT_ROUNDS:
        raise ApiError("ERR_REWORK_LIMIT_REACHED",
                       "the physical inventory has already used its single recount")
    inventory["recount_round"] += 1
    # Prior lines stay on file under their own pass_round and stop aggregating.
    inventory["line_count"] = 0
    inventory["status"] = "COUNTING"
    calc.touch(inventory)
    return ok(inventory)


def _bump_period(period):
    """Re-derive the period's buckets and bump its version exactly once."""
    base_version = period["version"]
    calc.recompute_period(period)
    period["version"] = base_version
    calc.touch(period)


@bp.post(PREFIX + "/physical-inventories/<physical_inventory_id>/reconcile")
def reconcile_physical_inventory(physical_inventory_id):
    require_roles("ShrinkController")
    inventory = lookup("physical_inventories", physical_inventory_id)
    parse_body(body_json(), [])
    if inventory["status"] != "FIRST_PASS_COMPLETE":
        _bad_state("only a FIRST_PASS_COMPLETE physical inventory may be reconciled")
    # Guard one: inside the threshold, or already re-counted. The boundary demands
    # a recount, so the comparison is >= and not >.
    if (inventory["net_variance_bps"] >= inventory["recount_threshold_bps"]
            and inventory["recount_round"] < 1):
        raise ApiError("ERR_RECOUNT_REQUIRED",
                       "net_variance_bps is at or above recount_threshold_bps")
    # Guard two: a physical reconciliation writes buckets, so it needs a fully OPEN period.
    period = calc.covering_period(inventory["store_id"],
                                  calc._as_date(inventory["scheduled_end_date"]),
                                  ("OPEN",))
    if period is None:
        raise ApiError("ERR_NO_COVERING_SHRINK_PERIOD",
                       "no OPEN shrink period covers scheduled_end_date")

    # First the book moves: one posted PHYSICAL_RECONCILIATION adjustment per
    # varying line, walked in ascending line-creation order.
    touched = []
    for line in _pass_lines(inventory["id"], inventory["recount_round"]):
        if line["variance_units"] == 0:
            continue
        position = calc.position_for(inventory["store_id"], line["item_id"])
        if position is None:
            continue
        adjustment = calc.mint_adjustment(position, line["variance_units"],
                                          "PHYSICAL_RECONCILIATION", None,
                                          acting_user(), exempt=True)
        calc.post_adjustment(adjustment, position, settle_store=False)
        if position["id"] not in touched:
            touched.append(position["id"])
    calc.settle(touched)

    # Then the shrink buckets: the unexplained pool poured through floored caps.
    abs_net = abs(inventory["net_variance_cents"])
    explained = period["final_total_shrink_cents"]
    allocation = calc.reconciliation_waterfall(abs_net, explained)
    waterfall = period.get("_waterfall") or calc.empty_waterfall()
    for key, amount in allocation.items():
        waterfall[key] = waterfall.get(key, 0) + amount
    period["_waterfall"] = waterfall
    _bump_period(period)

    inventory["status"] = "RECONCILING"
    calc.touch(inventory)
    return ok(inventory)


@bp.post(PREFIX + "/physical-inventories/<physical_inventory_id>/certify")
def certify_physical_inventory(physical_inventory_id):
    require_roles("ShrinkController")
    inventory = lookup("physical_inventories", physical_inventory_id)
    parse_body(body_json(), [])
    if inventory["status"] != "RECONCILING":
        _bad_state("only a RECONCILING physical inventory may be certified")
    still_open = calc.covering_period(inventory["store_id"],
                                     calc._as_date(inventory["scheduled_end_date"]),
                                     ("OPEN",))
    if still_open is not None:
        raise ApiError("ERR_SHRINK_PERIOD_STILL_OPEN",
                       "the covering shrink period is still OPEN")
    inventory["status"] = "CERTIFIED"
    inventory["certified_at"] = clock_now_iso()
    calc.touch(inventory)
    return ok(inventory)


@bp.post(PREFIX + "/physical-inventories/<physical_inventory_id>/abandon")
def abandon_physical_inventory(physical_inventory_id):
    require_roles("ShrinkController", "SystemAdmin")
    inventory = lookup("physical_inventories", physical_inventory_id)
    parse_body(body_json(), NOTE_SPECS)
    if inventory["status"] != "PLANNED":
        _bad_state("only a PLANNED physical inventory may be abandoned")
    inventory["status"] = "ABANDONED"
    calc.touch(inventory)
    return ok(inventory)
