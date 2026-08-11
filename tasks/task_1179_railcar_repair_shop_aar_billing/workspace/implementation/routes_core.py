"""Clock, shop configuration, party registries, price master, parts,
wheelsets, and shop slots."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, g

import db
from errors import ApiError
from common import (
    auth, ok, get_body, req_str, opt_str, req_int, opt_int, req_num, req_bool,
    opt_bool, invalid_request, base_fields, touch, get_or_404, ref_or_404,
    public, sort_items, list_response, iso, now, now_iso, parse_dt, parse_date,
    shop_out, car_owner_out, car_owner_status, part_out, part_status,
)
import billing_ops

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Test-driving logical clock (PRD 2.4)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@auth("ShopAdmin")
def set_clock():
    body = get_body()
    raw = req_str(body, "to_iso8601")
    try:
        target = parse_dt(raw)
    except (ValueError, TypeError):
        raise invalid_request("to_iso8601 must be an ISO 8601 timestamp")
    db.clock_set(target)
    return ok({"current_utc": iso(db.clock_now())}, code=200)


# ---------------------------------------------------------------------------
# Shops
# ---------------------------------------------------------------------------

@bp.post("/shops")
@auth("ShopAdmin")
def create_shop():
    body = get_body()
    name = req_str(body, "name")
    stalls = req_int(body, "stalls")
    dwell_rate = req_int(body, "dwell_rate_cents_per_hour")
    shop = base_fields()
    shop.update({
        "name": name,
        "stalls": stalls,
        "stall_daily_hours": opt_int(body, "stall_daily_hours", 8),
        "dwell_free_hours": opt_int(body, "dwell_free_hours", 48),
        "dwell_rate_cents_per_hour": dwell_rate,
        "warranty_days": opt_int(body, "warranty_days", 90),
        "counter_window_days": opt_int(body, "counter_window_days", 30),
        "owner_watch_threshold_cents": opt_int(body, "owner_watch_threshold_cents", 1000000),
    })
    db.STORE["shops"][shop["id"]] = shop
    return ok(shop_out(shop), code=201)


@bp.get("/shops/<sid>")
@auth("Any")
def get_shop(sid):
    shop = get_or_404("shops", sid, "Shop")
    return ok(shop_out(shop))


@bp.post("/shops/<sid>/sweep")
@auth("ShopAdmin")
def sweep_shop(sid):
    """PRD 2.4: counter-bill expiry first, then deemed BRC acceptance."""
    shop = get_or_404("shops", sid, "Shop")
    n = now()

    def brc_shop_id(brc):
        wo = db.STORE["work_orders"].get(brc["work_order_id"])
        if wo is None:
            return None
        rc = db.STORE["railcars"].get(wo["railcar_id"])
        return rc["shop_id"] if rc else None

    # 1) Counter-bill expiry: active counters past dispute window + grace.
    for cb in sorted([c for c in db.STORE["counter_bills"].values()
                      if c["status"] in ("OPEN", "REBUTTED")],
                     key=lambda c: c["_seq"]):
        brc = db.STORE["brcs"].get(cb["brc_id"])
        if brc is None or brc_shop_id(brc) != shop["id"]:
            continue
        if brc["dispute_window_ends_at"] is None:
            continue
        expiry = parse_dt(brc["dispute_window_ends_at"]) + timedelta(
            days=shop["counter_window_days"])
        if n > expiry:
            cb["status"] = "EXPIRED"
            touch(cb)
            billing_ops.maybe_resolve_disputed_brc(brc)

    # 2) Deemed acceptance: SUBMITTED past the dispute window, no active
    #    counters -> ACCEPTED, posting balances as a manual accept would.
    for brc in sorted([b for b in db.STORE["brcs"].values()
                       if b["status"] == "SUBMITTED"], key=lambda b: b["_seq"]):
        if brc_shop_id(brc) != shop["id"]:
            continue
        if brc["dispute_window_ends_at"] is None:
            continue
        if n > parse_dt(brc["dispute_window_ends_at"]) and not billing_ops.active_counters(brc["id"]):
            brc["status"] = "ACCEPTED"
            billing_ops.post_balances(brc, +1)
            touch(brc)

    return ok(shop_out(shop))


# ---------------------------------------------------------------------------
# Car owners / handling lines
# ---------------------------------------------------------------------------

@bp.post("/car-owners")
@auth("ShopAdmin")
def create_car_owner():
    body = get_body()
    shop = ref_or_404("shops", req_str(body, "shop_id"), "Shop")
    owner = base_fields()
    owner.update({
        "shop_id": shop["id"],
        "name": req_str(body, "name"),
        "scac_code": req_str(body, "scac_code"),
        "outstanding_balance_cents": 0,
    })
    db.STORE["car_owners"][owner["id"]] = owner
    return ok(car_owner_out(owner), code=201)


@bp.get("/car-owners")
@auth("Any")
def list_car_owners():
    items = list(db.STORE["car_owners"].values())
    shop_id = request_arg("shop_id")
    status = request_arg("status")
    if shop_id is not None:
        items = [o for o in items if o["shop_id"] == shop_id]
    if status is not None:
        items = [o for o in items if car_owner_status(o) == status]
    return list_response([car_owner_out(o) for o in sort_items(items)])


@bp.get("/car-owners/<oid>")
@auth("Any")
def get_car_owner(oid):
    return ok(car_owner_out(get_or_404("car_owners", oid, "CarOwner")))


@bp.post("/handling-lines")
@auth("ShopAdmin")
def create_handling_line():
    body = get_body()
    shop = ref_or_404("shops", req_str(body, "shop_id"), "Shop")
    line = base_fields()
    line.update({
        "shop_id": shop["id"],
        "name": req_str(body, "name"),
        "mark": req_str(body, "mark"),
        "outstanding_balance_cents": 0,
    })
    db.STORE["handling_lines"][line["id"]] = line
    return ok(public(line), code=201)


@bp.get("/handling-lines")
@auth("Any")
def list_handling_lines():
    items = list(db.STORE["handling_lines"].values())
    shop_id = request_arg("shop_id")
    if shop_id is not None:
        items = [l for l in items if l["shop_id"] == shop_id]
    return list_response([public(l) for l in sort_items(items)])


@bp.get("/handling-lines/<hid>")
@auth("Any")
def get_handling_line(hid):
    return ok(public(get_or_404("handling_lines", hid, "HandlingLine")))


def request_arg(name):
    from flask import request
    return request.args.get(name)


# ---------------------------------------------------------------------------
# Price master (PRD 2.6)
# ---------------------------------------------------------------------------

@bp.post("/price-master-entries")
@auth("ShopAdmin")
def create_price_entry():
    body = get_body()
    shop = ref_or_404("shops", req_str(body, "shop_id"), "Shop")
    job_code = req_str(body, "job_code")
    eff_from_raw = req_str(body, "effective_from")
    eff_to_raw = req_str(body, "effective_to")
    try:
        eff_from = parse_date(eff_from_raw)
        eff_to = parse_date(eff_to_raw)
    except (ValueError, TypeError):
        raise invalid_request("effective_from / effective_to must be YYYY-MM-DD dates")
    if eff_to < eff_from:
        raise invalid_request("effective_to must not precede effective_from")
    for e in db.STORE["price_entries"].values():
        if e["shop_id"] == shop["id"] and e["job_code"] == job_code:
            if eff_from.isoformat() <= e["effective_to"] and e["effective_from"] <= eff_to.isoformat():
                raise ApiError("ERR_PRICE_WINDOW_OVERLAP", 409,
                               "Effective window overlaps an existing entry for this job_code")
    entry = base_fields()
    entry.update({
        "shop_id": shop["id"],
        "job_code": job_code,
        "description": req_str(body, "description"),
        "labor_rate_cents_per_hour": req_int(body, "labor_rate_cents_per_hour"),
        "mobile_labor_rate_cents_per_hour": req_int(body, "mobile_labor_rate_cents_per_hour"),
        "standard_labor_hours": req_num(body, "standard_labor_hours"),
        "mobile_trip_surcharge_cents": req_int(body, "mobile_trip_surcharge_cents"),
        "mobile_eligible": req_bool(body, "mobile_eligible"),
        "shared_split": opt_bool(body, "shared_split", False),
        "effective_from": eff_from.isoformat(),
        "effective_to": eff_to.isoformat(),
    })
    db.STORE["price_entries"][entry["id"]] = entry
    return ok(public(entry), code=201)


@bp.get("/price-master-entries")
@auth("Any")
def list_price_entries():
    items = list(db.STORE["price_entries"].values())
    shop_id = request_arg("shop_id")
    job_code = request_arg("job_code")
    if shop_id is not None:
        items = [e for e in items if e["shop_id"] == shop_id]
    if job_code is not None:
        items = [e for e in items if e["job_code"] == job_code]
    return list_response([public(e) for e in sort_items(items)])


@bp.get("/price-master-entries/<eid>")
@auth("Any")
def get_price_entry(eid):
    return ok(public(get_or_404("price_entries", eid, "PriceMasterEntry")))


# ---------------------------------------------------------------------------
# Parts (PRD 2.9)
# ---------------------------------------------------------------------------

@bp.post("/parts")
@auth("ShopAdmin")
def create_part():
    body = get_body()
    shop = ref_or_404("shops", req_str(body, "shop_id"), "Shop")
    part_number = req_str(body, "part_number")
    for p in db.STORE["parts"].values():
        if p["shop_id"] == shop["id"] and p["part_number"] == part_number:
            raise ApiError("ERR_DUPLICATE_PART_NUMBER", 409,
                           "part_number already exists within the shop")
    part = base_fields()
    part.update({
        "shop_id": shop["id"],
        "part_number": part_number,
        "description": req_str(body, "description"),
        "unit_price_cents": req_int(body, "unit_price_cents"),
        "on_hand_qty": req_int(body, "on_hand_qty"),
        "reserved_qty": 0,
        "reorder_threshold": req_int(body, "reorder_threshold"),
    })
    db.STORE["parts"][part["id"]] = part
    return ok(part_out(part), code=201)


@bp.get("/parts")
@auth("Any")
def list_parts():
    items = list(db.STORE["parts"].values())
    shop_id = request_arg("shop_id")
    status = request_arg("status")
    if shop_id is not None:
        items = [p for p in items if p["shop_id"] == shop_id]
    if status is not None:
        items = [p for p in items if part_status(p) == status]
    return list_response([part_out(p) for p in sort_items(items)])


@bp.get("/parts/<pid>")
@auth("Any")
def get_part(pid):
    return ok(part_out(get_or_404("parts", pid, "PartItem")))


@bp.post("/parts/<pid>/adjust")
@auth("PartsClerk")
def adjust_part(pid):
    part = get_or_404("parts", pid, "PartItem")
    body = get_body()
    delta = req_int(body, "delta_qty")
    if delta == 0:
        raise invalid_request("delta_qty must be non-zero")
    req_str(body, "reason")
    new_on_hand = part["on_hand_qty"] + delta
    if new_on_hand < part["reserved_qty"]:
        raise ApiError("ERR_PART_STOCK_INSUFFICIENT", 409,
                       "Adjustment would drop on_hand_qty below reserved_qty")
    part["on_hand_qty"] = new_on_hand
    touch(part)
    return ok(part_out(part))


# ---------------------------------------------------------------------------
# Wheelsets (PRD 3.6)
# ---------------------------------------------------------------------------

def q3(v):
    return float(Decimal(str(v)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def wheelset_out(w):
    return public(w)


@bp.post("/wheelsets")
@auth("PartsClerk")
def create_wheelset():
    body = get_body()
    shop = ref_or_404("shops", req_str(body, "shop_id"), "Shop")
    serial = req_str(body, "serial_number")
    for w in db.STORE["wheelsets"].values():
        if w["shop_id"] == shop["id"] and w["serial_number"] == serial:
            raise ApiError("ERR_DUPLICATE_WHEELSET_SERIAL", 409,
                           "serial_number already exists within the shop")
    ws = base_fields()
    ws.update({
        "shop_id": shop["id"],
        "serial_number": serial,
        "flange_thickness_mm": q3(req_num(body, "flange_thickness_mm")),
        "tread_wear_mm": q3(req_num(body, "tread_wear_mm")),
        "status": "IN_STOCK",
        "mounted_railcar_id": None,
    })
    db.STORE["wheelsets"][ws["id"]] = ws
    return ok(wheelset_out(ws), code=201)


@bp.get("/wheelsets")
@auth("Any")
def list_wheelsets():
    items = list(db.STORE["wheelsets"].values())
    shop_id = request_arg("shop_id")
    status = request_arg("status")
    mounted = request_arg("mounted_railcar_id")
    if shop_id is not None:
        items = [w for w in items if w["shop_id"] == shop_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    if mounted is not None:
        items = [w for w in items if w["mounted_railcar_id"] == mounted]
    return list_response([wheelset_out(w) for w in sort_items(items)])


@bp.get("/wheelsets/<wid>")
@auth("Any")
def get_wheelset(wid):
    return ok(wheelset_out(get_or_404("wheelsets", wid, "Wheelset")))


@bp.post("/wheelsets/<wid>/mount")
@auth("RepairForeman")
def mount_wheelset(wid):
    ws = get_or_404("wheelsets", wid, "Wheelset")
    body = get_body()
    railcar = ref_or_404("railcars", req_str(body, "railcar_id"), "Railcar")
    if ws["status"] != "IN_STOCK":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an IN_STOCK wheelset can be mounted")
    if railcar["status"] != "IN_SHOP":
        raise ApiError("ERR_CAR_NOT_IN_SHOP", 409,
                       "Wheelset mount requires the railcar to be IN_SHOP")
    ws["status"] = "MOUNTED"
    ws["mounted_railcar_id"] = railcar["id"]
    touch(ws)
    return ok(wheelset_out(ws))


@bp.post("/wheelsets/<wid>/remove")
@auth("RepairForeman")
def remove_wheelset(wid):
    ws = get_or_404("wheelsets", wid, "Wheelset")
    get_body(required=False)
    if ws["status"] != "MOUNTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a MOUNTED wheelset can be removed")
    ws["status"] = "REMOVED"
    ws["mounted_railcar_id"] = None
    touch(ws)
    return ok(wheelset_out(ws))


@bp.post("/wheelsets/<wid>/evaluate")
@auth("QualityInspector")
def evaluate_wheelset(wid):
    ws = get_or_404("wheelsets", wid, "Wheelset")
    body = get_body()
    flange = Decimal(str(req_num(body, "flange_thickness_mm"))).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP)
    tread = Decimal(str(req_num(body, "tread_wear_mm"))).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP)
    if ws["status"] not in ("REMOVED", "IN_STOCK"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only REMOVED or IN_STOCK wheelsets can be evaluated")
    ws["flange_thickness_mm"] = float(flange)
    ws["tread_wear_mm"] = float(tread)
    condemned = flange <= Decimal("28.0") or tread >= Decimal("9.5")
    if condemned:
        ws["status"] = "CONDEMNED"
        ws["mounted_railcar_id"] = None
    elif ws["status"] == "REMOVED":
        ws["status"] = "IN_STOCK"
    touch(ws)
    return ok(wheelset_out(ws))


# ---------------------------------------------------------------------------
# Shop slots (PRD 3.1)
# ---------------------------------------------------------------------------

def slot_out(s):
    return public(s)


@bp.post("/shop-slots")
@auth("ShopAdmin")
def create_slot():
    body = get_body()
    shop = ref_or_404("shops", req_str(body, "shop_id"), "Shop")
    stall_id = req_str(body, "stall_id")
    try:
        starts = parse_dt(req_str(body, "starts_at"))
        ends = parse_dt(req_str(body, "ends_at"))
    except (ValueError, TypeError):
        raise invalid_request("starts_at / ends_at must be ISO 8601 timestamps")
    if ends <= starts:
        raise invalid_request("ends_at must be after starts_at")
    if ends <= now():
        raise ApiError("ERR_SLOT_IN_PAST", 409,
                       "Slot window ends at or before the current logical time")
    slot = base_fields()
    slot.update({
        "shop_id": shop["id"],
        "stall_id": stall_id,
        "starts_at": iso(starts),
        "ends_at": iso(ends),
        "status": "OPEN",
        "reserved_work_order_id": None,
    })
    db.STORE["shop_slots"][slot["id"]] = slot
    return ok(slot_out(slot), code=201)


@bp.get("/shop-slots")
@auth("Any")
def list_slots():
    items = list(db.STORE["shop_slots"].values())
    for name in ("shop_id", "stall_id", "status", "reserved_work_order_id"):
        v = request_arg(name)
        if v is not None:
            items = [s for s in items if s[name] == v]
    return list_response([slot_out(s) for s in sort_items(items)])


@bp.get("/shop-slots/<sid>")
@auth("Any")
def get_slot(sid):
    return ok(slot_out(get_or_404("shop_slots", sid, "ShopSlot")))


@bp.post("/shop-slots/<sid>/block")
@auth("ShopAdmin")
def block_slot(sid):
    slot = get_or_404("shop_slots", sid, "ShopSlot")
    get_body(required=False)
    if slot["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an OPEN slot can be blocked")
    slot["status"] = "BLOCKED"
    touch(slot)
    return ok(slot_out(slot))
