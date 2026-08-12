"""Endpoints: delivery routes, deliveries + cold chain, reauthorizations,
outcome assessments, claims."""
from datetime import date, timedelta

from flask import Blueprint, request

import db
from db import store
from util import (ApiError, ALL_ROLES, authenticate, get_body,
                  f_str, f_int, f_number, f_enum, f_date, f_time, f_datetime,
                  envelope_ok, paginated, pub, not_found, invalid_request)
import domain
from domain import bump, reauth_view

bp = Blueprint("ops", __name__)


# ---------------------------------------------------------------------------
# Delivery routes
# ---------------------------------------------------------------------------

def _hhmm_to_min(t):
    return int(t[0:2]) * 60 + int(t[3:5])


@bp.post("/mtm/delivery-routes")
def create_route():
    authenticate(["LogisticsCoordinator"])
    body = get_body()
    driver_id = f_str(body, "driver_id")
    route_date = f_date(body, "route_date")
    start_time = f_time(body, "start_time")
    end_time = f_time(body, "end_time")
    capacity = f_int(body, "capacity_stops", min_val=1)
    if _hhmm_to_min(end_time) <= _hhmm_to_min(start_time):
        invalid_request("end_time must be strictly after start_time")
    s1, e1 = _hhmm_to_min(start_time), _hhmm_to_min(end_time)
    for r in store["routes"].values():
        if (r["driver_id"] == driver_id and r["route_date"] == route_date
                and r["status"] in ("PLANNED", "DISPATCHED")):
            s2, e2 = _hhmm_to_min(r["start_time"]), _hhmm_to_min(r["end_time"])
            if s1 < e2 and s2 < e1:  # half-open [start, end) overlap
                raise ApiError("ERR_ROUTE_WINDOW_OVERLAP", 409,
                               "Same driver has a non-terminal overlapping route window")
    ts = db.now_iso()
    r = {
        "id": db.new_id(), "driver_id": driver_id, "route_date": route_date,
        "start_time": start_time, "end_time": end_time,
        "capacity_stops": capacity, "status": "PLANNED",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["routes"][r["id"]] = r
    return envelope_ok(pub(r), "object", 201)


@bp.get("/mtm/delivery-routes")
def list_routes():
    authenticate(ALL_ROLES)
    items = sorted(store["routes"].values(), key=lambda r: r["created_at"])
    for param, field in (("driver_id", "driver_id"),
                         ("route_date", "route_date"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    return paginated([pub(r) for r in items])


def _get_route(rid):
    r = store["routes"].get(rid)
    if r is None:
        not_found("Delivery route not found")
    return r


@bp.get("/mtm/delivery-routes/<rid>")
def get_route(rid):
    authenticate(ALL_ROLES)
    return envelope_ok(pub(_get_route(rid)), "object", 200)


@bp.post("/mtm/delivery-routes/<rid>/dispatch")
def dispatch_route(rid):
    authenticate(["LogisticsCoordinator"])
    r = _get_route(rid)
    if r["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Route must be PLANNED to dispatch")
    r["status"] = "DISPATCHED"
    bump(r)
    return envelope_ok(pub(r), "object", 200)


@bp.post("/mtm/delivery-routes/<rid>/complete")
def complete_route(rid):
    authenticate(["LogisticsCoordinator"])
    r = _get_route(rid)
    if r["status"] != "DISPATCHED":
        raise ApiError("ERR_ROUTE_NOT_DISPATCHED", 409,
                       "Route must be DISPATCHED to complete")
    open_ds = [d for d in store["deliveries"].values()
               if d["route_id"] == rid
               and d["status"] not in domain.DELIVERY_TERMINAL]
    if open_ds:
        raise ApiError("ERR_ROUTE_HAS_OPEN_DELIVERIES", 409,
                       "Route completion blocked by non-terminal deliveries")
    r["status"] = "COMPLETED"
    bump(r)
    return envelope_ok(pub(r), "object", 200)


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------

@bp.post("/mtm/deliveries")
def schedule_delivery():
    authenticate(["LogisticsCoordinator"])
    body = get_body()
    member_id = f_str(body, "member_id")
    menu_cycle_id = f_str(body, "menu_cycle_id")
    route_id = f_str(body, "route_id")
    service_date = f_date(body, "service_date")
    if member_id not in store["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member_id does not exist")
    c = store["menu_cycles"].get(menu_cycle_id)
    if c is None:
        raise ApiError("ERR_MENU_CYCLE_NOT_FOUND", 404,
                       "menu_cycle_id does not exist")
    r = store["routes"].get(route_id)
    if r is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND", 404, "route_id does not exist")
    if c["status"] != "FROZEN":
        raise ApiError("ERR_MENU_CYCLE_NOT_FROZEN", 409,
                       "Menu cycle must be FROZEN to schedule a delivery")
    if r["status"] not in ("PLANNED", "DISPATCHED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Route must be PLANNED or DISPATCHED to schedule")
    if service_date != r["route_date"]:
        raise ApiError("ERR_ROUTE_DATE_MISMATCH", 422,
                       "Delivery service_date must equal the route's route_date")
    auth = domain.select_authorization(member_id, service_date)
    auth["reserved_units"] += 1
    bump(auth)
    ts = db.now_iso()
    d = {
        "id": db.new_id(), "member_id": member_id, "menu_cycle_id": menu_cycle_id,
        "route_id": route_id, "authorization_id": auth["id"],
        "service_date": service_date, "status": "SCHEDULED",
        "cold_chain_status": "INTACT", "cumulative_excursion_minutes": 0,
        "delivered_at": None, "confirmed_at": None,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["deliveries"][d["id"]] = d
    return envelope_ok(pub(d), "object", 201)


@bp.get("/mtm/deliveries")
def list_deliveries():
    authenticate(ALL_ROLES)
    items = sorted(store["deliveries"].values(), key=lambda r: r["created_at"])
    for param in ("member_id", "menu_cycle_id", "route_id",
                  "authorization_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d[param] == v]
    return paginated([pub(d) for d in items])


def _get_delivery(did):
    d = store["deliveries"].get(did)
    if d is None:
        not_found("Delivery not found")
    return d


@bp.get("/mtm/deliveries/<did>")
def get_delivery(did):
    authenticate(ALL_ROLES)
    return envelope_ok(pub(_get_delivery(did)), "object", 200)


@bp.post("/mtm/deliveries/<did>/out-for-delivery")
def out_for_delivery(did):
    authenticate(["Driver"])
    d = _get_delivery(did)
    if d["status"] != "SCHEDULED":
        raise ApiError("ERR_DELIVERY_NOT_SCHEDULED", 409,
                       "Delivery must be SCHEDULED for out-for-delivery")
    r = store["routes"][d["route_id"]]
    if r["status"] != "DISPATCHED":
        raise ApiError("ERR_ROUTE_NOT_DISPATCHED", 409,
                       "Route must be DISPATCHED for out-for-delivery")
    d["status"] = "OUT_FOR_DELIVERY"
    bump(d)
    return envelope_ok(pub(d), "object", 200)


@bp.post("/mtm/deliveries/<did>/mark-delivered")
def mark_delivered(did):
    authenticate(["Driver"])
    d = _get_delivery(did)
    if d["status"] != "OUT_FOR_DELIVERY":
        raise ApiError("ERR_DELIVERY_NOT_OUT_FOR_DELIVERY", 409,
                       "Delivery must be OUT_FOR_DELIVERY to mark delivered")
    if d["cold_chain_status"] == "SPOILED":
        raise ApiError("ERR_DELIVERY_TERMINAL", 409,
                       "Delivery cold chain is SPOILED")
    d["status"] = "DELIVERED"
    d["delivered_at"] = db.logical_now_iso()
    bump(d)
    domain.consume_unit(d)
    domain.maybe_fulfill_cycle(d["menu_cycle_id"])
    return envelope_ok(pub(d), "object", 200)


@bp.post("/mtm/deliveries/<did>/mark-failed")
def mark_failed(did):
    authenticate(["Driver"])
    d = _get_delivery(did)
    if d["status"] != "OUT_FOR_DELIVERY":
        raise ApiError("ERR_DELIVERY_NOT_OUT_FOR_DELIVERY", 409,
                       "Delivery must be OUT_FOR_DELIVERY to mark failed")
    d["status"] = "FAILED"
    bump(d)
    domain.release_unit(d)
    domain.maybe_fulfill_cycle(d["menu_cycle_id"])
    return envelope_ok(pub(d), "object", 200)


@bp.post("/mtm/deliveries/<did>/confirm-receipt")
def confirm_receipt(did):
    uid, _ = authenticate(["Member"])
    d = _get_delivery(did)
    if d["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Delivery must be DELIVERED to confirm receipt")
    if d["member_id"] != uid:
        raise ApiError("ERR_DELIVERY_NOT_OWNED", 403,
                       "Member may confirm receipt only of own deliveries")
    d["confirmed_at"] = db.logical_now_iso()
    bump(d)
    return envelope_ok(pub(d), "object", 200)


@bp.post("/mtm/deliveries/<did>/cold-chain-readings")
def add_reading(did):
    authenticate(["Driver"])
    body = get_body()
    raw, dt = f_datetime(body, "recorded_at")
    temp = f_number(body, "temp_celsius")
    d = _get_delivery(did)
    if d["status"] != "OUT_FOR_DELIVERY":
        raise ApiError("ERR_DELIVERY_NOT_OUT_FOR_DELIVERY", 409,
                       "Delivery must be OUT_FOR_DELIVERY for cold-chain readings")
    reading = {
        "id": db.new_id(), "delivery_id": did, "recorded_at": raw,
        "temp_celsius": temp, "created_at": db.now_iso(),
        "_recorded_dt": dt,
    }
    store["readings"][reading["id"]] = reading
    cumulative, cc_status = domain.replay_cold_chain(d)
    changed = (cumulative != d["cumulative_excursion_minutes"]
               or cc_status != d["cold_chain_status"])
    spoiled_now = (cc_status == "SPOILED" and d["status"] == "OUT_FOR_DELIVERY")
    d["cumulative_excursion_minutes"] = cumulative
    d["cold_chain_status"] = cc_status
    if spoiled_now:
        d["status"] = "SPOILED"
        bump(d)
        domain.release_unit(d)
        domain.maybe_fulfill_cycle(d["menu_cycle_id"])
    elif changed:
        bump(d)
    return envelope_ok(pub(reading), "object", 201)


@bp.get("/mtm/deliveries/<did>/cold-chain-readings")
def list_readings(did):
    authenticate(ALL_ROLES)
    _get_delivery(did)
    readings = [r for r in store["readings"].values() if r["delivery_id"] == did]
    readings.sort(key=lambda r: (r["_recorded_dt"], r["created_at"]))
    return paginated([pub(r) for r in readings])


# ---------------------------------------------------------------------------
# Reauthorizations
# ---------------------------------------------------------------------------

@bp.post("/mtm/reauthorizations")
def create_reauthorization():
    authenticate(["CareCoordinator"])
    body = get_body()
    member_id = f_str(body, "member_id")
    units = f_int(body, "authorized_units", min_val=1)
    max_amount = f_int(body, "max_amount_cents", min_val=0)
    start_date = f_date(body, "start_date")
    end_date = f_date(body, "end_date")
    if end_date < start_date:
        invalid_request("end_date must be on or after start_date")
    if member_id not in store["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member_id does not exist")
    ts = db.now_iso()
    a = {
        "id": db.new_id(), "member_id": member_id, "authorized_units": units,
        "used_units": 0, "reserved_units": 0, "max_amount_cents": max_amount,
        "consumed_amount_cents": 0, "start_date": start_date,
        "end_date": end_date, "authorization_number": None, "status": "PENDING",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["reauthorizations"][a["id"]] = a
    return envelope_ok(reauth_view(a), "object", 201)


@bp.get("/mtm/reauthorizations")
def list_reauthorizations():
    authenticate(ALL_ROLES)
    items = sorted(store["reauthorizations"].values(), key=lambda r: r["created_at"])
    for param in ("member_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[param] == v]
    return paginated([reauth_view(a) for a in items])


def _get_reauth(aid):
    a = store["reauthorizations"].get(aid)
    if a is None:
        not_found("Reauthorization not found")
    return a


@bp.get("/mtm/reauthorizations/<aid>")
def get_reauthorization(aid):
    authenticate(ALL_ROLES)
    return envelope_ok(reauth_view(_get_reauth(aid)), "object", 200)


@bp.post("/mtm/reauthorizations/<aid>/approve")
def approve_reauthorization(aid):
    authenticate(["PayerReviewer"])
    body = get_body()
    auth_number = f_str(body, "authorization_number")
    a = _get_reauth(aid)
    if a["status"] != "PENDING":
        raise ApiError("ERR_AUTHORIZATION_NOT_PENDING", 409,
                       "Reauthorization must be PENDING to approve")
    member = store["members"][a["member_id"]]
    if member["status"] == "DISENROLLED":
        raise ApiError("ERR_MEMBER_TERMINAL", 409,
                       "Member is DISENROLLED (terminal)")
    delivered_pct, _ = domain.compute_adherence(a["member_id"])
    from decimal import Decimal
    if Decimal(str(delivered_pct)) < domain.ADHERENCE_THRESHOLD:
        raise ApiError("ERR_ADHERENCE_BELOW_THRESHOLD", 409,
                       "Member adherence_delivered_pct is below 80.00")
    today = db.get_clock().date()
    cutoff = (today - timedelta(days=domain.ASSESSMENT_WINDOW_DAYS)).isoformat()
    fresh = [o for o in store["assessments"].values()
             if o["member_id"] == a["member_id"] and o["assessed_at"] >= cutoff]
    if not fresh:
        raise ApiError("ERR_OUTCOME_ASSESSMENT_STALE", 409,
                       "No outcome assessment within trailing 90 days")
    a["authorization_number"] = auth_number
    a["status"] = "APPROVED"
    bump(a)
    return envelope_ok(reauth_view(a), "object", 200)


@bp.post("/mtm/reauthorizations/<aid>/deny")
def deny_reauthorization(aid):
    authenticate(["PayerReviewer"])
    body = get_body()
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        invalid_request("Field reason must be a string")
    a = _get_reauth(aid)
    if a["status"] != "PENDING":
        raise ApiError("ERR_AUTHORIZATION_NOT_PENDING", 409,
                       "Reauthorization must be PENDING to deny")
    a["status"] = "DENIED"
    bump(a)
    return envelope_ok(reauth_view(a), "object", 200)


# ---------------------------------------------------------------------------
# Outcome assessments
# ---------------------------------------------------------------------------

@bp.post("/mtm/outcome-assessments")
def create_assessment():
    uid, _ = authenticate(["Dietitian"])
    body = get_body()
    member_id = f_str(body, "member_id")
    assessed_at = f_date(body, "assessed_at")
    weight = f_number(body, "weight_kg")
    hba1c = f_number(body, "hba1c_pct")
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        invalid_request("Field notes must be a string")
    if member_id not in store["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member_id does not exist")
    ts = db.now_iso()
    o = {
        "id": db.new_id(), "member_id": member_id, "dietitian_user_id": uid,
        "assessed_at": assessed_at, "weight_kg": weight, "hba1c_pct": hba1c,
        "notes": notes, "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["assessments"][o["id"]] = o
    return envelope_ok(pub(o), "object", 201)


@bp.get("/mtm/outcome-assessments")
def list_assessments():
    authenticate(ALL_ROLES)
    items = sorted(store["assessments"].values(), key=lambda r: r["created_at"])
    v = request.args.get("member_id")
    if v is not None:
        items = [o for o in items if o["member_id"] == v]
    return paginated([pub(o) for o in items])


@bp.get("/mtm/outcome-assessments/<oid>")
def get_assessment(oid):
    authenticate(ALL_ROLES)
    o = store["assessments"].get(oid)
    if o is None:
        not_found("Outcome assessment not found")
    return envelope_ok(pub(o), "object", 200)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@bp.post("/mtm/claims")
def create_claim():
    authenticate(["BillingSpecialist"])
    body = get_body()
    member_id = f_str(body, "member_id")
    menu_cycle_id = f_str(body, "menu_cycle_id")
    authorization_id = f_str(body, "authorization_id")
    erv = f_int(body, "expected_reauthorization_version")
    member = store["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member_id does not exist")
    c = store["menu_cycles"].get(menu_cycle_id)
    if c is None:
        raise ApiError("ERR_MENU_CYCLE_NOT_FOUND", 404,
                       "menu_cycle_id does not exist")
    a = store["reauthorizations"].get(authorization_id)
    if a is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND", 404,
                       "authorization_id does not exist")
    # OCC before state preconditions
    if erv != a["version"]:
        raise ApiError("ERR_STALE_AUTHORIZATION_VERSION", 412,
                       "expected_reauthorization_version does not match current version")
    has_delivered = any(d["menu_cycle_id"] == menu_cycle_id
                        and d["status"] == "DELIVERED"
                        for d in store["deliveries"].values())
    if c["status"] not in ("FROZEN", "FULFILLED") or not has_delivered:
        raise ApiError("ERR_MENU_CYCLE_NOT_FROZEN", 409,
                       "Cycle must be FROZEN or FULFILLED with >= 1 DELIVERED delivery")
    if a["member_id"] != member_id:
        raise ApiError("ERR_AUTHORIZATION_MEMBER_MISMATCH", 422,
                       "Authorization belongs to a different member than the claim")
    gross, share, liability = domain.compute_claim_amounts(member, c)
    ts = db.now_iso()
    claim = {
        "id": db.new_id(), "member_id": member_id, "menu_cycle_id": menu_cycle_id,
        "authorization_id": authorization_id,
        "payer_type_snapshot": member["payer_type"],
        "units_delivered": c["meals_count"],
        "provisional_gross_cents": gross,
        "member_cost_share_cents": share,
        "plan_liability_cents": liability,
        "remitted_amount_cents": None, "submitted_by_user_id": None,
        "status": "DRAFT", "created_at": ts, "updated_at": ts, "version": 1,
    }
    store["claims"][claim["id"]] = claim
    bump(a)  # claim creation increments the authorization's version
    return envelope_ok(pub(claim), "object", 201)


@bp.get("/mtm/claims")
def list_claims():
    authenticate(ALL_ROLES)
    items = sorted(store["claims"].values(), key=lambda r: r["created_at"])
    for param in ("member_id", "menu_cycle_id", "authorization_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [cl for cl in items if cl[param] == v]
    return paginated([pub(cl) for cl in items])


def _get_claim(cid):
    cl = store["claims"].get(cid)
    if cl is None:
        not_found("Claim not found")
    return cl


@bp.get("/mtm/claims/<cid>")
def get_claim(cid):
    authenticate(ALL_ROLES)
    return envelope_ok(pub(_get_claim(cid)), "object", 200)


@bp.post("/mtm/claims/<cid>/submit")
def submit_claim(cid):
    uid, _ = authenticate(["BillingSpecialist"])
    cl = _get_claim(cid)
    if cl["status"] != "DRAFT":
        raise ApiError("ERR_CLAIM_NOT_DRAFT", 409,
                       "Claim must be DRAFT to submit")
    c = store["menu_cycles"][cl["menu_cycle_id"]]
    if c["status"] not in ("FROZEN", "FULFILLED"):
        raise ApiError("ERR_MENU_CYCLE_NOT_FROZEN", 409,
                       "Cycle must be FROZEN or FULFILLED to submit a claim")
    a = store["reauthorizations"][cl["authorization_id"]]
    if a["status"] != "APPROVED":
        raise ApiError("ERR_AUTHORIZATION_NOT_APPROVED", 409,
                       "Claim submit requires authorization status APPROVED")
    remaining = a["max_amount_cents"] - a["consumed_amount_cents"]
    if cl["provisional_gross_cents"] > remaining:
        raise ApiError("ERR_AUTHORIZATION_AMOUNT_EXCEEDED", 402,
                       "Claim provisional_gross_cents exceeds authorization remaining amount")
    cl["submitted_by_user_id"] = uid
    cl["status"] = "SUBMITTED"
    bump(cl)
    return envelope_ok(pub(cl), "object", 200)


@bp.post("/mtm/claims/<cid>/remit")
def remit_claim(cid):
    authenticate(["PayerReviewer"])
    body = get_body()
    outcome = f_enum(body, "outcome", ["PAID", "PARTIALLY_PAID", "DENIED"])
    remitted = f_int(body, "remitted_amount_cents", required=False)
    cl = _get_claim(cid)
    if cl["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED", 409,
                       "Claim must be SUBMITTED to remit")
    liability = cl["plan_liability_cents"]
    if outcome == "PAID":
        if remitted is None or remitted != liability:
            raise ApiError("ERR_REMIT_AMOUNT_MISMATCH", 422,
                           "PAID requires remitted_amount_cents == plan_liability_cents")
    elif outcome == "PARTIALLY_PAID":
        if remitted is None or remitted <= 0 or remitted >= liability:
            raise ApiError("ERR_REMIT_AMOUNT_MISMATCH", 422,
                           "PARTIALLY_PAID requires 0 < remitted < plan_liability_cents")
    else:  # DENIED
        if remitted not in (None, 0):
            raise ApiError("ERR_REMIT_AMOUNT_MISMATCH", 422,
                           "DENIED requires remitted_amount_cents omitted or 0")
    cl["remitted_amount_cents"] = remitted
    cl["status"] = outcome
    bump(cl)
    if outcome in ("PAID", "PARTIALLY_PAID"):
        member = store["members"][cl["member_id"]]
        member["oop_accumulator_cents"] += cl["member_cost_share_cents"]
        bump(member)
        a = store["reauthorizations"][cl["authorization_id"]]
        a["consumed_amount_cents"] += remitted
        bump(a)
    return envelope_ok(pub(cl), "object", 200)


@bp.post("/mtm/claims/<cid>/correct")
def correct_claim(cid):
    authenticate(["BillingSpecialist"])
    cl = _get_claim(cid)
    if cl["status"] != "DENIED":
        raise ApiError("ERR_CLAIM_NOT_DENIED", 409,
                       "Claim must be DENIED to correct")
    cl["status"] = "DRAFT"
    bump(cl)
    return envelope_ok(pub(cl), "object", 200)


@bp.post("/mtm/claims/<cid>/void")
def void_claim(cid):
    uid, _ = authenticate(["BillingSpecialist"])
    cl = _get_claim(cid)
    if cl["status"] not in ("PAID", "PARTIALLY_PAID"):
        raise ApiError("ERR_CLAIM_NOT_VOIDABLE", 409,
                       "Claim must be PAID or PARTIALLY_PAID to void")
    if uid == cl["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Claim void attempted by the same operator that submitted it")
    cl["status"] = "VOIDED"
    bump(cl)
    member = store["members"][cl["member_id"]]
    member["oop_accumulator_cents"] -= cl["member_cost_share_cents"]
    bump(member)
    a = store["reauthorizations"][cl["authorization_id"]]
    a["consumed_amount_cents"] -= cl["remitted_amount_cents"]
    bump(a)
    return envelope_ok(pub(cl), "object", 200)
