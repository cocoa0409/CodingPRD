"""SurgeEvent endpoints (PRD 3.8)."""
from fractions import Fraction

from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_ALREADY_TERMINAL, ERR_FACILITY_IN_SURGE, \
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INVALID_WINDOW, \
    ERR_SURGE_WINDOW_CONFLICT, raise_err
from serializers import surge_out
from util import body_json, bump, ceil_int, dec, fk_ref, get_or_404, \
    list_response, new_record, req_dt, req_enum, req_number, success_object

bp = Blueprint("surges", __name__)

SEVERITIES = ["LEVEL_1", "LEVEL_2"]


@bp.route("/surge-events", methods=["POST"])
def create_surge():
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    body = body_json()

    fac = fk_ref(body, "facility_id", store.facilities, "Facility")
    severity = req_enum(body, "severity", SEVERITIES)
    mult = req_number(body, "par_multiplier")
    if dec(mult) <= 0:
        raise_err(ERR_INVALID_REQUEST, "par_multiplier must be > 0")
    starts = req_dt(body, "starts_at")
    ends = req_dt(body, "ends_at")

    # temporal (priority 9): window validity, then closed-interval overlap
    if ends <= starts:
        raise_err(ERR_INVALID_WINDOW, "ends_at must be after starts_at")
    for s in store.surges.values():
        if s["facility_id"] == fac["id"] and s["status"] in ("DECLARED", "ACTIVE"):
            if starts <= s["ends_at"] and s["starts_at"] <= ends:
                raise_err(ERR_SURGE_WINDOW_CONFLICT,
                          "surge window overlaps surge %s (closed intervals)" % s["id"])

    rec = new_record()
    rec.update({
        "facility_id": fac["id"],
        "severity": severity,
        "par_multiplier": mult,
        "starts_at": starts,
        "ends_at": ends,
        "status": "DECLARED",
    })
    store.surges[rec["id"]] = rec
    return success_object(surge_out(rec), 201)


@bp.route("/surge-events/<surge_event_id>", methods=["GET"])
def get_surge(surge_event_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.surges, surge_event_id, "SurgeEvent")
    return success_object(surge_out(rec))


@bp.route("/surge-events", methods=["GET"])
def list_surges():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.surges.values())
    facility_id = request.args.get("facility_id")
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, surge_out)


@bp.route("/surge-events/<surge_event_id>/activate", methods=["POST"])
def activate_surge(surge_event_id):
    """Depth-3 cascade: posture flip -> effective_par recompute -> reserve
    waterfall (CRITICAL-tier units first, deficit-ratio DESC, oldest unit
    breaks ties; stocks visited oldest first). Zero reserve never blocks."""
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    sg = get_or_404(store.surges, surge_event_id, "SurgeEvent")
    body_json()

    if sg["status"] == "CLOSED":
        raise_err(ERR_ALREADY_TERMINAL, "surge event is CLOSED (terminal)")
    if sg["status"] != "DECLARED":
        raise_err(ERR_INVALID_STATE,
                  "activate requires status DECLARED, got %s" % sg["status"])

    fac = store.facilities.get(sg["facility_id"])
    if fac["surge_posture"] != "NORMAL":
        raise_err(ERR_FACILITY_IN_SURGE,
                  "facility %s is already in SURGE posture" % fac["id"])

    fac["surge_posture"] = "SURGE"
    bump(fac)

    # One version bump per resource per request: collect every mutation the
    # cascade makes to a par level (effective_par recompute + waterfall
    # allocation), then bump each touched resource once (PRD 2.4).
    fac_pars = services.pars_of_facility(fac["id"])
    changed_pars = set()
    for p in fac_pars:
        new_eff = ceil_int(dec(p["base_par_quantity"]) * dec(sg["par_multiplier"]))
        if new_eff != p["effective_par"]:
            p["effective_par"] = new_eff
            changed_pars.add(p["id"])

    # reserve waterfall
    fac_stocks = sorted(
        (s for s in store.stocks.values() if s["facility_id"] == fac["id"]),
        key=lambda s: s["_seq"])
    for stock in fac_stocks:
        if stock["reserve_pieces"] <= 0:
            continue
        candidates = [p for p in fac_pars if p["stock_id"] == stock["id"]]

        def rank(par):
            u = store.units.get(par["unit_id"])
            tier = 0 if u["unit_tier"] == "CRITICAL" else 1
            deficit = max(par["effective_par"] - par["on_hand"], 0)
            ratio = (Fraction(deficit, par["effective_par"])
                     if par["effective_par"] > 0 else Fraction(0))
            return (tier, -ratio, u["_seq"])

        stock_changed = False
        for par in sorted(candidates, key=rank):
            if stock["reserve_pieces"] <= 0:
                break
            deficit = max(par["effective_par"] - par["on_hand"], 0)
            alloc = min(deficit, stock["reserve_pieces"])
            if alloc > 0:
                stock["reserve_pieces"] -= alloc
                stock_changed = True
                par["on_hand"] += alloc
                changed_pars.add(par["id"])
        if stock_changed:
            bump(stock)

    for pid in changed_pars:
        bump(store.par_levels[pid])

    sg["status"] = "ACTIVE"
    bump(sg)
    return success_object(surge_out(sg), 200)


@bp.route("/surge-events/<surge_event_id>/close", methods=["POST"])
def close_surge(surge_event_id):
    """Posture reverts when no other ACTIVE surge exists; pars revert to base;
    allocated reserve pieces stay at the units (no clawback)."""
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    sg = get_or_404(store.surges, surge_event_id, "SurgeEvent")
    body_json()

    if sg["status"] == "CLOSED":
        raise_err(ERR_ALREADY_TERMINAL, "surge event is CLOSED (terminal)")
    if sg["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE,
                  "close requires status ACTIVE, got %s" % sg["status"])

    sg["status"] = "CLOSED"
    bump(sg)

    fac = store.facilities.get(sg["facility_id"])
    other_active = any(
        s for s in store.surges.values()
        if s["facility_id"] == fac["id"] and s["id"] != sg["id"] and s["status"] == "ACTIVE")
    fac_pars = services.pars_of_facility(fac["id"])
    if not other_active:
        fac["surge_posture"] = "NORMAL"
        bump(fac)
        for p in fac_pars:
            if p["effective_par"] != p["base_par_quantity"]:
                p["effective_par"] = p["base_par_quantity"]
                bump(p)
    else:
        # another surge keeps the facility in SURGE: track its multiplier
        other = next(s for s in store.surges.values()
                     if s["facility_id"] == fac["id"] and s["id"] != sg["id"]
                     and s["status"] == "ACTIVE")
        for p in fac_pars:
            new_eff = ceil_int(dec(p["base_par_quantity"]) * dec(other["par_multiplier"]))
            if new_eff != p["effective_par"]:
                p["effective_par"] = new_eff
                bump(p)

    return success_object(surge_out(sg), 200)
