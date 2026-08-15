"""Load, Trip, CheckCall, FuelPurchase, AccessorialCharge, Invoice, Dispatch
endpoints."""
from flask import Blueprint, request

from common import (ApiError, require_role, get_body, ok, ok_list,
                    ok_array_raw, pagination, created_order, paged, req_str,
                    opt_str, req_int, opt_int, req_enum, req_dt, opt_dt,
                    ERR_INVALID, ERR_DRIVER_MISMATCH, ERR_STALE)
from store import store, now, init_common, init_telemetry, touch
import services as svc
from routes_fleet import (ALL, get_driver_or_404, get_tractor_or_404,
                          get_customer_or_404, get_lane_or_404)

bp = Blueprint("ops", __name__)

ACCESSORIAL_TYPES = ("DETENTION_PICKUP", "DETENTION_DELIVERY", "LAYOVER",
                     "LUMPER", "STOP_OFF")
CHECK_CALL_KINDS = ("ARRIVED_PICKUP", "DEPARTED_PICKUP", "EN_ROUTE",
                    "ARRIVED_DELIVERY", "DELIVERED")
TRIP_FUELABLE_STATES = ("DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_DELIVERY")
TRIP_CANCELLABLE_STATES = ("PLANNED", "DISPATCHED", "AT_PICKUP")
TRIP_NONTERMINAL = ("PLANNED", "DISPATCHED", "AT_PICKUP", "IN_TRANSIT",
                    "AT_DELIVERY")
LOAD_CANCELLABLE = ("TENDERED", "SCREENED", "ACCEPTED", "ASSIGNED",
                    "DISPATCHED")


def get_load_or_404(load_id):
    l = store.loads.get(load_id)
    if l is None:
        raise ApiError("ERR_LOAD_NOT_FOUND", 404, "Load id does not exist")
    return l


def get_trip_or_404(trip_id):
    t = store.trips.get(trip_id)
    if t is None:
        raise ApiError("ERR_TRIP_NOT_FOUND", 404, "Trip id does not exist")
    return t


def get_accessorial_or_404(acc_id):
    a = store.accessorials.get(acc_id)
    if a is None:
        raise ApiError("ERR_ACCESSORIAL_NOT_FOUND", 404,
                       "AccessorialCharge id does not exist")
    return a


def get_invoice_or_404(inv_id):
    i = store.invoices.get(inv_id)
    if i is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", 404, "Invoice id does not exist")
    return i


def driver_has_trip_on_load(load_id, driver_id):
    return any(t["load_id"] == load_id and t["driver_id"] == driver_id
               for t in store.trips.values())


def parse_route_states(b):
    rs = b.get("route_states")
    if rs is None:
        return []
    if not isinstance(rs, list):
        raise ApiError(ERR_INVALID, 400, "Field 'route_states' must be an array")
    out = []
    for i, seg in enumerate(rs):
        if not isinstance(seg, dict):
            raise ApiError(ERR_INVALID, 400,
                           f"route_states[{i}] must be an object")
        sc = seg.get("state_code")
        if not isinstance(sc, str) or sc == "":
            raise ApiError(ERR_INVALID, 400,
                           f"route_states[{i}].state_code must be a string")
        miles = seg.get("miles")
        if not (isinstance(miles, int) and not isinstance(miles, bool)) or miles < 0:
            raise ApiError(ERR_INVALID, 400,
                           f"route_states[{i}].miles must be an integer >= 0")
        out.append({"state_code": sc, "miles": miles})
    return out


def check_trip_gates(driver, load, lane, deadhead, exclude_trip_id=None):
    """Safety floor (8a) -> HOS feasibility (8b) -> home time (8c) -> overlap (9)."""
    if driver["safety_score"] < svc.SAFETY_ASSIGNMENT_MIN:
        raise ApiError("ERR_DRIVER_SAFETY_BELOW_FLOOR", 422,
                       "driver.safety_score is below the assignment floor of 60")
    if not svc.hos_feasible(driver["id"], lane, deadhead,
                            load["delivery_appt_at"]):
        raise ApiError("ERR_HOS_INSUFFICIENT", 422,
                       "Hours-of-service feasibility check failed")
    if not svc.home_time_ok(driver, load["delivery_appt_at"]):
        raise ApiError("ERR_HOME_TIME_EXCEEDED", 422,
                       "Projected days away from home exceed 14")


def check_trip_overlap(driver, load, planned_start_at, exclude_trip_id=None):
    new_start = planned_start_at
    new_end = load["delivery_appt_at"]
    for t in store.trips.values():
        if t["driver_id"] != driver["id"] or t["id"] == exclude_trip_id:
            continue
        if t["status"] not in TRIP_NONTERMINAL:
            continue
        other_load = store.loads[t["load_id"]]
        o_start = t["planned_start_at"]
        o_end = other_load["delivery_appt_at"]
        # Half-open windows: touching boundaries do not overlap.
        if new_start < o_end and o_start < new_end:
            raise ApiError("ERR_TRIP_OVERLAP", 422,
                           "Driver has a non-terminal trip whose window overlaps")


# ---------------------------------------------------------------------------
# Loads
# ---------------------------------------------------------------------------

@bp.post("/loads")
def create_load():
    require_role(["LoadPlanner"])
    b = get_body()
    customer_id = req_str(b, "customer_id")
    lane_id = req_str(b, "lane_id")
    rate = req_int(b, "rate_cents", min_v=1)
    weight = req_int(b, "weight_lbs", min_v=1)
    pickup = req_dt(b, "pickup_appt_at")
    delivery = req_dt(b, "delivery_appt_at")
    if delivery <= pickup:
        raise ApiError(ERR_INVALID, 400,
                       "delivery_appt_at must be strictly after pickup_appt_at")
    get_customer_or_404(customer_id)
    get_lane_or_404(lane_id)
    l = init_common({
        "customer_id": customer_id,
        "lane_id": lane_id,
        "rate_cents": rate,
        "weight_lbs": weight,
        "pickup_appt_at": pickup,
        "delivery_appt_at": delivery,
        "status": "TENDERED",
        "fuel_surcharge_cents": None,
        "projected_margin_cents": None,
        "projected_rpm_cents": None,
        "final_margin_cents": None,
        "total_accessorial_cents": 0,
        "cancellation_fee_cents": None,
        "reassignment_count": 0,
    })
    store.loads[l["id"]] = l
    return ok(l, 201)


@bp.get("/loads")
def list_loads():
    require_role(ALL)
    limit, offset = pagination()
    items = list(store.loads.values())
    status = request.args.get("status")
    customer_id = request.args.get("customer_id")
    lane_id = request.args.get("lane_id")
    if status:
        items = [l for l in items if l["status"] == status]
    if customer_id:
        items = [l for l in items if l["customer_id"] == customer_id]
    if lane_id:
        items = [l for l in items if l["lane_id"] == lane_id]
    items = created_order(items)
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/loads/<load_id>")
def get_load(load_id):
    require_role(ALL)
    return ok(get_load_or_404(load_id))


@bp.post("/loads/<load_id>/screen")
def screen_load(load_id):
    require_role(["LoadPlanner"])
    l = get_load_or_404(load_id)
    if l["status"] != "TENDERED":
        raise ApiError("ERR_LOAD_NOT_TENDERED", 409,
                       "Screen requires status TENDERED")
    lane = store.lanes[l["lane_id"]]
    fsc = svc.compute_fsc(lane)  # raises ERR_FUEL_RATE_UNAVAILABLE
    margin, rpm = svc.provisional_margin(l, lane, fsc)
    l["fuel_surcharge_cents"] = fsc
    l["projected_margin_cents"] = margin
    l["projected_rpm_cents"] = rpm
    l["status"] = "SCREENED"
    touch(l)
    return ok(l)


@bp.post("/loads/<load_id>/accept")
def accept_load(load_id):
    require_role(["LoadPlanner"])
    l = get_load_or_404(load_id)
    if l["status"] != "SCREENED":
        raise ApiError("ERR_LOAD_NOT_SCREENED", 409,
                       "Accept requires status SCREENED")
    lane = store.lanes[l["lane_id"]]
    # Recompute with the currently effective US-NATIONAL row (snapshot overwritten)
    fsc = svc.compute_fsc(lane)  # ERR_FUEL_RATE_UNAVAILABLE (stage 10)
    margin, rpm = svc.provisional_margin(l, lane, fsc)
    l["fuel_surcharge_cents"] = fsc
    l["projected_margin_cents"] = margin
    l["projected_rpm_cents"] = rpm
    # Fiscal gates in fixed sub-order: credit hold first, then margin floor.
    customer = store.customers[l["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD", 402,
                       "Accept requires the customer to be ACTIVE")
    if margin < 0 or rpm < lane["rpm_floor_cents"]:
        raise ApiError("ERR_MARGIN_BELOW_FLOOR", 402,
                       "Recomputed margin or RPM is below the lane floor")
    l["status"] = "ACCEPTED"
    touch(l)
    return ok(l)


@bp.post("/loads/<load_id>/reject")
def reject_load(load_id):
    require_role(["LoadPlanner"])
    l = get_load_or_404(load_id)
    if l["status"] not in ("TENDERED", "SCREENED"):
        raise ApiError("ERR_LOAD_NOT_REJECTABLE", 409,
                       "Reject requires status TENDERED or SCREENED")
    l["status"] = "REJECTED"
    touch(l)
    return ok(l)


@bp.post("/loads/<load_id>/cancel")
def cancel_load(load_id):
    require_role(["LoadPlanner"])
    l = get_load_or_404(load_id)
    if l["status"] not in LOAD_CANCELLABLE:
        raise ApiError("ERR_LOAD_NOT_CANCELLABLE", 409,
                       "Cancel allowed only from TENDERED/SCREENED/ACCEPTED/ASSIGNED/DISPATCHED")
    fee = svc.cancellation_fee(l)
    if l["status"] in ("ASSIGNED", "DISPATCHED"):
        for t in list(store.trips.values()):
            if t["load_id"] == l["id"] and t["status"] in TRIP_CANCELLABLE_STATES:
                svc.cancel_trip_cascade(t, "CUSTOMER", roll_back_load=False)
    l["status"] = "CANCELLED"
    l["cancellation_fee_cents"] = fee
    touch(l)
    return ok(l)


@bp.get("/loads/<load_id>/margin")
def load_margin(load_id):
    require_role(ALL)
    l = get_load_or_404(load_id)
    lane = store.lanes[l["lane_id"]]
    pm = l["projected_margin_cents"]
    pr = l["projected_rpm_cents"]
    floor_pass = (pm is not None and pr is not None and pm >= 0
                  and pr >= lane["rpm_floor_cents"])
    return ok({
        "projected_margin_cents": pm,
        "projected_rpm_cents": pr,
        "final_margin_cents": l["final_margin_cents"],
        "floor_pass": floor_pass,
    })


@bp.get("/loads/<load_id>/trips")
def list_load_trips(load_id):
    require_role(ALL)
    get_load_or_404(load_id)
    limit, offset = pagination()
    items = created_order([t for t in store.trips.values()
                           if t["load_id"] == load_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/loads/<load_id>/accessorials")
def list_load_accessorials(load_id):
    require_role(ALL)
    get_load_or_404(load_id)
    limit, offset = pagination()
    items = created_order([a for a in store.accessorials.values()
                           if a["load_id"] == load_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/loads/<load_id>/accessorials")
def create_accessorial(load_id):
    uid, role = require_role(["Dispatcher", "Driver"])
    l = get_load_or_404(load_id)
    b = get_body()
    charge_type = req_enum(b, "type", ACCESSORIAL_TYPES)
    quantity = req_int(b, "quantity", min_v=1)
    trip_id = opt_str(b, "trip_id")
    if trip_id is not None and trip_id not in store.trips:
        raise ApiError("ERR_TRIP_NOT_FOUND", 404, "Trip id does not exist")
    if role == "Driver" and not driver_has_trip_on_load(load_id, uid):
        raise ApiError(ERR_DRIVER_MISMATCH, 403,
                       "A Driver may capture accessorials only for loads with a trip they drive")
    if charge_type in ("DETENTION_PICKUP", "DETENTION_DELIVERY"):
        for a in store.accessorials.values():
            if (a["load_id"] == load_id and a["type"] == charge_type
                    and a["status"] != "REJECTED"):
                raise ApiError("ERR_DUPLICATE_ACCESSORIAL_TYPE", 422,
                               "A non-REJECTED detention charge of this leg already exists")
    a = init_common({
        "load_id": load_id,
        "trip_id": trip_id,
        "type": charge_type,
        "quantity": quantity,
        "amount_cents": svc.accessorial_amount(charge_type, quantity),
        "source": "MANUAL",
        "status": "PENDING",
    })
    store.accessorials[a["id"]] = a
    return ok(a, 201)


@bp.get("/loads/<load_id>/invoice")
def get_load_invoice(load_id):
    require_role(ALL)
    get_load_or_404(load_id)
    items = created_order([i for i in store.invoices.values()
                           if i["load_id"] == load_id and i["status"] != "VOID"])
    return ok_array_raw(items)


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------

@bp.post("/trips")
def create_trip():
    require_role(["Dispatcher"])
    b = get_body()
    load_id = req_str(b, "load_id")
    driver_id = req_str(b, "driver_id")
    tractor_id = req_str(b, "tractor_id")
    deadhead = req_int(b, "planned_deadhead_miles", min_v=0)
    planned_start = req_dt(b, "planned_start_at")
    route_states = parse_route_states(b)
    load = get_load_or_404(load_id)
    driver = get_driver_or_404(driver_id)
    tractor = get_tractor_or_404(tractor_id)
    if load["status"] != "ACCEPTED":
        raise ApiError("ERR_LOAD_NOT_ASSIGNABLE", 409,
                       "Trip create requires load status ACCEPTED")
    if tractor["status"] != "AVAILABLE":
        raise ApiError("ERR_TRACTOR_NOT_AVAILABLE", 409,
                       "Trip create requires tractor status AVAILABLE")
    lane = store.lanes[load["lane_id"]]
    check_trip_gates(driver, load, lane, deadhead)
    check_trip_overlap(driver, load, planned_start)
    t = init_common({
        "load_id": load_id,
        "driver_id": driver_id,
        "tractor_id": tractor_id,
        "planned_deadhead_miles": deadhead,
        "planned_start_at": planned_start,
        "route_states": route_states,
        "status": "PLANNED",
        "start_odometer_miles": None,
        "actual_miles": None,
        "pay_miles": None,
        "provisional_pay_cents": svc.provisional_pay(driver, load, lane, deadhead),
        "final_pay_cents": None,
        "cancel_reason": None,
        "completed_at": None,
    })
    store.trips[t["id"]] = t
    load["status"] = "ASSIGNED"
    touch(load)
    tractor["status"] = "ASSIGNED"
    touch(tractor)
    return ok(t, 201)


@bp.get("/trips")
def list_trips():
    require_role(ALL)
    limit, offset = pagination()
    items = list(store.trips.values())
    for param, field in (("driver_id", "driver_id"), ("tractor_id", "tractor_id"),
                         ("load_id", "load_id"), ("status", "status")):
        v = request.args.get(param)
        if v:
            items = [t for t in items if t[field] == v]
    items = created_order(items)
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/trips/<trip_id>")
def get_trip(trip_id):
    require_role(ALL)
    return ok(get_trip_or_404(trip_id))


@bp.patch("/trips/<trip_id>")
def replan_trip(trip_id):
    require_role(["Dispatcher"])
    t = get_trip_or_404(trip_id)
    b = get_body()
    expected = req_int(b, "expected_trip_version")
    deadhead = opt_int(b, "planned_deadhead_miles", min_v=0)
    planned_start = opt_dt(b, "planned_start_at")
    route_states = parse_route_states(b) if "route_states" in b else None
    if t["status"] != "PLANNED":
        raise ApiError("ERR_TRIP_NOT_PLANNED", 409,
                       "Replan requires trip status PLANNED")
    if expected != t["version"]:
        raise ApiError(ERR_STALE, 412,
                       "expected_trip_version does not match the current Trip version")
    new_deadhead = deadhead if deadhead is not None else t["planned_deadhead_miles"]
    new_start = planned_start if planned_start is not None else t["planned_start_at"]
    load = store.loads[t["load_id"]]
    lane = store.lanes[load["lane_id"]]
    driver = store.drivers[t["driver_id"]]
    check_trip_gates(driver, load, lane, new_deadhead)
    check_trip_overlap(driver, load, new_start, exclude_trip_id=t["id"])
    t["planned_deadhead_miles"] = new_deadhead
    t["planned_start_at"] = new_start
    if route_states is not None:
        t["route_states"] = route_states
    t["provisional_pay_cents"] = svc.provisional_pay(driver, load, lane, new_deadhead)
    touch(t)
    return ok(t)


@bp.post("/trips/<trip_id>/dispatch")
def dispatch_trip(trip_id):
    require_role(["Dispatcher"])
    t = get_trip_or_404(trip_id)
    if t["status"] != "PLANNED":
        raise ApiError("ERR_TRIP_NOT_PLANNED", 409,
                       "Dispatch requires trip status PLANNED")
    load = store.loads[t["load_id"]]
    if load["status"] != "ASSIGNED":
        raise ApiError("ERR_LOAD_NOT_ASSIGNABLE", 409,
                       "Dispatch requires load status ASSIGNED")
    driver = store.drivers[t["driver_id"]]
    if driver["employment_status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE", 409,
                       "Dispatch requires driver employment_status ACTIVE")
    tractor = store.tractors[t["tractor_id"]]
    t["start_odometer_miles"] = tractor["odometer_miles"]
    t["status"] = "DISPATCHED"
    touch(t)
    load["status"] = "DISPATCHED"
    touch(load)
    return ok(t)


@bp.post("/trips/<trip_id>/cancel")
def cancel_trip(trip_id):
    require_role(["Dispatcher"])
    t = get_trip_or_404(trip_id)
    b = get_body(required=False)
    reason = b.get("reason", "REASSIGN")
    if reason is None:
        reason = "REASSIGN"
    if reason not in ("REASSIGN", "CUSTOMER"):
        raise ApiError(ERR_INVALID, 400,
                       "Field 'reason' must be REASSIGN or CUSTOMER")
    if t["status"] not in TRIP_CANCELLABLE_STATES:
        raise ApiError("ERR_TRIP_NOT_CANCELLABLE", 409,
                       "Trip cancel allowed only from PLANNED/DISPATCHED/AT_PICKUP")
    svc.cancel_trip_cascade(t, reason, roll_back_load=True)
    return ok(t)


@bp.get("/trips/<trip_id>/eta")
def trip_eta(trip_id):
    require_role(ALL)
    t = get_trip_or_404(trip_id)
    load = store.loads[t["load_id"]]
    lane = store.lanes[load["lane_id"]]
    return ok(svc.eta_projection(t, load, lane))


@bp.get("/trips/<trip_id>/fuel-plan")
def trip_fuel_plan(trip_id):
    require_role(ALL)
    t = get_trip_or_404(trip_id)
    tractor = store.tractors[t["tractor_id"]]
    candidates = svc.fuel_plan(t, tractor)
    best = candidates[0]
    return ok({
        "recommended_state": best["state_code"],
        "effective_price_cents": best["effective_price_cents"],
        "candidates": candidates,
    })


@bp.get("/trips/<trip_id>/check-calls")
def list_check_calls(trip_id):
    require_role(ALL)
    get_trip_or_404(trip_id)
    limit, offset = pagination()
    items = created_order([c for c in store.check_calls.values()
                           if c["trip_id"] == trip_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/trips/<trip_id>/check-calls")
def create_check_call(trip_id):
    uid, role = require_role(["Driver", "Dispatcher"])
    t = get_trip_or_404(trip_id)
    b = get_body()
    kind = req_enum(b, "kind", CHECK_CALL_KINDS)
    occurred_at = req_dt(b, "occurred_at")
    if occurred_at > now():
        raise ApiError(ERR_INVALID, 400,
                       "occurred_at must not be after the logical now")
    state_code = req_str(b, "state_code")
    odometer = req_int(b, "odometer_miles")
    if role == "Driver" and uid != t["driver_id"]:
        raise ApiError(ERR_DRIVER_MISMATCH, 403,
                       "A Driver may record check calls only on their own trips")
    prev = sorted((c for c in store.check_calls.values()
                   if c["trip_id"] == trip_id),
                  key=lambda c: (c["occurred_at"], c["_seq"]))

    def out_of_order(msg):
        raise ApiError("ERR_CHECK_CALL_OUT_OF_ORDER", 422, msg)

    if t["status"] in ("PLANNED", "COMPLETED", "CANCELLED"):
        out_of_order("Check calls are not allowed on a PLANNED or terminal trip")
    if kind == "EN_ROUTE":
        if t["status"] not in ("DISPATCHED", "IN_TRANSIT"):
            out_of_order("EN_ROUTE is allowed only while DISPATCHED or IN_TRANSIT")
    else:
        rank = svc.CHECK_CALL_RANK[kind]
        prev_rank = max((svc.CHECK_CALL_RANK[c["kind"]] for c in prev
                         if c["kind"] != "EN_ROUTE"), default=0)
        if rank <= prev_rank:
            out_of_order("Check-call milestone rank must advance")
    if prev:
        last = prev[-1]
        if occurred_at < last["occurred_at"]:
            out_of_order("occurred_at must not precede the previous check call")
        if odometer < last["odometer_miles"]:
            out_of_order("odometer_miles must not regress below the previous check call")
    else:
        if t["start_odometer_miles"] is not None and odometer < t["start_odometer_miles"]:
            out_of_order("First check-call odometer must be >= trip start odometer")
    cc = init_telemetry({
        "trip_id": trip_id,
        "kind": kind,
        "occurred_at": occurred_at,
        "state_code": state_code,
        "odometer_miles": odometer,
    })
    store.check_calls[cc["id"]] = cc
    load = store.loads[t["load_id"]]
    if kind == "ARRIVED_PICKUP":
        t["status"] = "AT_PICKUP"
        touch(t)
    elif kind == "DEPARTED_PICKUP":
        t["status"] = "IN_TRANSIT"
        touch(t)
        load["status"] = "IN_TRANSIT"
        touch(load)
    elif kind == "ARRIVED_DELIVERY":
        t["status"] = "AT_DELIVERY"
        touch(t)
    elif kind == "DELIVERED":
        svc.complete_trip(t, cc)
    return ok(cc, 201)


@bp.get("/trips/<trip_id>/duty-events")
def list_trip_duty_events(trip_id):
    require_role(ALL)
    get_trip_or_404(trip_id)
    limit, offset = pagination()
    items = [e for e in store.duty_events.values() if e["trip_id"] == trip_id]
    items.sort(key=lambda e: (e["occurred_at"], e["_seq"]))
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/trips/<trip_id>/accessorials")
def list_trip_accessorials(trip_id):
    require_role(ALL)
    get_trip_or_404(trip_id)
    limit, offset = pagination()
    items = created_order([a for a in store.accessorials.values()
                           if a["trip_id"] == trip_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/trips/<trip_id>/fuel-purchases")
def create_fuel_purchase(trip_id):
    uid, role = require_role(["Driver", "Dispatcher"])
    t = get_trip_or_404(trip_id)
    b = get_body()
    driver_id = req_str(b, "driver_id")
    state_code = req_str(b, "state_code")
    gallons = req_int(b, "gallons", min_v=1)
    pump_price = req_int(b, "pump_price_cents", min_v=1)
    purchased_at = req_dt(b, "purchased_at")
    if purchased_at > now():
        raise ApiError(ERR_INVALID, 400,
                       "purchased_at must not be after the logical now")
    if role == "Driver" and uid != driver_id:
        raise ApiError(ERR_DRIVER_MISMATCH, 403,
                       "driver_id must equal X-User-ID for Driver callers")
    if driver_id != t["driver_id"]:
        raise ApiError(ERR_DRIVER_MISMATCH, 403,
                       "driver_id must equal the trip's driver")
    if t["status"] not in TRIP_FUELABLE_STATES:
        raise ApiError("ERR_TRIP_NOT_FUELABLE", 409,
                       "Fuel purchase requires trip DISPATCHED through AT_DELIVERY")
    route_states = [seg["state_code"] for seg in (t["route_states"] or [])]
    if state_code not in route_states:
        raise ApiError("ERR_STATE_NOT_ON_ROUTE", 422,
                       "Purchase state_code is not on the trip's route")
    tractor = store.tractors[t["tractor_id"]]
    if tractor["current_fuel_gallons"] + gallons > tractor["tank_capacity_gallons"]:
        raise ApiError("ERR_TANK_CAPACITY_EXCEEDED", 422,
                       "Purchase would exceed the tractor's tank capacity")
    rate = svc.current_fuel_rate(state_code)
    if rate is None:
        raise ApiError("ERR_FUEL_RATE_UNAVAILABLE", 422,
                       "No currently effective StateFuelRate row for this state_code")
    p = init_common({
        "trip_id": trip_id,
        "driver_id": driver_id,
        "state_code": state_code,
        "gallons": gallons,
        "pump_price_cents": pump_price,
        "purchased_at": purchased_at,
        "total_cost_cents": gallons * pump_price,
        "tax_paid_cents": gallons * rate["tax_cents_per_gallon"],
        "net_effective_price_cents": pump_price - rate["tax_cents_per_gallon"],
    })
    store.fuel_purchases[p["id"]] = p
    tractor["current_fuel_gallons"] += gallons
    touch(tractor)
    return ok(p, 201)


@bp.get("/trips/<trip_id>/fuel-purchases")
def list_trip_fuel_purchases(trip_id):
    require_role(ALL)
    get_trip_or_404(trip_id)
    limit, offset = pagination()
    items = created_order([p for p in store.fuel_purchases.values()
                           if p["trip_id"] == trip_id])
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Accessorial adjudication
# ---------------------------------------------------------------------------

@bp.get("/accessorials/<acc_id>")
def get_accessorial(acc_id):
    require_role(ALL)
    return ok(get_accessorial_or_404(acc_id))


@bp.post("/accessorials/<acc_id>/submit")
def submit_accessorial(acc_id):
    uid, role = require_role(["Dispatcher", "Driver"])
    a = get_accessorial_or_404(acc_id)
    if role == "Driver" and not driver_has_trip_on_load(a["load_id"], uid):
        raise ApiError(ERR_DRIVER_MISMATCH, 403,
                       "A Driver may submit accessorials only for loads with a trip they drive")
    if a["status"] not in ("PENDING", "DISPUTED"):
        raise ApiError("ERR_ACCESSORIAL_NOT_SUBMITTABLE", 409,
                       "Submit requires status PENDING or DISPUTED")
    a["status"] = "SUBMITTED"
    touch(a)
    return ok(a)


@bp.post("/accessorials/<acc_id>/approve")
def approve_accessorial(acc_id):
    require_role(["LoadPlanner"])
    a = get_accessorial_or_404(acc_id)
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_ACCESSORIAL_NOT_APPROVABLE", 409,
                       "Approve requires status SUBMITTED")
    a["status"] = "APPROVED"
    touch(a)
    return ok(a)


@bp.post("/accessorials/<acc_id>/dispute")
def dispute_accessorial(acc_id):
    require_role(["LoadPlanner"])
    a = get_accessorial_or_404(acc_id)
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_ACCESSORIAL_NOT_DISPUTABLE", 409,
                       "Dispute requires status SUBMITTED")
    a["status"] = "DISPUTED"
    touch(a)
    return ok(a)


@bp.post("/accessorials/<acc_id>/reject")
def reject_accessorial(acc_id):
    require_role(["LoadPlanner"])
    a = get_accessorial_or_404(acc_id)
    if a["status"] not in ("SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_ACCESSORIAL_NOT_REJECTABLE", 409,
                       "Reject requires status SUBMITTED or DISPUTED")
    a["status"] = "REJECTED"
    touch(a)
    return ok(a)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.post("/loads/<load_id>/invoice")
def create_invoice(load_id):
    require_role(["LoadPlanner"])
    l = get_load_or_404(load_id)
    get_body(required=False)
    if l["status"] != "DELIVERED":
        raise ApiError("ERR_INVOICE_NOT_ISSUABLE", 409,
                       "Invoice create requires load status DELIVERED")
    for i in store.invoices.values():
        if i["load_id"] == load_id and i["status"] != "VOID":
            raise ApiError("ERR_INVOICE_ALREADY_EXISTS", 409,
                           "A non-VOID invoice already exists for this load")
    inv = init_common({
        "load_id": load_id,
        "status": "DRAFT",
        "linehaul_cents": l["rate_cents"],
        "fuel_surcharge_cents": l["fuel_surcharge_cents"],
        "accessorial_total_cents": 0,
        "total_cents": l["rate_cents"] + (l["fuel_surcharge_cents"] or 0),
    })
    store.invoices[inv["id"]] = inv
    return ok(inv, 201)


@bp.get("/invoices/<inv_id>")
def get_invoice(inv_id):
    require_role(ALL)
    return ok(get_invoice_or_404(inv_id))


@bp.post("/invoices/<inv_id>/issue")
def issue_invoice(inv_id):
    require_role(["LoadPlanner"])
    inv = get_invoice_or_404(inv_id)
    load = store.loads[inv["load_id"]]
    if inv["status"] != "DRAFT" or load["status"] != "DELIVERED":
        raise ApiError("ERR_INVOICE_NOT_ISSUABLE", 409,
                       "Issue requires invoice DRAFT and load DELIVERED")
    for a in store.accessorials.values():
        if (a["load_id"] == load["id"]
                and a["status"] in ("PENDING", "SUBMITTED", "DISPUTED")):
            raise ApiError("ERR_INVOICE_OPEN_ACCESSORIALS", 422,
                           "Issue blocked: an accessorial of the load is still open")
    svc.issue_invoice_cascade(inv)
    return ok(inv)


@bp.post("/invoices/<inv_id>/void")
def void_invoice(inv_id):
    require_role(["LoadPlanner"])
    inv = get_invoice_or_404(inv_id)
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_VOIDABLE", 409,
                       "Void requires invoice status ISSUED")
    svc.void_invoice_cascade(inv)
    return ok(inv)


@bp.post("/invoices/<inv_id>/mark-paid")
def mark_invoice_paid(inv_id):
    require_role(["LoadPlanner"])
    inv = get_invoice_or_404(inv_id)
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", 409,
                       "Mark-paid requires invoice status ISSUED")
    inv["status"] = "PAID"
    touch(inv)
    load = store.loads[inv["load_id"]]
    load["status"] = "CLOSED"
    touch(load)
    return ok(inv)


# ---------------------------------------------------------------------------
# Dispatch backhaul board
# ---------------------------------------------------------------------------

@bp.get("/dispatch/backhaul-candidates")
def backhaul():
    require_role(["Dispatcher"])
    tractor_id = request.args.get("tractor_id")
    if not tractor_id:
        raise ApiError(ERR_INVALID, 400,
                       "Query parameter 'tractor_id' is required")
    driver_id = request.args.get("driver_id")
    limit, offset = pagination()
    tractor = get_tractor_or_404(tractor_id)
    driver = None
    if driver_id:
        driver = get_driver_or_404(driver_id)
    items = svc.backhaul_candidates(tractor, driver)
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)
