"""Cycle lines: re-screening, the three-rung substitution ladder, short fill."""

from flask import Blueprint

import calc
import constants as C
import serialize
import services
import shapes
import store
from auth import api, get_cycle_line, lookup
from envelope import ok, paginate
from errors import ApiError
from store import db, now, touch

bp = Blueprint("lines", __name__)

READ_ROLES = ["AccountHolder", "SupportAgent", "OpsAdmin"]


@api(bp, "GET", "/cycle-lines/<id>", READ_ROLES)
def read_line(id):
    return ok(serialize.cycle_line(get_cycle_line(id)))


@api(bp, "GET", "/cycle-lines", READ_ROLES)
def list_lines():
    rows = [r for r in db.cycle_lines.values()
            if shapes.match(r, "cycle_id", shapes.qs("cycle_id"))
            and shapes.match(r, "sku_id", shapes.qs("sku_id"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.cycle_line)


@api(bp, "POST", "/cycle-lines/<id>/substitute", ["OpsAdmin"])
def substitute(id):
    line = get_cycle_line(id)
    cycle = db.cycles.get(line["cycle_id"])
    sub = services.subscription_of_cycle(cycle) if cycle else None
    child = services.child_of_subscription(sub) if sub else None
    plan_row = services.plan_of_subscription(sub) if sub else None

    if line["status"] != "SUBSTITUTION_PENDING":
        raise ApiError("ERR_LINE_STATE_INVALID")
    # The cap is checked when the substitution is ATTEMPTED, not when the line
    # is flagged: a line at 3 attempts simply sits in SUBSTITUTION_PENDING.
    if int(line["substitution_attempts"]) >= C.SUBSTITUTION_ATTEMPT_CAP:
        raise ApiError("ERR_SUBSTITUTION_CAP_EXCEEDED")

    from_sku = db.skus.get(line["sku_id"])
    if from_sku is None:
        raise ApiError("ERR_SKU_NOT_FOUND")
    reason = line.get("_pending_reason") or "ALLERGEN_RESCREEN"

    rung, candidates = services.substitution_candidates(
        line, from_sku, child, plan_row)

    if candidates:
        winner = candidates[0]
        unit = calc.effective_unit_price(winner)
        delta = unit - calc.effective_unit_price(from_sku)
        services.write_substitution_event(
            line, from_sku["id"], winner["id"], rung, "SUBSTITUTED", delta, reason)
        line["sku_id"] = winner["id"]
        line["substitution_attempts"] = int(line["substitution_attempts"]) + 1
        line["unit_price_cents"] = unit
        line["line_total_cents"] = int(line["quantity_packs"]) * unit
        line["status"] = "SUBSTITUTED"
        line["_pending_reason"] = None
        touch(line)
    else:
        # Every rung came back empty: SHORT FILL. This is a 200 OK outcome.
        services.write_substitution_event(
            line, from_sku["id"], None, 0, "SHORT_FILLED", 0, reason)
        face = calc.round_half_up(
            calc.dec(line["quantity_packs"]) * calc.dec(line["unit_price_cents"])
            * calc.dec(C.SHORT_FILL_CREDIT_PCT))
        line["short_filled_units"] = int(line["quantity_packs"]) * \
            int(from_sku["pack_size_units"])
        line["quantity_packs"] = 0
        line["line_total_cents"] = 0
        line["status"] = "SHORT_FILLED"
        line["_pending_reason"] = None
        touch(line)
        if sub is not None and face > 0:
            services.issue_credit(
                sub["account_id"], "SHORT_FILL", face, True,
                store.plus_days(now(), C.CREDIT_EXPIRY_DAYS))

    if cycle is not None:
        services.apply_pricing(cycle)
        touch(cycle)
    if sub is not None:
        services.recompute_account_estimate(sub["account_id"])
    return ok(serialize.cycle_line(line))


@api(bp, "POST", "/cycle-lines/<id>/rescreen", ["OpsAdmin"])
def rescreen(id):
    line = get_cycle_line(id)
    cycle = db.cycles.get(line["cycle_id"])
    sub = services.subscription_of_cycle(cycle) if cycle else None
    child = services.child_of_subscription(sub) if sub else None
    plan_row = services.plan_of_subscription(sub) if sub else None

    if cycle is None or cycle["status"] not in ("PLANNED", "ALLOCATED"):
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if line["status"] not in ("ALLOCATED", "SUBSTITUTED"):
        raise ApiError("ERR_LINE_STATE_INVALID")

    sku = db.skus.get(line["sku_id"])
    if sku is not None and child is not None and \
            not services._passes_safety(sku, child, plan_row):
        services.flag_line_pending(line, "ALLERGEN_RESCREEN")
    return ok(serialize.cycle_line(line))


@api(bp, "GET", "/substitution-events/<id>", READ_ROLES)
def read_substitution_event(id):
    return ok(serialize.substitution_event(
        lookup(db.substitution_events, id, "SubstitutionEvent")))


@api(bp, "GET", "/substitution-events", READ_ROLES)
def list_substitution_events():
    rows = [r for r in db.substitution_events.values()
            if shapes.match(r, "cycle_line_id", shapes.qs("cycle_line_id"))
            and shapes.match(r, "from_sku_id", shapes.qs("from_sku_id"))
            and shapes.match(r, "to_sku_id", shapes.qs("to_sku_id"))
            and shapes.match(r, "outcome", shapes.qs("outcome"))
            and shapes.match(r, "reason", shapes.qs("reason"))]
    return paginate(rows, serialize.substitution_event)
