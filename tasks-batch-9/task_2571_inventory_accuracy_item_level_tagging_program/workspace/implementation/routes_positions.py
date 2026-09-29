"""Stock positions, the integrity scan, and on-hand adjustments (PRD 3.2, 3.7)."""

from datetime import date
from decimal import Decimal

from flask import Blueprint

import calc
from db import clock_now_iso, clock_today, db, new_id
from errors import ApiError
from middleware import (acting_role, acting_user, require_read, require_roles,
                        segregation_check)
from response import created, ok, ok_list, paginate, read_pagination
from validate import (S, body_json, filter_enum, filter_str, lookup, parse_body)

bp = Blueprint("positions", __name__)
PREFIX = "/inventory-integrity"

PROMISING_STATES = ("PROMISABLE", "RESTRICTED", "BLOCKED")


def _list(collection, predicates):
    matched = [r for r in getattr(db, collection).values()
               if all(r.get(key) == value for key, value in predicates)]
    limit, offset = read_pagination()
    page, total = paginate(calc.newest_first(matched), limit, offset)
    return ok_list(page, limit, offset, total)


# --------------------------------------------------------------------------
# StockPosition
# --------------------------------------------------------------------------
POSITION_SPECS = [
    S("baseline_on_hand_units", "int", required=False, default=0, min=0),
    S("reserved_units", "int", required=False, default=0, min=0),
]


@bp.post(PREFIX + "/stock-positions")
def create_stock_position():
    require_roles("SystemAdmin", "InventoryAnalyst")
    body = body_json()
    store = lookup("stores", body.get("store_id"))
    item = lookup("items", body.get("item_id"))
    data = parse_body(body, POSITION_SPECS)
    if calc.position_for(store["id"], item["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_STOCK_POSITION",
                       "a stock position already exists for this store and item")
    category = db.categories[item["category_id"]]
    baseline = data["baseline_on_hand_units"]
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "store_id": store["id"],
        "item_id": item["id"],
        "baseline_on_hand_units": baseline,
        "on_hand_units": baseline,
        "reserved_units": data["reserved_units"],
        "phantom_units": 0,
        "book_value_cents": baseline * item["unit_cost_cents"],
        "last_counted_at": None,
        "last_count_system_units": 0,
        "last_count_book_value_cents": 0,
        "last_variance_units": 0,
        "last_variance_value_cents": 0,
        "unit_accuracy_pct": Decimal("100.00"),
        "value_accuracy_pct": Decimal("100.00"),
        "tag_integrity_hold": False,
        "negative_correction_count": 0,
        "promising_state": "PROMISABLE",
        "promising_reason": "",
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    state, reason = calc.position_promising_state(record, category)
    record["promising_state"] = state
    record["promising_reason"] = reason
    db.stock_positions[record["id"]] = record
    calc.derive_store(store["id"])
    return created(record)


@bp.get(PREFIX + "/stock-positions/<stock_position_id>")
def get_stock_position(stock_position_id):
    require_read()
    return ok(lookup("stock_positions", stock_position_id))


@bp.get(PREFIX + "/stock-positions")
def list_stock_positions():
    require_read()
    promising_state = filter_enum("promising_state", PROMISING_STATES)
    predicates = []
    for param in ("store_id", "item_id"):
        value = filter_str(param)
        if value is not None:
            predicates.append((param, value))
    if promising_state is not None:
        predicates.append(("promising_state", promising_state))
    return _list("stock_positions", predicates)


@bp.get(PREFIX + "/stock-positions/<stock_position_id>/accuracy")
def stock_position_accuracy(stock_position_id):
    require_read()
    position = lookup("stock_positions", stock_position_id)
    item = db.items[position["item_id"]]
    category = db.categories[item["category_id"]]
    unit_pct, value_pct = calc.stock_accuracy_pct(position)
    state, reason = calc.position_promising_state(position, category)
    return ok({
        "unit_accuracy_pct": unit_pct,
        "value_accuracy_pct": value_pct,
        "last_count_system_units": position["last_count_system_units"],
        "last_count_book_value_cents": position["last_count_book_value_cents"],
        "last_variance_units": position["last_variance_units"],
        "last_variance_value_cents": position["last_variance_value_cents"],
        "promising_state": state,
        "promising_reason": reason,
        "min_accuracy_pct": category["min_accuracy_pct"],
    })


# --------------------------------------------------------------------------
# integrity scan (PRD 3.7)
# --------------------------------------------------------------------------

def _date_of(iso_text):
    return date(int(iso_text[0:4]), int(iso_text[5:7]), int(iso_text[8:10]))


@bp.post(PREFIX + "/stock-positions/<stock_position_id>/integrity-scan")
def integrity_scan(stock_position_id):
    require_roles("InventoryAnalyst", "InventorySupervisor")
    position = lookup("stock_positions", stock_position_id)
    item = db.items[position["item_id"]]
    category = db.categories[item["category_id"]]

    corrections = 0
    negative_corrected_units = 0
    phantom_zeroed_units = 0
    auto_posted = []
    pending = []

    # --- rule one: negative on-hand ---
    if position["on_hand_units"] < 0:
        deficit = -position["on_hand_units"]
        auto = (abs(position["on_hand_units"]) <= calc.NEGATIVE_AUTO_CORRECT_MAX_UNITS
                and bool(category["auto_correct_negative"]))
        adjustment = calc.mint_adjustment(
            position, deficit, "NEGATIVE_CORRECTION", None, "system",
            exempt=auto, force_approval_state=None if auto else "PENDING")
        corrections += 1
        if auto:
            adjustment["posting_state"] = "POSTED"
            adjustment["posted_at"] = clock_now_iso()
            calc.touch(adjustment)
            position["negative_correction_count"] += 1
            negative_corrected_units = deficit
            auto_posted.append(adjustment["id"])
        else:
            pending.append(adjustment["id"])
            position["tag_integrity_hold"] = True

    # --- rule two: phantom inventory, evaluated on the post-rule-one on-hand ---
    on_hand = position["baseline_on_hand_units"] + calc.posted_delta_sum(position["id"])
    if (on_hand > 0
            and position["reserved_units"] == 0
            and position["last_counted_at"] is not None
            and on_hand <= calc.PHANTOM_MAX_AUTO_UNITS):
        elapsed = (clock_today() - _date_of(position["last_counted_at"])).days
        if elapsed >= calc.PHANTOM_STALE_DAYS:
            position["phantom_units"] = on_hand
            adjustment = calc.mint_adjustment(
                position, -on_hand, "PHANTOM_CLEAR", None, "system", exempt=True)
            adjustment["posting_state"] = "POSTED"
            adjustment["posted_at"] = clock_now_iso()
            adjustment["_phantom_restore"] = on_hand
            calc.touch(adjustment)
            position["phantom_units"] = 0
            corrections += 1
            phantom_zeroed_units = on_hand
            auto_posted.append(adjustment["id"])

    calc.derive_position(position, force=True)
    calc.derive_store(position["store_id"])

    return ok({
        "corrections_applied": corrections,
        "negative_corrected_units": negative_corrected_units,
        "phantom_zeroed_units": phantom_zeroed_units,
        "auto_posted_adjustment_ids": auto_posted,
        "pending_adjustment_ids": pending,
        "resulting_on_hand_units": position["on_hand_units"],
        "resulting_phantom_units": position["phantom_units"],
        "resulting_promising_state": position["promising_state"],
        "tag_integrity_hold": position["tag_integrity_hold"],
    })


# --------------------------------------------------------------------------
# Adjustment
# --------------------------------------------------------------------------
ADJUSTMENT_SPECS = [
    S("delta_units", "int"),
    S("expected_stock_position_version", "int"),
    S("reason_code", "enum", allowed=calc.REASON_CODES),
]


@bp.post(PREFIX + "/stock-positions/<stock_position_id>/adjustments")
def request_adjustment(stock_position_id):
    require_roles("InventoryAnalyst", "InventorySupervisor", "ShrinkController")
    position = lookup("stock_positions", stock_position_id)
    body = body_json()
    investigation = None
    if body.get("investigation_id") is not None:
        investigation = lookup("investigations", body.get("investigation_id"))
    data = parse_body(body, ADJUSTMENT_SPECS)
    if data["expected_stock_position_version"] != position["version"]:
        raise ApiError("ERR_STALE_STOCK_POSITION_VERSION",
                       "expected_stock_position_version does not match the stored version")
    if data["delta_units"] == 0:
        raise ApiError("ERR_ZERO_DELTA_UNITS", "delta_units may not be zero")
    adjustment = calc.mint_adjustment(position, data["delta_units"], data["reason_code"],
                                      investigation, acting_user())
    calc.touch(position)
    return created(adjustment)


@bp.get(PREFIX + "/adjustments/<adjustment_id>")
def get_adjustment(adjustment_id):
    require_read()
    return ok(lookup("adjustments", adjustment_id))


@bp.get(PREFIX + "/adjustments")
def list_adjustments():
    require_read()
    approval_state = filter_enum("approval_state", calc.APPROVAL_STATES)
    posting_state = filter_enum("posting_state", calc.POSTING_STATES)
    predicates = []
    for param in ("stock_position_id", "investigation_id"):
        value = filter_str(param)
        if value is not None:
            predicates.append((param, value))
    if approval_state is not None:
        predicates.append(("approval_state", approval_state))
    if posting_state is not None:
        predicates.append(("posting_state", posting_state))
    return _list("adjustments", predicates)


NOTE_SPECS = [S("note", "str", required=False, max_len=2000)]


@bp.post(PREFIX + "/adjustments/<adjustment_id>/approve")
def approve_adjustment(adjustment_id):
    require_roles("InventorySupervisor", "ShrinkController")
    adjustment = lookup("adjustments", adjustment_id)
    parse_body(body_json(), [])
    if adjustment["approval_state"] != "PENDING":
        raise ApiError("ERR_ADJUSTMENT_INVALID_STATE",
                       "only a PENDING adjustment may be approved")
    segregation_check(adjustment["requested_by_user_id"])
    if (adjustment["value_impact_cents"] > calc.SUPERVISOR_SINGLE_APPROVAL_CAP_CENTS
            and acting_role() != "ShrinkController"):
        raise ApiError("ERR_ADJUSTMENT_ABOVE_SUPERVISOR_CAP",
                       "value impact exceeds the supervisor single-approval cap")
    adjustment["approval_state"] = "APPROVED"
    adjustment["approved_by_user_id"] = acting_user()
    calc.touch(adjustment)
    return ok(adjustment)


@bp.post(PREFIX + "/adjustments/<adjustment_id>/reject")
def reject_adjustment(adjustment_id):
    require_roles("InventorySupervisor", "ShrinkController")
    adjustment = lookup("adjustments", adjustment_id)
    parse_body(body_json(), NOTE_SPECS)
    if adjustment["approval_state"] != "PENDING":
        raise ApiError("ERR_ADJUSTMENT_INVALID_STATE",
                       "only a PENDING adjustment may be rejected")
    segregation_check(adjustment["requested_by_user_id"])
    adjustment["approval_state"] = "REJECTED"
    adjustment["approved_by_user_id"] = acting_user()
    calc.touch(adjustment)
    return ok(adjustment)


@bp.post(PREFIX + "/adjustments/<adjustment_id>/post")
def post_adjustment_route(adjustment_id):
    require_roles("InventorySupervisor", "ShrinkController")
    adjustment = lookup("adjustments", adjustment_id)
    parse_body(body_json(), [])
    position = db.stock_positions[adjustment["stock_position_id"]]
    if adjustment["posting_state"] != "UNPOSTED":
        raise ApiError("ERR_ADJUSTMENT_INVALID_STATE",
                       "only an UNPOSTED adjustment may be posted")
    if position["tag_integrity_hold"]:
        raise ApiError("ERR_TAG_INTEGRITY_HOLD",
                       "the position carries a tag integrity hold")
    if adjustment["investigation_id"] is not None:
        investigation = db.investigations.get(adjustment["investigation_id"])
        if investigation is None or investigation["status"] != "CLOSED":
            raise ApiError("ERR_INVESTIGATION_NOT_CLOSED",
                           "the linked investigation is not CLOSED")
    if adjustment["approval_state"] not in ("NOT_REQUIRED", "APPROVED"):
        raise ApiError("ERR_ADJUSTMENT_APPROVAL_REQUIRED",
                       "the adjustment still requires approval")
    calc.post_adjustment(adjustment, position)
    return ok(adjustment)


@bp.post(PREFIX + "/adjustments/<adjustment_id>/reverse")
def reverse_adjustment_route(adjustment_id):
    require_roles("InventorySupervisor", "ShrinkController")
    adjustment = lookup("adjustments", adjustment_id)
    parse_body(body_json(), NOTE_SPECS)
    position = db.stock_positions[adjustment["stock_position_id"]]
    if adjustment["posting_state"] != "POSTED":
        raise ApiError("ERR_ADJUSTMENT_INVALID_STATE",
                       "only a POSTED adjustment may be reversed")
    segregation_check(adjustment["requested_by_user_id"])
    calc.reverse_adjustment(adjustment, position)
    return ok(adjustment)
