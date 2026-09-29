"""Shrink periods, dual-variant attribution and vendor chargebacks (PRD 3.8)."""

from flask import Blueprint

import calc
from db import db, new_id
from errors import ApiError
from middleware import require_read, require_roles
from response import created, ok, ok_list, paginate, read_pagination
from validate import S, body_json, filter_enum, filter_str, lookup, parse_body

bp = Blueprint("shrink", __name__)
PREFIX = "/inventory-integrity"

PERIOD_STATUSES = ("OPEN", "PROVISIONAL_CLOSED", "FINAL_CLOSED")

NOTE_SPECS = [S("note", "str", required=False, max_len=2000)]

PERIOD_SPECS = [
    S("period_start", "date"),
    S("period_end", "date"),
    S("sales_at_cost_cents", "int", min=1),
]


def _bad_state(message):
    raise ApiError("ERR_SHRINK_PERIOD_INVALID_STATE", message)


def _close_transition(period):
    """Re-derive the buckets and bump ``version`` exactly once for the hop."""
    base_version = period["version"]
    calc.recompute_period(period)
    period["version"] = base_version
    calc.touch(period)


def _overlaps(store_id, start, end):
    for period in calc.rows("shrink_periods"):
        if period["store_id"] != store_id:
            continue
        if period["period_start"] <= end.isoformat() and start.isoformat() <= period["period_end"]:
            return period
    return None


@bp.post(PREFIX + "/shrink-periods")
def create_shrink_period():
    require_roles("ShrinkController", "InventorySupervisor")
    body = body_json()
    store = lookup("stores", body.get("store_id"))
    data = parse_body(body, PERIOD_SPECS)
    start = data["period_start"]
    end = data["period_end"]
    # Rejection tier 8 (business constraint) precedes tier 10 (temporal).
    if _overlaps(store["id"], start, end) is not None:
        raise ApiError("ERR_SHRINK_PERIOD_OVERLAP",
                       "an existing shrink period for this store intersects the range")
    if end < start:
        raise ApiError("ERR_INVALID_PERIOD_RANGE",
                       "period_end must be on or after period_start")
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "store_id": store["id"],
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "sales_at_cost_cents": data["sales_at_cost_cents"],
        "status": "OPEN",
        "theft_cents": 0,
        "damage_cents": 0,
        "process_error_cents": 0,
        "vendor_shortage_cents": 0,
        "unresolved_cents": 0,
        "total_attributable_variance_cents": 0,
        "provisional_total_shrink_cents": 0,
        "final_total_shrink_cents": 0,
        "shrink_rate_bps": 0,
        "reopen_count": 0,
        "chargeback_issued_vendor_ids": [],
        "_waterfall": calc.empty_waterfall(),
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.shrink_periods[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/shrink-periods/<shrink_period_id>")
def get_shrink_period(shrink_period_id):
    require_read()
    return ok(lookup("shrink_periods", shrink_period_id))


@bp.get(PREFIX + "/shrink-periods")
def list_shrink_periods():
    require_read()
    status = filter_enum("status", PERIOD_STATUSES)
    predicates = []
    store_id = filter_str("store_id")
    if store_id is not None:
        predicates.append(("store_id", store_id))
    if status is not None:
        predicates.append(("status", status))
    matched = [r for r in db.shrink_periods.values()
               if all(r.get(key) == value for key, value in predicates)]
    limit, offset = read_pagination()
    page, total = paginate(calc.newest_first(matched), limit, offset)
    return ok_list(page, limit, offset, total)


# --------------------------------------------------------------------------
# attribution: both variants side by side, computed and never stored
# --------------------------------------------------------------------------

def _attribution(period):
    waterfall = period.get("_waterfall") or calc.empty_waterfall()
    buckets = {
        "theft_cents": waterfall["theft_cents"],
        "damage_cents": waterfall["damage_cents"],
        "process_error_cents": waterfall["process_error_cents"],
        "vendor_shortage_cents": waterfall["vendor_shortage_cents"],
    }
    unresolved = waterfall["unresolved_cents"]
    for inv in calc.period_investigations(period["id"]):
        amount = inv["variance_value_cents"]
        if inv["status"] == "CLOSED":
            bucket = calc.CAUSE_BUCKET.get(inv.get("approved_root_cause"))
            if bucket:
                buckets[bucket] += amount
        elif inv["status"] in calc.INVESTIGATION_NON_TERMINAL:
            unresolved += amount
    bucket_total = sum(buckets.values())
    figures = dict(buckets)
    figures["unresolved_cents"] = unresolved
    figures["provisional_total_shrink_cents"] = bucket_total + unresolved
    figures["final_total_shrink_cents"] = bucket_total
    figures["total_attributable_variance_cents"] = bucket_total + unresolved
    sales = period["sales_at_cost_cents"]
    figures["provisional_shrink_rate_bps"] = calc.shrink_rate_bps(
        figures["provisional_total_shrink_cents"], sales)
    figures["final_shrink_rate_bps"] = calc.shrink_rate_bps(
        figures["final_total_shrink_cents"], sales)
    figures["active_variant"] = "final" if period["status"] == "FINAL_CLOSED" else "provisional"
    return figures


@bp.get(PREFIX + "/shrink-periods/<shrink_period_id>/attribution")
def shrink_period_attribution(shrink_period_id):
    require_read()
    period = lookup("shrink_periods", shrink_period_id)
    figures = _attribution(period)
    return ok({
        "theft_cents": figures["theft_cents"],
        "damage_cents": figures["damage_cents"],
        "process_error_cents": figures["process_error_cents"],
        "vendor_shortage_cents": figures["vendor_shortage_cents"],
        "unresolved_cents": figures["unresolved_cents"],
        "total_attributable_variance_cents": figures["total_attributable_variance_cents"],
        "provisional_total_shrink_cents": figures["provisional_total_shrink_cents"],
        "final_total_shrink_cents": figures["final_total_shrink_cents"],
        "provisional_shrink_rate_bps": figures["provisional_shrink_rate_bps"],
        "final_shrink_rate_bps": figures["final_shrink_rate_bps"],
        "active_variant": figures["active_variant"],
    })


# --------------------------------------------------------------------------
# closure lifecycle
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/shrink-periods/<shrink_period_id>/provisional-close")
def provisional_close(shrink_period_id):
    require_roles("ShrinkController")
    period = lookup("shrink_periods", shrink_period_id)
    parse_body(body_json(), [])
    if period["status"] != "OPEN":
        _bad_state("only an OPEN period may be provisionally closed")
    period["status"] = "PROVISIONAL_CLOSED"
    _close_transition(period)
    return ok(period)


@bp.post(PREFIX + "/shrink-periods/<shrink_period_id>/reopen")
def reopen_shrink_period(shrink_period_id):
    require_roles("ShrinkController")
    period = lookup("shrink_periods", shrink_period_id)
    parse_body(body_json(), NOTE_SPECS)
    if period["status"] != "PROVISIONAL_CLOSED":
        _bad_state("only a PROVISIONAL_CLOSED period may be reopened")
    period["status"] = "OPEN"
    period["reopen_count"] += 1
    _close_transition(period)
    return ok(period)


@bp.post(PREFIX + "/shrink-periods/<shrink_period_id>/final-close")
def final_close(shrink_period_id):
    require_roles("ShrinkController")
    period = lookup("shrink_periods", shrink_period_id)
    parse_body(body_json(), [])
    if period["status"] != "PROVISIONAL_CLOSED":
        _bad_state("only a PROVISIONAL_CLOSED period may be finally closed")
    for inv in calc.period_investigations(period["id"]):
        if inv["status"] in calc.INVESTIGATION_NON_TERMINAL:
            raise ApiError("ERR_OPEN_INVESTIGATIONS",
                           "an investigation attributed to this period is still unresolved")
    period["status"] = "FINAL_CLOSED"
    _close_transition(period)
    return ok(period)


# --------------------------------------------------------------------------
# vendor chargebacks and credits
# --------------------------------------------------------------------------

def _attributable_shortage(vendor_id, period_id):
    total = 0
    for inv in calc.rows("investigations"):
        if inv.get("shrink_period_id") != period_id:
            continue
        if inv["status"] != "CLOSED":
            continue
        if inv.get("approved_root_cause") != "VENDOR_SHORTAGE":
            continue
        item = db.items.get(inv.get("_item_id"))
        if item is None or item["primary_vendor_id"] != vendor_id:
            continue
        total += inv["variance_value_cents"]
    return total


@bp.post(PREFIX + "/vendors/<vendor_id>/chargebacks")
def issue_chargeback(vendor_id):
    require_roles("ShrinkController")
    vendor = lookup("vendors", vendor_id)
    body = body_json()
    period = lookup("shrink_periods", body.get("shrink_period_id"))
    parse_body(body, [])
    shortage = _attributable_shortage(vendor["id"], period["id"])
    if shortage <= 0:
        raise ApiError("ERR_NO_VENDOR_SHORTAGE",
                       "no closed VENDOR_SHORTAGE attribution names this vendor in the period")
    if vendor["id"] in period["chargeback_issued_vendor_ids"]:
        raise ApiError("ERR_CHARGEBACK_ALREADY_ISSUED",
                       "a chargeback has already been issued to this vendor out of the period")
    tier, gross, credit, net = calc.vendor_shortage_chargeback(shortage)
    vendor["lifetime_chargeback_gross_cents"] += gross
    vendor["credited_cents"] += credit
    vendor["chargeback_balance_cents"] = (vendor["lifetime_chargeback_gross_cents"]
                                         - vendor["credited_cents"])
    calc.touch(vendor)
    period["chargeback_issued_vendor_ids"] = (list(period["chargeback_issued_vendor_ids"])
                                              + [vendor["id"]])
    calc.touch(period)
    return created({
        "vendor_id": vendor["id"],
        "shrink_period_id": period["id"],
        "attributable_shortage_cents": shortage,
        "tier": tier,
        "chargeback_gross_cents": gross,
        "vendor_credit_cents": credit,
        "net_chargeback_cents": net,
        "lifetime_chargeback_gross_cents": vendor["lifetime_chargeback_gross_cents"],
        "credited_cents": vendor["credited_cents"],
        "chargeback_balance_cents": vendor["chargeback_balance_cents"],
    })


@bp.post(PREFIX + "/vendors/<vendor_id>/chargeback-credits")
def grant_chargeback_credit(vendor_id):
    require_roles("ShrinkController")
    vendor = lookup("vendors", vendor_id)
    data = parse_body(body_json(), [S("credit_cents", "int", min=1)] + NOTE_SPECS)
    if data["credit_cents"] > vendor["chargeback_balance_cents"]:
        raise ApiError("ERR_CREDIT_EXCEEDS_BALANCE",
                       "credit_cents exceeds the vendor's outstanding chargeback balance")
    vendor["credited_cents"] += data["credit_cents"]
    vendor["chargeback_balance_cents"] = (vendor["lifetime_chargeback_gross_cents"]
                                         - vendor["credited_cents"])
    calc.touch(vendor)
    return created({
        "vendor_id": vendor["id"],
        "credit_cents": data["credit_cents"],
        "lifetime_chargeback_gross_cents": vendor["lifetime_chargeback_gross_cents"],
        "credited_cents": vendor["credited_cents"],
        "chargeback_balance_cents": vendor["chargeback_balance_cents"],
    })
