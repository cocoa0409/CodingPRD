import os
from datetime import datetime, time as dtime, timedelta

from flask import Flask, request

import core
from core import (
    store, clock, set_clock, ApiError, ok, ok_list, error_response,
    require_auth, require_role, get_or_404, new_record, touch, body_json,
    validate_required, validate_optional, validate_enum, paginate, sorted_by_seq,
    parse_dt, D, round_half_up, labor_charge_raw, visit_scheduled_minutes,
    recompute_client_balance, recompute_committed_minutes, recompute_policy,
    bgcheck_status, bond_status, schedule_status, UTC,
)
import serializers as S

app = Flask(__name__)

TASK_TYPES = {"GROCERY", "RX_PICKUP", "TRANSPORT", "COMPANION"}
FREQUENCIES = {"WEEKLY", "BIWEEKLY"}
DOW = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
ADDON_TYPES = {"MEAL_PREP", "PET_CARE", "PAPERWORK", "EXTRA_STOP"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
ENTRY_TYPES = {"NOTE", "TASK_DONE", "INCIDENT"}
BENEFIT_TYPES = {"INDEMNITY", "REIMBURSEMENT"}


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(_e):
    return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Method not allowed"))


# ===========================================================================
# Clients
# ===========================================================================
@app.post("/care/clients")
def create_client():
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    b = body_json()
    validate_required(b, [("name", "str"), ("home_zip", "str"),
                          ("hourly_rate_cents", "int"), ("mileage_rate_cents_per_mile", "num")])
    validate_optional(b, [("timezone", "str"), ("ot_threshold_hours", "num"),
                          ("ot_multiplier", "num"), ("min_visit_minutes", "int")])
    c = new_record(with_status="ACTIVE")
    c.update({
        "name": b["name"],
        "timezone": b.get("timezone", "UTC") if b.get("timezone") is not None else "UTC",
        "home_zip": b["home_zip"],
        "hourly_rate_cents": b["hourly_rate_cents"],
        "mileage_rate_cents_per_mile": b["mileage_rate_cents_per_mile"],
        "ot_threshold_hours": b["ot_threshold_hours"] if b.get("ot_threshold_hours") is not None else 8,
        "ot_multiplier": b["ot_multiplier"] if b.get("ot_multiplier") is not None else 1.5,
        "min_visit_minutes": b["min_visit_minutes"] if b.get("min_visit_minutes") is not None else 60,
        "outstanding_balance_cents": 0,
    })
    store["clients"][c["id"]] = c
    return ok(S.client_out(c), code=201)


@app.get("/care/clients/<cid>")
def get_client(cid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "BillingClerk"})
    c = get_or_404("clients", cid)
    return ok(S.client_out(c))


@app.post("/care/clients/<cid>/suspend")
def suspend_client(cid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    c = get_or_404("clients", cid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client is not ACTIVE")
    c["status"] = "SUSPENDED"
    touch(c)
    # hop 1: ACTIVE schedules -> PAUSED (each cascades to its SCHEDULED visits)
    for s in list(store["schedules"].values()):
        if s["client_id"] == cid and s["status"] == "ACTIVE":
            _pause_schedule(s)
    recompute_client_balance(c)
    return ok(S.client_out(c))


@app.post("/care/clients/<cid>/family-contacts")
def create_family_contact(cid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    get_or_404("clients", cid)
    b = body_json()
    validate_required(b, [("name", "str"), ("email", "str"), ("relationship", "str")])
    fc = new_record()
    fc.update({"client_id": cid, "name": b["name"], "email": b["email"],
               "relationship": b["relationship"]})
    store["family_contacts"][fc["id"]] = fc
    return ok(S.family_contact_out(fc), code=201)


@app.get("/care/clients/<cid>/family-contacts")
def list_family_contacts(cid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    get_or_404("clients", cid)
    items = sorted_by_seq([f for f in store["family_contacts"].values() if f["client_id"] == cid])
    page, pg = paginate(items)
    return ok_list([S.family_contact_out(x) for x in page], pg)


@app.post("/care/clients/<cid>/schedules")
def create_schedule(cid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    c = get_or_404("clients", cid)
    b = body_json()
    validate_required(b, [("task_type", "str"), ("frequency", "str"), ("day_of_week", "str"),
                          ("start_time", "str"), ("duration_minutes", "int"),
                          ("start_date", "datetime"), ("end_date", "datetime")])
    validate_enum(b, "task_type", TASK_TYPES)
    validate_enum(b, "frequency", FREQUENCIES)
    validate_enum(b, "day_of_week", set(DOW.keys()))
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client is not ACTIVE")
    start_date = parse_dt(b["start_date"])
    end_date = parse_dt(b["end_date"])
    if end_date < start_date:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422, "end_date before start_date")
    s = new_record(with_status="ACTIVE")
    s.update({
        "client_id": cid, "task_type": b["task_type"], "frequency": b["frequency"],
        "day_of_week": b["day_of_week"], "start_time": b["start_time"],
        "duration_minutes": b["duration_minutes"], "start_date": start_date, "end_date": end_date,
    })
    store["schedules"][s["id"]] = s
    return ok(S.schedule_out(s), code=201)


@app.get("/care/clients/<cid>/schedules")
def list_schedules(cid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    get_or_404("clients", cid)
    items = sorted_by_seq([s for s in store["schedules"].values() if s["client_id"] == cid])
    page, pg = paginate(items)
    return ok_list([S.schedule_out(x) for x in page], pg)


@app.post("/care/clients/<cid>/ltc-policies")
def create_ltc_policy(cid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    get_or_404("clients", cid)
    b = body_json()
    validate_required(b, [("payer_name", "str"), ("benefit_type", "str"),
                          ("lifetime_max_cents", "int")])
    validate_optional(b, [("daily_benefit_cents", "int"), ("reimbursement_rate", "num"),
                          ("daily_cap_cents", "int")])
    validate_enum(b, "benefit_type", BENEFIT_TYPES)
    p = new_record(with_status="ACTIVE")
    p.update({
        "client_id": cid, "payer_name": b["payer_name"], "benefit_type": b["benefit_type"],
        "daily_benefit_cents": b.get("daily_benefit_cents"),
        "reimbursement_rate": b.get("reimbursement_rate"),
        "daily_cap_cents": b.get("daily_cap_cents"),
        "lifetime_max_cents": b["lifetime_max_cents"],
        "reimbursed_to_date_cents": 0,
    })
    store["ltc_policies"][p["id"]] = p
    return ok(S.ltc_policy_out(p), code=201)


@app.get("/care/clients/<cid>/ltc-policies")
def list_ltc_policies(cid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "BillingClerk"})
    get_or_404("clients", cid)
    items = sorted_by_seq([p for p in store["ltc_policies"].values() if p["client_id"] == cid])
    page, pg = paginate(items)
    return ok_list([S.ltc_policy_out(x) for x in page], pg)


# ===========================================================================
# Caregivers / background checks / bonds
# ===========================================================================
@app.post("/care/caregivers")
def create_caregiver():
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    b = body_json()
    validate_required(b, [("name", "str"), ("home_zip", "str")])
    validate_optional(b, [("hourly_pay_cents", "int")])
    cg = new_record(with_status="ACTIVE")
    cg.update({
        "name": b["name"], "home_zip": b["home_zip"],
        "hourly_pay_cents": b["hourly_pay_cents"] if b.get("hourly_pay_cents") is not None else 0,
        "committed_minutes": 0,
    })
    store["caregivers"][cg["id"]] = cg
    return ok(S.caregiver_out(cg), code=201)


@app.get("/care/caregivers/<gid>")
def get_caregiver(gid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "BillingClerk"})
    cg = get_or_404("caregivers", gid)
    return ok(S.caregiver_out(cg))


@app.post("/care/caregivers/<gid>/background-checks")
def create_background_check(gid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    get_or_404("caregivers", gid)
    bc = new_record(with_status="PENDING")
    bc.update({"caregiver_id": gid, "decided_at": None, "expires_at": None})
    store["background_checks"][bc["id"]] = bc
    return ok(S.background_check_out(bc), code=201)


@app.get("/care/caregivers/<gid>/background-checks")
def list_background_checks(gid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    get_or_404("caregivers", gid)
    items = sorted_by_seq([b for b in store["background_checks"].values() if b["caregiver_id"] == gid])
    page, pg = paginate(items)
    return ok_list([S.background_check_out(x) for x in page], pg)


@app.post("/care/background-checks/<bid>/decision")
def background_check_decision(bid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    bc = get_or_404("background_checks", bid)
    b = body_json()
    validate_required(b, [("outcome", "str")])
    validate_optional(b, [("expires_at", "datetime")])
    validate_enum(b, "outcome", {"CLEARED", "FLAGGED"})
    if bc["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Background check is not PENDING")
    bc["decided_at"] = clock()
    if b["outcome"] == "CLEARED":
        bc["status"] = "CLEARED"
        bc["expires_at"] = parse_dt(b["expires_at"]) if b.get("expires_at") is not None else None
    else:
        bc["status"] = "FLAGGED"
    touch(bc)
    return ok(S.background_check_out(bc))


@app.post("/care/caregivers/<gid>/bonds")
def create_bond(gid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    get_or_404("caregivers", gid)
    b = body_json()
    validate_required(b, [("coverage_cents", "int"), ("effective_date", "datetime"),
                          ("expiry_date", "datetime")])
    bond = new_record(with_status="ACTIVE")
    bond.update({
        "caregiver_id": gid, "coverage_cents": b["coverage_cents"],
        "effective_date": parse_dt(b["effective_date"]),
        "expiry_date": parse_dt(b["expiry_date"]),
    })
    store["bonds"][bond["id"]] = bond
    return ok(S.bond_out(bond), code=201)


@app.get("/care/caregivers/<gid>/bonds")
def list_bonds(gid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    get_or_404("caregivers", gid)
    items = sorted_by_seq([x for x in store["bonds"].values() if x["caregiver_id"] == gid])
    page, pg = paginate(items)
    return ok_list([S.bond_out(x) for x in page], pg)


# ===========================================================================
# Schedules
# ===========================================================================
@app.get("/care/schedules/<sid>")
def get_schedule(sid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    s = get_or_404("schedules", sid)
    return ok(S.schedule_out(s))


@app.post("/care/schedules/<sid>/generate-visits")
def generate_visits(sid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    s = get_or_404("schedules", sid)
    b = body_json()
    validate_required(b, [("from_date", "datetime"), ("to_date", "datetime")])
    if schedule_status(s) != "ACTIVE":
        raise ApiError("ERR_SCHEDULE_NOT_ACTIVE", 409, "Schedule is not ACTIVE")
    client = store["clients"].get(s["client_id"])
    from_d = parse_dt(b["from_date"]).date()
    to_d = parse_dt(b["to_date"]).date()
    start_d = s["start_date"].date()
    end_d = s["end_date"].date()
    dow = DOW[s["day_of_week"]]
    interval = 7 if s["frequency"] == "WEEKLY" else 14

    # first matching weekday on/after schedule start_date
    anchor = start_d
    while anchor.weekday() != dow:
        anchor = anchor + timedelta(days=1)

    hh, mm = _parse_hhmm(s["start_time"])
    created = []
    d = anchor
    while d <= end_d:
        if from_d <= d <= to_d and d >= start_d:
            ss = datetime(d.year, d.month, d.day, hh, mm, tzinfo=UTC)
            se = ss + timedelta(minutes=s["duration_minutes"])
            v = _make_visit(client, s["task_type"], ss, se, s["id"])
            created.append(v)
        d = d + timedelta(days=interval)

    created = sorted_by_seq(created)
    return ok([S.visit_out(v) for v in created], response_type="array", code=201)


def _parse_hhmm(val):
    parts = val.split(":")
    return int(parts[0]), int(parts[1])


# ===========================================================================
# Visits
# ===========================================================================
def _make_visit(client, task_type, scheduled_start, scheduled_end, schedule_id):
    v = new_record(with_status="SCHEDULED")
    v.update({
        "client_id": client["id"], "schedule_id": schedule_id, "caregiver_id": None,
        "task_type": task_type, "scheduled_start": scheduled_start, "scheduled_end": scheduled_end,
        "actual_start": None, "actual_end": None, "mileage_miles": 0,
        "hourly_rate_cents": client["hourly_rate_cents"],
        "mileage_rate_cents_per_mile": client["mileage_rate_cents_per_mile"],
        "ot_threshold_hours": client["ot_threshold_hours"],
        "ot_multiplier": client["ot_multiplier"],
        "min_visit_minutes": client["min_visit_minutes"],
        "estimated_cost_cents": None,
    })
    store["visits"][v["id"]] = v
    return v


@app.post("/care/visits")
def create_visit():
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    b = body_json()
    validate_required(b, [("client_id", "str"), ("task_type", "str"),
                          ("scheduled_start", "datetime"), ("scheduled_end", "datetime")])
    validate_optional(b, [("schedule_id", "str")])
    validate_enum(b, "task_type", TASK_TYPES)
    client = store["clients"].get(b["client_id"])
    if client is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Client not found")
    if b.get("schedule_id") is not None and b["schedule_id"] not in store["schedules"]:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Schedule not found")
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client is not ACTIVE")
    ss = parse_dt(b["scheduled_start"])
    se = parse_dt(b["scheduled_end"])
    # client visit overlap (closed intervals, no buffer) against non-cancelled visits
    for ov in store["visits"].values():
        if ov["client_id"] == client["id"] and ov["status"] != "CANCELLED":
            if ss <= ov["scheduled_end"] and ov["scheduled_start"] <= se:
                raise ApiError("ERR_CLIENT_VISIT_OVERLAP", 409, "Overlaps an existing visit")
    if se <= ss:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422, "scheduled_end must be after scheduled_start")
    v = _make_visit(client, b["task_type"], ss, se, b.get("schedule_id"))
    return ok(S.visit_out(v), code=201)


@app.get("/care/visits/<vid>")
def get_visit(vid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "BillingClerk", "Caregiver", "FamilyContact"})
    v = get_or_404("visits", vid)
    return ok(S.visit_out(v))


@app.get("/care/visits")
def list_visits():
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "BillingClerk"})
    items = list(store["visits"].values())
    cid = request.args.get("client_id")
    gid = request.args.get("caregiver_id")
    sid = request.args.get("schedule_id")
    if cid is not None:
        items = [x for x in items if x["client_id"] == cid]
    if gid is not None:
        items = [x for x in items if x["caregiver_id"] == gid]
    if sid is not None:
        items = [x for x in items if x["schedule_id"] == sid]
    items = sorted_by_seq(items)
    page, pg = paginate(items)
    return ok_list([S.visit_out(x) for x in page], pg)


@app.post("/care/visits/<vid>/assignments")
def create_assignment(vid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    v = get_or_404("visits", vid)
    b = body_json()
    validate_required(b, [("caregiver_id", "str"), ("expected_visit_version", "int")])
    cg = store["caregivers"].get(b["caregiver_id"])
    if cg is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Caregiver not found")
    # OCC (priority 7) before state (priority 8)
    if b["expected_visit_version"] != v["version"]:
        raise ApiError("ERR_STALE_VISIT_VERSION", 412, "Stale visit version")
    if v["status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_NOT_SCHEDULED", 409, "Visit is not SCHEDULED")
    # clearance / bonding (priority 9)
    if not _caregiver_cleared(cg["id"]):
        raise ApiError("ERR_CAREGIVER_NOT_CLEARED", 409, "Caregiver not cleared")
    if not _caregiver_bonded(cg["id"]):
        raise ApiError("ERR_CAREGIVER_NOT_BONDED", 409, "Caregiver not bonded")
    # double-booking (priority 11): buffered half-open against CONFIRMED assignments
    if _caregiver_double_booked(cg["id"], v):
        raise ApiError("ERR_CAREGIVER_DOUBLE_BOOKED", 409, "Caregiver double-booked")

    # supersede prior CONFIRMED assignment on this visit
    for a in store["assignments"].values():
        if a["visit_id"] == vid and a["status"] == "CONFIRMED":
            prev_cg = store["caregivers"].get(a["caregiver_id"])
            a["status"] = "SUPERSEDED"
            touch(a)
            if prev_cg is not None:
                recompute_committed_minutes(prev_cg)

    a = new_record(with_status="CONFIRMED")
    a.update({"visit_id": vid, "caregiver_id": cg["id"]})
    store["assignments"][a["id"]] = a

    v["caregiver_id"] = cg["id"]
    sched_min = visit_scheduled_minutes(v)
    raw = labor_charge_raw(sched_min, v["hourly_rate_cents"], v["ot_threshold_hours"],
                           v["ot_multiplier"], v["min_visit_minutes"])
    v["estimated_cost_cents"] = round_half_up(raw)
    touch(v)
    recompute_committed_minutes(cg)
    return ok(S.assignment_out(a), code=201)


@app.post("/care/assignments/<aid>/cancel")
def cancel_assignment(aid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    a = get_or_404("assignments", aid)
    if a["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment is not CONFIRMED")
    a["status"] = "CANCELLED"
    touch(a)
    cg = store["caregivers"].get(a["caregiver_id"])
    v = store["visits"].get(a["visit_id"])
    if v is not None and v.get("caregiver_id") == a["caregiver_id"]:
        v["caregiver_id"] = None
        touch(v)
    if cg is not None:
        recompute_committed_minutes(cg)
    return ok(S.assignment_out(a))


@app.get("/care/assignments/<aid>")
def get_assignment(aid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    a = get_or_404("assignments", aid)
    return ok(S.assignment_out(a))


@app.get("/care/assignments")
def list_assignments():
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    items = list(store["assignments"].values())
    vid = request.args.get("visit_id")
    gid = request.args.get("caregiver_id")
    if vid is not None:
        items = [x for x in items if x["visit_id"] == vid]
    if gid is not None:
        items = [x for x in items if x["caregiver_id"] == gid]
    items = sorted_by_seq(items)
    page, pg = paginate(items)
    return ok_list([S.assignment_out(x) for x in page], pg)


def _caregiver_cleared(gid):
    for bc in store["background_checks"].values():
        if (bc["caregiver_id"] == gid and bc["status"] == "CLEARED"
                and bc.get("expires_at") is not None and bc["expires_at"] > clock()):
            return True
    return False


def _caregiver_bonded(gid):
    for bond in store["bonds"].values():
        if (bond["caregiver_id"] == gid
                and bond["effective_date"] <= clock() < bond["expiry_date"]):
            return True
    return False


def _caregiver_double_booked(gid, visit):
    ns, ne = visit["scheduled_start"], visit["scheduled_end"]
    for a in store["assignments"].values():
        if a["caregiver_id"] != gid or a["status"] != "CONFIRMED":
            continue
        if a["visit_id"] == visit["id"]:
            continue
        other = store["visits"].get(a["visit_id"])
        if other is None:
            continue
        os_, oe = other["scheduled_start"], other["scheduled_end"]
        # half-open overlap: touching endpoints do not conflict
        if ns < oe and os_ < ne:
            return True
    return False


# ===========================================================================
# Add-ons
# ===========================================================================
@app.post("/care/visits/<vid>/add-ons")
def create_addon(vid):
    uid, role = require_auth()
    require_role(role, {"CareCoordinator", "FamilyContact"})
    v = get_or_404("visits", vid)
    if role == "FamilyContact":
        _require_family_owns_client(uid, v["client_id"])
    b = body_json()
    validate_required(b, [("addon_type", "str"), ("fee_cents", "int")])
    validate_enum(b, "addon_type", ADDON_TYPES)
    a = new_record(with_status="REQUESTED")
    a.update({"visit_id": vid, "addon_type": b["addon_type"], "fee_cents": b["fee_cents"]})
    store["addons"][a["id"]] = a
    return ok(S.addon_out(a), code=201)


@app.get("/care/visits/<vid>/add-ons")
def list_addons(vid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "FamilyContact"})
    get_or_404("visits", vid)
    items = sorted_by_seq([x for x in store["addons"].values() if x["visit_id"] == vid])
    page, pg = paginate(items)
    return ok_list([S.addon_out(x) for x in page], pg)


@app.post("/care/add-ons/<aid>/approve")
def approve_addon(aid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    a = get_or_404("addons", aid)
    b = body_json()
    validate_required(b, [("outcome", "str")])
    validate_enum(b, "outcome", {"APPROVE", "REJECT"})
    if a["status"] != "REQUESTED":
        raise ApiError("ERR_ADDON_NOT_REQUESTED", 409, "Add-on is not REQUESTED")
    if b["outcome"] == "APPROVE":
        v = store["visits"].get(a["visit_id"])
        if v is not None and v["status"] in ("COMPLETED", "CANCELLED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Parent visit already completed or cancelled")
        a["status"] = "APPROVED"
    else:
        a["status"] = "REJECTED"
    touch(a)
    return ok(S.addon_out(a))


# ===========================================================================
# Visit lifecycle: clock-in / clock-out / escalate / cancel / log
# ===========================================================================
@app.post("/care/visits/<vid>/clock-in")
def clock_in(vid):
    uid, role = require_auth()
    require_role(role, {"Caregiver"})
    v = get_or_404("visits", vid)
    if v.get("caregiver_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the assigned caregiver")
    b = body_json()
    validate_required(b, [("actual_start", "datetime")])
    if v["status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_NOT_SCHEDULED", 409, "Visit is not SCHEDULED")
    if not _caregiver_cleared(uid):
        raise ApiError("ERR_CAREGIVER_NOT_CLEARED", 409, "Caregiver not cleared")
    if not _caregiver_bonded(uid):
        raise ApiError("ERR_CAREGIVER_NOT_BONDED", 409, "Caregiver not bonded")
    v["actual_start"] = parse_dt(b["actual_start"])
    v["status"] = "IN_PROGRESS"
    touch(v)
    return ok(S.visit_out(v))


@app.post("/care/visits/<vid>/clock-out")
def clock_out(vid):
    uid, role = require_auth()
    require_role(role, {"Caregiver"})
    v = get_or_404("visits", vid)
    if v.get("caregiver_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the assigned caregiver")
    b = body_json()
    validate_required(b, [("actual_end", "datetime"), ("mileage_miles", "num")])
    if v["status"] not in ("IN_PROGRESS", "ESCALATED"):
        raise ApiError("ERR_VISIT_NOT_IN_PROGRESS", 409, "Visit is not IN_PROGRESS")
    actual_end = parse_dt(b["actual_end"])
    mileage = b["mileage_miles"]
    if v.get("actual_start") is None or actual_end <= v["actual_start"] or mileage < 0:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422, "Invalid actual_end or mileage")
    v["actual_end"] = actual_end
    v["mileage_miles"] = mileage
    v["status"] = "COMPLETED"
    touch(v)
    _assemble_invoice(v)
    return ok(S.visit_out(v))


def _assemble_invoice(v):
    actual_minutes = D((v["actual_end"] - v["actual_start"]).total_seconds()) / D(60)
    raw = labor_charge_raw(actual_minutes, v["hourly_rate_cents"], v["ot_threshold_hours"],
                           v["ot_multiplier"], v["min_visit_minutes"])
    labor_cents = round_half_up(raw)
    mileage_cents = round_half_up(D(v["mileage_miles"]) * D(v["mileage_rate_cents_per_mile"]))
    addon_cents = sum(a["fee_cents"] for a in store["addons"].values()
                      if a["visit_id"] == v["id"] and a["status"] == "APPROVED")
    total = labor_cents + mileage_cents + addon_cents
    inv = new_record(with_status="DRAFT")
    inv.update({
        "client_id": v["client_id"], "visit_id": v["id"],
        "labor_cents": labor_cents, "mileage_cents": mileage_cents,
        "addon_cents": addon_cents, "total_cents": total,
    })
    store["invoices"][inv["id"]] = inv
    return inv


@app.post("/care/visits/<vid>/escalate")
def escalate_visit(vid):
    uid, role = require_auth()
    require_role(role, {"Caregiver"})
    v = get_or_404("visits", vid)
    if v.get("caregiver_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the assigned caregiver")
    b = body_json()
    validate_required(b, [("severity", "str"), ("reason", "str")])
    validate_enum(b, "severity", SEVERITIES)
    if v["status"] != "IN_PROGRESS":
        raise ApiError("ERR_VISIT_NOT_IN_PROGRESS", 409, "Visit is not IN_PROGRESS")
    v["status"] = "ESCALATED"
    touch(v)
    w = new_record(with_status="OPEN")
    w.update({"visit_id": vid, "client_id": v["client_id"], "severity": b["severity"],
              "reason": b["reason"], "acknowledged_by": None})
    store["wellness_checks"][w["id"]] = w
    return ok(S.wellness_out(w), code=201)


@app.post("/care/visits/<vid>/cancel")
def cancel_visit(vid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    v = get_or_404("visits", vid)
    if v["status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_NOT_SCHEDULED", 409, "Visit is not SCHEDULED")
    _cancel_visit_cascade(v)
    return ok(S.visit_out(v))


def _cancel_visit_cascade(v):
    v["status"] = "CANCELLED"
    touch(v)
    # hop 3: CONFIRMED assignments -> CANCELLED (release committed minutes)
    for a in store["assignments"].values():
        if a["visit_id"] == v["id"] and a["status"] == "CONFIRMED":
            cg = store["caregivers"].get(a["caregiver_id"])
            a["status"] = "CANCELLED"
            touch(a)
            if cg is not None:
                recompute_committed_minutes(cg)
    if v.get("caregiver_id") is not None:
        v["caregiver_id"] = None
        touch(v)
    # DRAFT invoice -> VOID
    for inv in store["invoices"].values():
        if inv["visit_id"] == v["id"] and inv["status"] == "DRAFT":
            inv["status"] = "VOID"
            touch(inv)


def _pause_schedule(s):
    s["status"] = "PAUSED"
    touch(s)
    # hop 2: SCHEDULED visits of this schedule -> CANCELLED (each hop-3 cascade)
    for v in list(store["visits"].values()):
        if v["schedule_id"] == s["id"] and v["status"] == "SCHEDULED":
            _cancel_visit_cascade(v)


@app.post("/care/visits/<vid>/log")
def append_log(vid):
    uid, role = require_auth()
    require_role(role, {"Caregiver"})
    v = get_or_404("visits", vid)
    if v.get("caregiver_id") != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the assigned caregiver")
    b = body_json()
    validate_required(b, [("entry_type", "str"), ("note", "str")])
    validate_enum(b, "entry_type", ENTRY_TYPES)
    entry = {
        "id": core.uuid.uuid4().__str__(),
        "created_at": core.now_wall(),
        "_seq": core.next_seq(),
        "visit_id": vid, "entry_type": b["entry_type"], "note": b["note"],
    }
    store["visit_logs"][entry["id"]] = entry
    return ok(S.visit_log_out(entry), code=201)


@app.get("/care/visits/<vid>/log")
def list_log(vid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "FamilyContact", "Caregiver"})
    get_or_404("visits", vid)
    items = sorted_by_seq([x for x in store["visit_logs"].values() if x["visit_id"] == vid])
    page, pg = paginate(items)
    return ok_list([S.visit_log_out(x) for x in page], pg)


# ===========================================================================
# Wellness checks
# ===========================================================================
@app.get("/care/wellness-checks/<wid>")
def get_wellness(wid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "FamilyContact"})
    w = get_or_404("wellness_checks", wid)
    return ok(S.wellness_out(w))


@app.get("/care/wellness-checks")
def list_wellness():
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "FamilyContact"})
    items = list(store["wellness_checks"].values())
    vid = request.args.get("visit_id")
    cid = request.args.get("client_id")
    if vid is not None:
        items = [x for x in items if x["visit_id"] == vid]
    if cid is not None:
        items = [x for x in items if x["client_id"] == cid]
    items = sorted_by_seq(items)
    page, pg = paginate(items)
    return ok_list([S.wellness_out(x) for x in page], pg)


@app.post("/care/wellness-checks/<wid>/acknowledge")
def acknowledge_wellness(wid):
    uid, role = require_auth()
    require_role(role, {"FamilyContact"})
    w = get_or_404("wellness_checks", wid)
    _require_family_owns_client(uid, w["client_id"])
    if w["status"] != "OPEN":
        raise ApiError("ERR_WELLNESS_NOT_ACTIONABLE", 409, "Wellness check is not OPEN")
    w["status"] = "ACKNOWLEDGED"
    w["acknowledged_by"] = uid
    touch(w)
    return ok(S.wellness_out(w))


@app.post("/care/wellness-checks/<wid>/resolve")
def resolve_wellness(wid):
    uid, role = require_auth()
    require_role(role, {"FamilyContact", "CareCoordinator"})
    w = get_or_404("wellness_checks", wid)
    if role == "FamilyContact":
        _require_family_owns_client(uid, w["client_id"])
        if w["status"] != "ACKNOWLEDGED":
            raise ApiError("ERR_WELLNESS_NOT_ACTIONABLE", 409, "Wellness check is not ACKNOWLEDGED")
    else:  # CareCoordinator resolves directly from OPEN
        if w["status"] != "OPEN":
            raise ApiError("ERR_WELLNESS_NOT_ACTIONABLE", 409, "Wellness check is not OPEN")
    w["status"] = "RESOLVED"
    touch(w)
    return ok(S.wellness_out(w))


def _require_family_owns_client(uid, client_id):
    fc = store["family_contacts"].get(uid)
    if fc is None or fc["client_id"] != client_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Family contact does not own this client")


# ===========================================================================
# Invoices
# ===========================================================================
@app.get("/care/invoices/<iid>")
def get_invoice(iid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "BillingClerk", "FamilyContact"})
    inv = get_or_404("invoices", iid)
    return ok(S.invoice_out(inv))


@app.get("/care/invoices")
def list_invoices():
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "BillingClerk"})
    items = list(store["invoices"].values())
    cid = request.args.get("client_id")
    vid = request.args.get("visit_id")
    if cid is not None:
        items = [x for x in items if x["client_id"] == cid]
    if vid is not None:
        items = [x for x in items if x["visit_id"] == vid]
    items = sorted_by_seq(items)
    page, pg = paginate(items)
    return ok_list([S.invoice_out(x) for x in page], pg)


@app.post("/care/invoices/<iid>/finalize")
def finalize_invoice(iid):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    inv = get_or_404("invoices", iid)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_NOT_DRAFT", 409, "Invoice is not DRAFT")
    inv["status"] = "FINALIZED"
    touch(inv)
    client = store["clients"].get(inv["client_id"])
    if client is not None:
        recompute_client_balance(client)
    return ok(S.invoice_out(inv))


@app.post("/care/invoices/<iid>/void")
def void_invoice(iid):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    inv = get_or_404("invoices", iid)
    if inv["status"] == "VOID":
        raise ApiError("ERR_INVOICE_ALREADY_VOID", 409, "Invoice is already VOID")
    was_finalized = inv["status"] == "FINALIZED"
    inv["status"] = "VOID"
    touch(inv)
    if was_finalized:
        # hop 2: withdraw claims against this invoice
        for cl in store["claims"].values():
            if cl["invoice_id"] == iid and cl["status"] in ("DRAFT", "SUBMITTED", "NEEDS_INFO", "APPROVED"):
                cl["status"] = "WITHDRAWN"
                touch(cl)
                policy = store["ltc_policies"].get(cl["ltc_policy_id"])
                if policy is not None:
                    recompute_policy(policy)
        client = store["clients"].get(inv["client_id"])
        if client is not None:
            recompute_client_balance(client)
    return ok(S.invoice_out(inv))


@app.post("/care/invoices/<iid>/claims")
def create_claim(iid):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    inv = get_or_404("invoices", iid)
    b = body_json()
    validate_required(b, [("ltc_policy_id", "str")])
    policy = store["ltc_policies"].get(b["ltc_policy_id"])
    if policy is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "LTC policy not found")
    if policy["client_id"] != inv["client_id"]:
        raise ApiError("ERR_POLICY_CLIENT_MISMATCH", 409, "Policy belongs to a different client")

    eligible = inv["labor_cents"] + inv["addon_cents"]
    if policy["benefit_type"] == "INDEMNITY":
        reimbursed = min(policy["daily_benefit_cents"], eligible)
    else:
        rate_amount = round_half_up(D(policy["reimbursement_rate"]) * D(eligible))
        reimbursed = min(rate_amount, policy["daily_cap_cents"])
    cl = new_record(with_status="DRAFT")
    cl.update({
        "invoice_id": iid, "ltc_policy_id": policy["id"], "benefit_type": policy["benefit_type"],
        "eligible_cents": eligible, "reimbursed_cents": reimbursed,
        "client_responsibility_cents": inv["total_cents"] - reimbursed,
    })
    store["claims"][cl["id"]] = cl
    return ok(S.claim_out(cl), code=201)


# ===========================================================================
# Claims
# ===========================================================================
@app.get("/care/claims/<cid>")
def get_claim(cid):
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "BillingClerk"})
    cl = get_or_404("claims", cid)
    return ok(S.claim_out(cl))


@app.get("/care/claims")
def list_claims():
    _, role = require_auth()
    require_role(role, {"CareCoordinator", "BillingClerk"})
    items = list(store["claims"].values())
    iid = request.args.get("invoice_id")
    pid = request.args.get("ltc_policy_id")
    if iid is not None:
        items = [x for x in items if x["invoice_id"] == iid]
    if pid is not None:
        items = [x for x in items if x["ltc_policy_id"] == pid]
    items = sorted_by_seq(items)
    page, pg = paginate(items)
    return ok_list([S.claim_out(x) for x in page], pg)


@app.post("/care/claims/<cid>/submit")
def submit_claim(cid):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    cl = get_or_404("claims", cid)
    if cl["status"] not in ("DRAFT", "NEEDS_INFO"):
        raise ApiError("ERR_CLAIM_NOT_SUBMITTABLE", 409, "Claim is not submittable")
    inv = store["invoices"].get(cl["invoice_id"])
    if inv is None or inv["status"] != "FINALIZED":
        raise ApiError("ERR_INVOICE_NOT_FINALIZED", 409, "Referenced invoice is not FINALIZED")
    policy = store["ltc_policies"].get(cl["ltc_policy_id"])
    if policy is None or policy["status"] != "ACTIVE":
        if policy is not None and policy["status"] == "EXHAUSTED":
            raise ApiError("ERR_POLICY_EXHAUSTED", 402, "Referenced policy is EXHAUSTED")
        raise ApiError("ERR_POLICY_NOT_ACTIVE", 409, "Referenced policy is not ACTIVE")
    cl["status"] = "SUBMITTED"
    touch(cl)
    return ok(S.claim_out(cl))


@app.post("/care/claims/<cid>/request-info")
def request_info_claim(cid):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    cl = get_or_404("claims", cid)
    b = body_json()
    validate_optional(b, [("note", "str")])
    if cl["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", 409, "Claim is not SUBMITTED")
    cl["status"] = "NEEDS_INFO"
    touch(cl)
    return ok(S.claim_out(cl))


@app.post("/care/claims/<cid>/decision")
def decide_claim(cid):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    cl = get_or_404("claims", cid)
    b = body_json()
    validate_required(b, [("outcome", "str")])
    validate_enum(b, "outcome", {"APPROVE", "DENY"})
    if cl["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", 409, "Claim is not SUBMITTED")
    if b["outcome"] == "APPROVE":
        cl["status"] = "APPROVED"
        touch(cl)
        policy = store["ltc_policies"].get(cl["ltc_policy_id"])
        if policy is not None:
            recompute_policy(policy)
        inv = store["invoices"].get(cl["invoice_id"])
        if inv is not None:
            client = store["clients"].get(inv["client_id"])
            if client is not None:
                recompute_client_balance(client)
    else:
        cl["status"] = "DENIED"
        touch(cl)
    return ok(S.claim_out(cl))


@app.post("/care/claims/<cid>/withdraw")
def withdraw_claim(cid):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    cl = get_or_404("claims", cid)
    if cl["status"] not in ("DRAFT", "SUBMITTED", "NEEDS_INFO", "APPROVED"):
        raise ApiError("ERR_CLAIM_NOT_ACTIONABLE", 409, "Claim is in a terminal state")
    was_approved = cl["status"] == "APPROVED"
    cl["status"] = "WITHDRAWN"
    touch(cl)
    if was_approved:
        policy = store["ltc_policies"].get(cl["ltc_policy_id"])
        if policy is not None:
            recompute_policy(policy)
        inv = store["invoices"].get(cl["invoice_id"])
        if inv is not None:
            client = store["clients"].get(inv["client_id"])
            if client is not None:
                recompute_client_balance(client)
    return ok(S.claim_out(cl))


# ===========================================================================
# Logical clock (test-driving)
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = require_auth()
    require_role(role, {"CareCoordinator"})
    b = body_json()
    validate_required(b, [("to_iso8601", "datetime")])
    set_clock(parse_dt(b["to_iso8601"]))
    return ok({}, code=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
