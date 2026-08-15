"""BuyingPoint, logical clock, Grower, DiscountSchedule, and run_ops sweep."""
from decimal import Decimal

from flask import Blueprint

import calc
from authz import (ADMIN, GROWER, INSPECTOR, LABTECH, CLERK, SHELLER,
                   authenticate, require_roles, check_grower_ownership)
from db import store
from errors import err, invalid_request, invalid_state
from respond import success
from serialize import ser_buying_point, ser_grower, ser_schedule
from store_ops import (get_or_404, json_body, list_response, new_common_fields,
                       req_datetime, req_int, req_str, touch)
from timeutil import fmt_dt

bp = Blueprint("core", __name__)

ALL_ROLES = [ADMIN, GROWER, INSPECTOR, LABTECH, CLERK, SHELLER]


# ---------------------------------------------------------------------------
# BuyingPoint
# ---------------------------------------------------------------------------

@bp.post("/buying-points")
def create_buying_point():
    authenticate()
    data = json_body()
    name = req_str(data, "name")
    crop_year = req_int(data, "crop_year")
    drying_rate = req_int(data, "drying_rate_per_cycle_cents", minimum=0)
    quota_price = req_int(data, "quota_price_cents_per_ton", minimum=0)
    additional_price = req_int(data, "additional_price_cents_per_ton", minimum=0)
    loan_quota = req_int(data, "loan_rate_quota_cents_per_ton", minimum=0)
    loan_additional = req_int(data, "loan_rate_additional_cents_per_ton", minimum=0)
    require_roles([ADMIN])
    bp_rec = new_common_fields()
    bp_rec.update({
        "name": name,
        "crop_year": crop_year,
        "drying_rate_per_cycle_cents": drying_rate,
        "quota_price_cents_per_ton": quota_price,
        "additional_price_cents_per_ton": additional_price,
        "loan_rate_quota_cents_per_ton": loan_quota,
        "loan_rate_additional_cents_per_ton": loan_additional,
        "ops_run_index": 0,
    })
    store.buying_points[bp_rec["id"]] = bp_rec
    return success(ser_buying_point(bp_rec), status=201)


@bp.get("/buying-points/<bp_id>")
def get_buying_point(bp_id):
    require_roles(ALL_ROLES)
    bp_rec = get_or_404(store.buying_points, bp_id)
    return success(ser_buying_point(bp_rec))


@bp.post("/buying-points/<bp_id>/run_ops")
def run_ops(bp_id):
    require_roles([ADMIN])
    bp_rec = get_or_404(store.buying_points, bp_id)
    bp_rec["ops_run_index"] += 1
    touch(bp_rec)
    _ops_run_sweep(bp_rec)
    return success(ser_buying_point(bp_rec))


def _suspend_grower_for_strikes(grower):
    """Grower -> SUSPENDED; cancels the grower's BOOKED bookings (their loads
    return to drying_status REQUIRED)."""
    grower["status"] = "SUSPENDED"
    touch(grower)
    for b in calc.sorted_by_seq(store.dryer_bookings.values()):
        load = store.loads.get(b["load_id"])
        if load is not None and load["grower_id"] == grower["id"] and b["status"] == "BOOKED":
            b["status"] = "CANCELLED"
            touch(b)
            load["drying_status"] = "REQUIRED"
            touch(load)


def _release_call_lines(call):
    """Delete the call's allocation lines (computed reservations release)."""
    doomed = [lid for lid, l in store.allocation_lines.items()
              if l["delivery_call_id"] == call["id"]]
    for lid in doomed:
        del store.allocation_lines[lid]


def _ops_run_sweep(bp_rec):
    """calculations.ops_run_sweep — pinned order: (1) dryer bookings, then
    (2) delivery calls. Strict < comparison against the logical clock."""
    now = store.clock
    # (1) BOOKED bookings of this buying point, ends_at < clock, ordered
    # starts_at ASC then created_at ASC.
    bookings = []
    for b in store.dryer_bookings.values():
        if b["status"] != "BOOKED" or not b["ends_at"] < now:
            continue
        dryer = store.dryers.get(b["dryer_id"])
        if dryer is not None and dryer["buying_point_id"] == bp_rec["id"]:
            bookings.append(b)
    bookings.sort(key=lambda b: (b["starts_at"], b["created_at"], b["_seq"]))
    for b in bookings:
        if b["status"] != "BOOKED":
            continue  # cancelled mid-sweep by a suspension cascade
        b["status"] = "NO_SHOW"
        touch(b)
        load = store.loads.get(b["load_id"])
        if load is not None:
            load["drying_status"] = "REQUIRED"
            touch(load)
            grower = store.growers.get(load["grower_id"])
            if grower is not None:
                grower["no_show_strikes"] += 1
                touch(grower)
                if grower["no_show_strikes"] >= calc.STRIKE_LIMIT \
                        and grower["status"] == "ACTIVE":
                    _suspend_grower_for_strikes(grower)
    # (2) ISSUED/ALLOCATED delivery calls of this buying point,
    # dock_window_end < clock, ordered dock_window_end ASC then created_at ASC.
    calls = []
    for c in store.delivery_calls.values():
        if c["status"] not in ("ISSUED", "ALLOCATED") or not c["dock_window_end"] < now:
            continue
        contract = store.sheller_contracts.get(c["contract_id"])
        if contract is not None and contract["buying_point_id"] == bp_rec["id"]:
            calls.append(c)
    calls.sort(key=lambda c: (c["dock_window_end"], c["created_at"], c["_seq"]))
    for c in calls:
        if c["status"] not in ("ISSUED", "ALLOCATED"):
            continue  # cancelled mid-sweep by a contract-default cascade
        if c["status"] == "ALLOCATED":
            _release_call_lines(c)
        c["status"] = "DEFAULTED"
        touch(c)
        contract = store.sheller_contracts.get(c["contract_id"])
        if contract is None:
            continue
        contract["default_count"] += 1
        touch(contract)
        if contract["default_count"] >= calc.CONTRACT_DEFAULT_LIMIT \
                and contract["status"] == "ACTIVE":
            contract["status"] = "DEFAULTED"
            touch(contract)
            for sibling in calc.sorted_by_seq(store.delivery_calls.values()):
                if sibling["contract_id"] == contract["id"] \
                        and sibling["status"] in ("ISSUED", "ALLOCATED"):
                    if sibling["status"] == "ALLOCATED":
                        _release_call_lines(sibling)
                    sibling["status"] = "CANCELLED"
                    touch(sibling)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate()
    data = json_body()
    to_iso = req_datetime(data, "to_iso8601")
    require_roles([ADMIN])
    store.clock = to_iso
    return success({"current_utc": fmt_dt(store.clock)})


# ---------------------------------------------------------------------------
# Grower
# ---------------------------------------------------------------------------

@bp.post("/buying-points/growers")
def create_grower():
    authenticate()
    data = json_body()
    name = req_str(data, "name")
    farm_number = req_str(data, "farm_number")
    require_roles([ADMIN])
    for g in store.growers.values():
        if g["farm_number"] == farm_number:
            raise invalid_request("farm_number must be unique across the buying point")
    g = new_common_fields()
    g.update({"name": name, "farm_number": farm_number,
              "status": "ACTIVE", "no_show_strikes": 0})
    store.growers[g["id"]] = g
    return success(ser_grower(g), status=201)


@bp.get("/buying-points/growers/<g_id>")
def get_grower(g_id):
    uid, role = require_roles([ADMIN, CLERK, GROWER])
    g = get_or_404(store.growers, g_id)
    check_grower_ownership(uid, role, g["id"])
    return success(ser_grower(g))


@bp.get("/buying-points/growers")
def list_growers():
    uid, role = require_roles([ADMIN, CLERK, GROWER])
    items = list(store.growers.values())
    if role == GROWER:
        items = [g for g in items if g["id"] == uid]
    from flask import request
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return list_response(items, ser_grower)


@bp.post("/buying-points/growers/<g_id>/suspend")
def suspend_grower(g_id):
    require_roles([ADMIN])
    g = get_or_404(store.growers, g_id)
    if g["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE grower may be suspended")
    g["status"] = "SUSPENDED"
    touch(g)
    # Cascade: cancel the grower's BOOKED bookings; their loads -> REQUIRED.
    for b in calc.sorted_by_seq(store.dryer_bookings.values()):
        load = store.loads.get(b["load_id"])
        if load is not None and load["grower_id"] == g["id"] and b["status"] == "BOOKED":
            b["status"] = "CANCELLED"
            touch(b)
            load["drying_status"] = "REQUIRED"
            touch(load)
    return success(ser_grower(g))


@bp.post("/buying-points/growers/<g_id>/reinstate")
def reinstate_grower(g_id):
    require_roles([ADMIN])
    g = get_or_404(store.growers, g_id)
    if g["status"] != "SUSPENDED":
        raise invalid_state("Only a SUSPENDED grower may be reinstated")
    g["status"] = "ACTIVE"
    g["no_show_strikes"] = 0
    touch(g)
    return success(ser_grower(g))


# ---------------------------------------------------------------------------
# DiscountSchedule
# ---------------------------------------------------------------------------

def _parse_tiers(data, name):
    v = data.get(name)
    if not isinstance(v, list) or len(v) == 0:
        raise invalid_request("Field %s must be a non-empty array of tiers" % name)
    tiers = []
    for t in v:
        if not isinstance(t, dict) or "up_to_pct" not in t \
                or "discount_cents_per_ton" not in t:
            raise invalid_request("Each tier of %s needs up_to_pct and "
                                  "discount_cents_per_ton" % name)
        up_to = t["up_to_pct"]
        if up_to is not None:
            from store_ops import to_decimal
            up_to = to_decimal(up_to, "%s.up_to_pct" % name)
        cpt = t["discount_cents_per_ton"]
        if isinstance(cpt, bool) or not isinstance(cpt, int):
            raise invalid_request("Tier discount_cents_per_ton must be an integer")
        tiers.append({"up_to_pct": up_to, "discount_cents_per_ton": cpt})
    return tiers


@bp.post("/buying-points/discount-schedules")
def create_schedule():
    authenticate()
    data = json_body()
    code = req_str(data, "schedule_code")
    eff_from = req_datetime(data, "effective_from")
    eff_to = req_datetime(data, "effective_to")
    moisture_tiers = _parse_tiers(data, "moisture_tiers")
    fm_tiers = _parse_tiers(data, "foreign_material_tiers")
    damage_rate = req_int(data, "damage_rate_cents_per_pct", minimum=0)
    if not eff_from < eff_to:
        raise invalid_request("effective_from must be before effective_to")
    require_roles([ADMIN])
    s = new_common_fields()
    s.update({
        "schedule_code": code,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "moisture_tiers": moisture_tiers,
        "foreign_material_tiers": fm_tiers,
        "damage_rate_cents_per_pct": damage_rate,
        "status": "DRAFT",
    })
    store.discount_schedules[s["id"]] = s
    return success(ser_schedule(s), status=201)


@bp.get("/buying-points/discount-schedules/<s_id>")
def get_schedule(s_id):
    require_roles([ADMIN, INSPECTOR, CLERK])
    s = get_or_404(store.discount_schedules, s_id)
    return success(ser_schedule(s))


@bp.get("/buying-points/discount-schedules")
def list_schedules():
    require_roles([ADMIN, INSPECTOR, CLERK])
    from flask import request
    items = list(store.discount_schedules.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, ser_schedule)


@bp.post("/buying-points/discount-schedules/<s_id>/activate")
def activate_schedule(s_id):
    require_roles([ADMIN])
    s = get_or_404(store.discount_schedules, s_id)
    if s["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT schedule may be activated")
    # Half-open [from, to) overlap against every other ACTIVE schedule.
    for o in store.discount_schedules.values():
        if o["id"] == s["id"] or o["status"] != "ACTIVE":
            continue
        if s["effective_from"] < o["effective_to"] and o["effective_from"] < s["effective_to"]:
            raise err("ERR_SCHEDULE_WINDOW_OVERLAP", 409,
                      "Window overlaps another ACTIVE discount schedule")
    s["status"] = "ACTIVE"
    touch(s)
    return success(ser_schedule(s))


@bp.post("/buying-points/discount-schedules/<s_id>/retire")
def retire_schedule(s_id):
    require_roles([ADMIN])
    s = get_or_404(store.discount_schedules, s_id)
    if s["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE schedule may be retired")
    s["status"] = "RETIRED"
    touch(s)
    return success(ser_schedule(s))
