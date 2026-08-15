"""CartExchangeRun endpoints (PRD 3.2, 3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import services
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_ALREADY_TERMINAL, ERR_COUNT_EXCEEDS_ON_HAND, \
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NO_PAR_LEVEL, ERR_NOT_FOUND, \
    ERR_RUN_WINDOW_CONFLICT, ERR_STORAGE_NOT_ATTESTED, ERR_INVALID_WINDOW, \
    ERR_UNIT_OWNERSHIP, raise_err
from serializers import run_out
from util import body_json, bump, fk_ref, get_or_404, list_response, new_record, \
    req_dt, success_object

bp = Blueprint("cart_runs", __name__)

RUN_BUFFER = timedelta(minutes=120)


def _windows_conflict(s1, e1, s2, e2):
    """Overlap, or a clear gap of strictly less than 120 minutes."""
    if s1 < e2 and s2 < e1:
        return True
    if e1 <= s2:
        gap = s2 - e1
    else:
        gap = s1 - e2
    return gap < RUN_BUFFER


def _check_unit_ownership(uid, run):
    if run["unit_id"] != uid:
        raise_err(ERR_UNIT_OWNERSHIP,
                  "UnitClerk may only act on runs of their own unit")


def _piece_lines_shape(body, key):
    """Parse a [{stock_id, pieces}] list. FK existence (404) first, then the
    per-entry shape checks (400). Returns aggregated entries in first-seen
    order as a list of (stock_record, pieces)."""
    raw = body.get(key)
    if not isinstance(raw, list):
        raise_err(ERR_INVALID_REQUEST, "%s is required and must be a list" % key)
    for entry in raw:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "%s entries must be objects" % key)
        sid = entry.get("stock_id")
        if not isinstance(sid, str) or sid not in store.stocks:
            raise_err(ERR_NOT_FOUND, "LinenStock not found: %s" % sid)
    totals = {}
    order = []
    for entry in raw:
        sid = entry["stock_id"]
        pieces = entry.get("pieces")
        if not isinstance(pieces, int) or isinstance(pieces, bool) or pieces < 0:
            raise_err(ERR_INVALID_REQUEST, "%s.pieces must be an integer >= 0" % key)
        if sid not in totals:
            totals[sid] = 0
            order.append(sid)
        totals[sid] += pieces
    return [(store.stocks[sid], totals[sid]) for sid in order]


@bp.route("/cart-runs", methods=["POST"])
def create_cart_run():
    _, role = authenticate()
    authorize(role, ["EVSOperator"])
    body = body_json()

    unit = fk_ref(body, "unit_id", store.units, "Unit")
    start = req_dt(body, "scheduled_start")
    end = req_dt(body, "scheduled_end")

    # temporal rules (priority 9)
    if end <= start:
        raise_err(ERR_INVALID_WINDOW, "scheduled_end must be after scheduled_start")
    for r in store.cart_runs.values():
        if r["unit_id"] == unit["id"] and r["status"] != "RECONCILED":
            if _windows_conflict(start, end, r["scheduled_start"], r["scheduled_end"]):
                raise_err(ERR_RUN_WINDOW_CONFLICT,
                          "window overlaps or leaves < 120 minutes vs run %s" % r["id"])

    # referential (priority 10): the unit needs at least one par level
    if not any(p["unit_id"] == unit["id"] for p in store.par_levels.values()):
        raise_err(ERR_NO_PAR_LEVEL,
                  "unit %s has no par levels configured" % unit["id"])

    rec = new_record()
    rec.update({
        "unit_id": unit["id"],
        "manifest_id": None,
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "SCHEDULED",
        "soiled_lines": [],
        "restock_lines": [],
        "shortage_flag": False,
        "storage_attested": None,
        "completed_at": None,
        "late_delivery": False,
    })
    store.cart_runs[rec["id"]] = rec
    return success_object(run_out(rec), 201)


@bp.route("/cart-runs/<cart_run_id>", methods=["GET"])
def get_cart_run(cart_run_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.cart_runs, cart_run_id, "CartExchangeRun")
    return success_object(run_out(rec))


@bp.route("/cart-runs", methods=["GET"])
def list_cart_runs():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.cart_runs.values())
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        records = [r for r in records if r["unit_id"] == unit_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    manifest_id = request.args.get("manifest_id")
    if manifest_id is not None:
        records = [r for r in records if r["manifest_id"] == manifest_id]
    return list_response(records, run_out)


@bp.route("/cart-runs/<cart_run_id>/complete", methods=["POST"])
def complete_cart_run(cart_run_id):
    """restock_quantity calc (PRD 3.3): per par level, deficit vs effective_par,
    CRITICAL-posture triage halves deficits for STANDARD units, delivery is
    capped by in_circulation."""
    _, role = authenticate()
    authorize(role, ["EVSOperator"])
    run = get_or_404(store.cart_runs, cart_run_id, "CartExchangeRun")
    body = body_json()

    soiled = _piece_lines_shape(body, "soiled_lines")
    sa = body.get("storage_attested")
    if sa is not None and not isinstance(sa, bool):
        raise_err(ERR_INVALID_REQUEST, "storage_attested must be a boolean")

    # state guard (priority 7)
    if run["status"] == "RECONCILED":
        raise_err(ERR_ALREADY_TERMINAL, "cart run is RECONCILED (terminal)")
    if run["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE,
                  "complete requires status SCHEDULED, got %s" % run["status"])

    # safety (priority 8)
    if sa is not True:
        raise_err(ERR_STORAGE_NOT_ATTESTED,
                  "clean-storage compliance attestation is required")

    unit = store.units.get(run["unit_id"])
    soiled_by_stock = {s["id"]: pcs for s, pcs in soiled}

    # fiscal guard (priority 11): soiled counts may not exceed on_hand
    for stock, pieces in soiled:
        par = services.find_par(unit["id"], stock["id"])
        on_hand = par["on_hand"] if par else 0
        if pieces > on_hand:
            raise_err(ERR_COUNT_EXCEEDS_ON_HAND,
                      "soiled pieces %s exceed on_hand %s for stock %s"
                      % (pieces, on_hand, stock["id"]))

    # apply: per par level of the unit, in creation order
    restock_lines = []
    shortage = False
    pars = sorted((p for p in store.par_levels.values() if p["unit_id"] == unit["id"]),
                  key=lambda p: p["_seq"])
    for par in pars:
        stock = store.stocks[par["stock_id"]]
        soiled_pieces = soiled_by_stock.get(par["stock_id"], 0)
        on_hand_after = par["on_hand"] - soiled_pieces
        deficit = max(par["effective_par"] - on_hand_after, 0)
        if services.stock_posture(stock) == "CRITICAL" and unit["unit_tier"] == "STANDARD":
            deficit = deficit // 2  # triage: halved, rounded down
        deliver = min(deficit, stock["in_circulation"])
        if deliver < deficit:
            shortage = True
        new_on_hand = on_hand_after + deliver
        if new_on_hand != par["on_hand"]:
            par["on_hand"] = new_on_hand
            bump(par)
        changed = False
        if deliver:
            stock["in_circulation"] -= deliver
            changed = True
        if soiled_pieces:
            stock["in_wash"] += soiled_pieces
            changed = True
        if changed:
            bump(stock)
        restock_lines.append({"stock_id": par["stock_id"], "pieces": deliver})

    # soiled lines for stocks with no par level on this unit still enter the wash
    for stock, pieces in soiled:
        if services.find_par(unit["id"], stock["id"]) is None and pieces:
            stock["in_wash"] += pieces
            bump(stock)

    run["soiled_lines"] = [{"stock_id": s["id"], "pieces": pcs} for s, pcs in soiled]
    run["restock_lines"] = restock_lines
    run["shortage_flag"] = shortage
    run["storage_attested"] = True
    run["completed_at"] = clock.now()
    run["late_delivery"] = run["completed_at"] > run["scheduled_end"]
    run["status"] = "COMPLETED"
    bump(run)
    return success_object(run_out(run), 200)


@bp.route("/cart-runs/<cart_run_id>/dispute", methods=["POST"])
def dispute_cart_run(cart_run_id):
    uid, role = authenticate()
    authorize(role, ["UnitClerk"])
    run = get_or_404(store.cart_runs, cart_run_id, "CartExchangeRun")
    body_json()  # optional reason; accepted and not stored

    if run["status"] == "RECONCILED":
        raise_err(ERR_ALREADY_TERMINAL, "cart run is RECONCILED (terminal)")
    if run["status"] not in ("COMPLETED", "RECOUNTED"):
        raise_err(ERR_INVALID_STATE,
                  "dispute requires status COMPLETED or RECOUNTED, got %s" % run["status"])
    _check_unit_ownership(uid, run)

    run["status"] = "DISPUTED"
    bump(run)
    return success_object(run_out(run), 200)


@bp.route("/cart-runs/<cart_run_id>/recount", methods=["POST"])
def recount_cart_run(cart_run_id):
    """Compensating deltas vs the currently recorded soiled counts, then a
    restock top-up per corrected stock (PRD 3.3)."""
    uid, role = authenticate()
    authorize(role, ["UnitClerk"])
    run = get_or_404(store.cart_runs, cart_run_id, "CartExchangeRun")
    body = body_json()

    corrected = _piece_lines_shape(body, "corrected_soiled_lines")

    if run["status"] == "RECONCILED":
        raise_err(ERR_ALREADY_TERMINAL, "cart run is RECONCILED (terminal)")
    if run["status"] != "DISPUTED":
        raise_err(ERR_INVALID_STATE,
                  "recount requires status DISPUTED, got %s" % run["status"])
    _check_unit_ownership(uid, run)

    current = {e["stock_id"]: e["pieces"] for e in run["soiled_lines"]}
    for stock, pieces in corrected:
        if pieces > current.get(stock["id"], 0):
            raise_err(ERR_INVALID_REQUEST,
                      "corrected pieces %s exceed the recorded soiled pieces %s "
                      "for stock %s" % (pieces, current.get(stock["id"], 0), stock["id"]))

    unit = store.units.get(run["unit_id"])

    # compensation vs the currently recorded counts (one version bump per
    # resource per request — PRD 2.4)
    changed_pars = set()
    changed_stocks = set()
    for stock, pieces in corrected:
        delta = current.get(stock["id"], 0) - pieces
        if delta == 0:
            continue
        par = services.find_par(unit["id"], stock["id"])
        if par is not None:
            par["on_hand"] += delta
            changed_pars.add(par["id"])
        stock["in_wash"] -= delta
        changed_stocks.add(stock["id"])

    # merge corrections into the recorded soiled lines (order preserved)
    merged_order = [e["stock_id"] for e in run["soiled_lines"]]
    merged = dict(current)
    for stock, pieces in corrected:
        if stock["id"] not in merged:
            merged_order.append(stock["id"])
        merged[stock["id"]] = pieces
    run["soiled_lines"] = [{"stock_id": sid, "pieces": merged[sid]}
                           for sid in merged_order]

    # restock top-up per corrected stock (overstock is allowed, not clamped)
    for stock, _pieces in corrected:
        par = services.find_par(unit["id"], stock["id"])
        if par is None:
            continue
        additional = min(max(par["effective_par"] - par["on_hand"], 0),
                         stock["in_circulation"])
        if additional > 0:
            par["on_hand"] += additional
            changed_pars.add(par["id"])
            stock["in_circulation"] -= additional
            changed_stocks.add(stock["id"])

    for pid in changed_pars:
        bump(store.par_levels[pid])
    for sid in changed_stocks:
        bump(store.stocks[sid])

    run["status"] = "RECOUNTED"
    bump(run)
    return success_object(run_out(run), 200)


@bp.route("/cart-runs/<cart_run_id>/reconcile", methods=["POST"])
def reconcile_cart_run(cart_run_id):
    uid, role = authenticate()
    authorize(role, ["UnitClerk"])
    run = get_or_404(store.cart_runs, cart_run_id, "CartExchangeRun")
    body_json()

    if run["status"] == "RECONCILED":
        raise_err(ERR_ALREADY_TERMINAL, "cart run is RECONCILED (terminal)")
    if run["status"] not in ("COMPLETED", "RECOUNTED"):
        raise_err(ERR_INVALID_STATE,
                  "reconcile requires status COMPLETED or RECOUNTED, got %s" % run["status"])
    _check_unit_ownership(uid, run)

    run["status"] = "RECONCILED"
    bump(run)
    return success_object(run_out(run), 200)
