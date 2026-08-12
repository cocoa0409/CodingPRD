"""Routes: assembly runs, shipping waves, shipments, return cases, billing statements."""
import uuid
from datetime import timedelta

from flask import Blueprint, request

from core import (
    STORE, clock, iso, parse_dt, valid_period, period_bounds,
    ApiError, bad_request, not_found, conflict,
    base_record, touch, pub, ok, list_resp,
    require_roles, check_own,
    owner_of_plan, owner_of_run, owner_of_shipment, owner_of_case,
    body, req_field, req_str, req_int, req_enum,
    get_or_404, lines_of_revision, subs_of_plan, shipments_of_run,
    find_statement, compute_statement, recompute_provisional,
    statement_for_run, recompute_statements_for_shipments,
    comp_available, append_event, postage_for, ser_wave,
)

bp = Blueprint("ops_routes", __name__)

def invalid_state_exc(msg="Target entity is not in a valid state for this transition"):
    return conflict("ERR_INVALID_STATE", msg)

def new_shipment(run_id, subscriber_id, is_replacement=False, fulfill="QUEUED"):
    rec = base_record()
    rec.update({"run_id": run_id, "subscriber_id": subscriber_id, "wave_id": None,
                "fulfill_status": fulfill, "label_status": "NONE",
                "postage_cents": 0, "tracking_code": None,
                "is_replacement": is_replacement, "delivered_at": None})
    STORE["shipments"][rec["id"]] = rec
    return rec

# ============================================================ assembly runs
@bp.post("/assembly-runs")
def create_run():
    require_roles("WarehouseOps")
    b = body()
    plan_id = req_str(b, "plan_id")
    period = req_str(b, "period")
    get_or_404("plans", plan_id)
    if not valid_period(period):
        raise bad_request("period must be a YYYY-MM string")
    if any(r["plan_id"] == plan_id and r["period"] == period
           and r["status"] != "CANCELLED" for r in STORE["runs"].values()):
        raise conflict("ERR_RUN_PERIOD_CONFLICT",
                       "A non-CANCELLED run already exists for this plan and period")
    rec = base_record()
    rec.update({"plan_id": plan_id, "period": period, "planned_box_count": 0,
                "kitted_box_count": 0, "estimate_cents": 0, "status": "DRAFT",
                "locked_at": None})
    STORE["runs"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)

@bp.get("/assembly-runs/<rid>")
def get_run(rid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps",
                              "BillingAdmin")
    rec = get_or_404("runs", rid)
    check_own(uid, role, owner_of_run(rec))
    return ok(pub(rec))

@bp.get("/box-plans/<pid>/assembly-runs")
def list_plan_runs(pid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    plan = get_or_404("plans", pid)
    check_own(uid, role, owner_of_plan(plan))
    res = [r for r in STORE["runs"].values() if r["plan_id"] == pid]
    f_period = request.args.get("period")
    f_status = request.args.get("status")
    if f_period is not None:
        res = [r for r in res if r["period"] == f_period]
    if f_status is not None:
        res = [r for r in res if r["status"] == f_status]
    return list_resp(res, pub)

@bp.get("/assembly-runs/<rid>/shipments")
def list_run_shipments(rid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps",
                              "CustomerService")
    rec = get_or_404("runs", rid)
    check_own(uid, role, owner_of_run(rec))
    res = shipments_of_run(rid)
    f_ful = request.args.get("fulfill_status")
    f_lab = request.args.get("label_status")
    if f_ful is not None:
        res = [s for s in res if s["fulfill_status"] == f_ful]
    if f_lab is not None:
        res = [s for s in res if s["label_status"] == f_lab]
    return list_resp(res, pub)

@bp.get("/assembly-runs/<rid>/inventory-events")
def list_run_events(rid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    rec = get_or_404("runs", rid)
    check_own(uid, role, owner_of_run(rec))
    res = [e for e in STORE["events"].values() if e["run_id"] == rid]
    f_type = request.args.get("event_type")
    if f_type is not None:
        res = [e for e in res if e["event_type"] == f_type]
    return list_resp(res, pub)

@bp.post("/assembly-runs/<rid>/lock")
def lock_run(rid):
    require_roles("WarehouseOps")
    run = get_or_404("runs", rid)
    if run["status"] != "DRAFT":
        raise invalid_state_exc()
    plan = STORE["plans"][run["plan_id"]]
    if plan["status"] != "ACTIVE":
        raise conflict("ERR_PLAN_NOT_ACTIVE", "Plan is not ACTIVE")
    if not plan["active_revision_id"]:
        raise conflict("ERR_PLAN_HAS_NO_APPROVED_REVISION",
                       "Plan has no approved revision")
    actives = [s for s in subs_of_plan(plan["id"]) if s["status"] == "ACTIVE"]
    if not actives:
        raise conflict("ERR_RUN_EMPTY", "No ACTIVE subscribers for this plan")
    planned = len(actives)
    estimate = planned * plan["price_per_box_cents"]
    client = STORE["clients"][plan["client_id"]]
    if client["credit_balance_cents"] < estimate:
        raise conflict("ERR_INSUFFICIENT_CREDIT",
                       "Client wallet below run estimate")
    lines = lines_of_revision(plan["active_revision_id"])
    required = {}
    for line in lines:
        comp = STORE["components"][line["component_id"]]
        req = line["qty_per_box"] * planned
        required[comp["id"]] = req
        if comp_available(comp) < req:
            raise conflict("ERR_COMPONENT_SHORTAGE",
                           "Component available_units below required units")
    # --- apply atomically ---
    run["planned_box_count"] = planned
    run["estimate_cents"] = estimate
    run["locked_at"] = iso(clock())
    run["status"] = "LOCKED"
    touch(run)
    for line in lines:
        comp = STORE["components"][line["component_id"]]
        req = required[comp["id"]]
        append_event(comp["id"], run["id"], "RESERVE", req, None)
        comp["reserved_units"] += req
        touch(comp)
    for s in sorted(actives, key=lambda x: (x["_seq"], x["email"])):
        new_shipment(run["id"], s["id"])
    st = find_statement(client["id"], run["period"])
    if st is None:
        st = base_record()
        st.update({"client_id": client["id"], "period": run["period"],
                   "box_charge_cents": 0, "postage_cents": 0,
                   "refund_credit_cents": 0, "discount_pct": 0,
                   "adjustment_credit_cents": 0, "net_cents": 0,
                   "status": "PROVISIONAL"})
        computed = compute_statement(st, "provisional")
        st.update(computed)
        STORE["statements"][st["id"]] = st
    else:
        recompute_provisional(st)
    return ok(pub(run))

@bp.post("/assembly-runs/<rid>/start-kitting")
def start_kitting(rid):
    require_roles("WarehouseOps")
    run = get_or_404("runs", rid)
    if run["status"] != "LOCKED":
        raise invalid_state_exc()
    run["status"] = "KITTING"
    touch(run)
    return ok(pub(run))

@bp.post("/assembly-runs/<rid>/complete-kitting")
def complete_kitting(rid):
    require_roles("WarehouseOps")
    run = get_or_404("runs", rid)
    if run["status"] != "KITTING":
        raise invalid_state_exc()
    b = body()
    actual = req_int(b, "actual_kitted_count")
    if actual < 1:
        raise ApiError("ERR_INVALID_QUANTITY", 400,
                       "actual_kitted_count must be >= 1")
    if actual > run["planned_box_count"]:
        raise conflict("ERR_KIT_COUNT_MISMATCH",
                       "actual_kitted_count exceeds planned_box_count")
    plan = STORE["plans"][run["plan_id"]]
    lines = lines_of_revision(plan["active_revision_id"])
    first = run["kitted_box_count"] == 0
    new_commit = actual - run["kitted_box_count"]
    if not first:
        if actual < run["kitted_box_count"]:
            raise conflict("ERR_REWORK_REGRESS",
                           "Re-completion below previous kitted count")
        for line in lines:
            comp = STORE["components"][line["component_id"]]
            if comp_available(comp) < line["qty_per_box"] * new_commit:
                raise conflict("ERR_COMPONENT_SHORTAGE",
                               "Component available_units below required delta")
    # --- inventory effects ---
    if first:
        if new_commit > 0:
            for line in lines:
                comp = STORE["components"][line["component_id"]]
                qty = line["qty_per_box"] * new_commit
                append_event(comp["id"], run["id"], "COMMIT", -qty, None)
                comp["on_hand_units"] -= qty
                comp["reserved_units"] -= qty
                touch(comp)
        excess = run["planned_box_count"] - actual
        if excess > 0:
            for line in lines:
                comp = STORE["components"][line["component_id"]]
                qty = line["qty_per_box"] * excess
                append_event(comp["id"], run["id"], "RELEASE", -qty, None)
                comp["reserved_units"] -= qty
                touch(comp)
            # excess shipment selection (exactly once per run)
            cands = [s for s in shipments_of_run(run["id"])
                     if s["fulfill_status"] == "QUEUED"]
            cands.sort(key=lambda s: (-STORE["subscribers"][s["subscriber_id"]]["_seq"],
                                      STORE["subscribers"][s["subscriber_id"]]["email"]))
            for sh in cands[:excess]:
                sh["fulfill_status"] = "CANCELLED"
                touch(sh)
        for sh in shipments_of_run(run["id"]):
            if sh["fulfill_status"] == "QUEUED":
                sh["fulfill_status"] = "STAGED"
                touch(sh)
    elif new_commit > 0:
        for line in lines:
            comp = STORE["components"][line["component_id"]]
            qty = line["qty_per_box"] * new_commit
            append_event(comp["id"], run["id"], "COMMIT", -qty, None)
            comp["on_hand_units"] -= qty
            touch(comp)
    run["kitted_box_count"] = actual
    run["status"] = "KITTED"
    touch(run)
    return ok(pub(run))

@bp.post("/assembly-runs/<rid>/rework")
def rework_run(rid):
    require_roles("WarehouseOps")
    run = get_or_404("runs", rid)
    if run["status"] != "KITTED":
        raise invalid_state_exc()
    if any(s["fulfill_status"] in ("ASSIGNED", "MANIFESTED", "SHIPPED",
                                   "DELIVERED", "RETURNED")
           for s in shipments_of_run(rid)):
        raise conflict("ERR_RUN_HAS_COMMITTED_SHIPMENTS",
                       "Run has committed shipments")
    run["status"] = "KITTING"
    touch(run)
    return ok(pub(run))

@bp.post("/assembly-runs/<rid>/close")
def close_run(rid):
    require_roles("WarehouseOps")
    run = get_or_404("runs", rid)
    if run["status"] != "KITTED":
        raise invalid_state_exc()
    if any(s["fulfill_status"] in ("QUEUED", "STAGED", "ASSIGNED", "MANIFESTED")
           for s in shipments_of_run(rid)):
        raise conflict("ERR_RUN_HAS_OPEN_SHIPMENTS", "Run has open shipments")
    run["status"] = "CLOSED"
    touch(run)
    return ok(pub(run))

@bp.post("/assembly-runs/<rid>/cancel")
def cancel_run(rid):
    require_roles("WarehouseOps")
    run = get_or_404("runs", rid)
    if run["status"] not in ("DRAFT", "LOCKED"):
        raise invalid_state_exc()
    if run["status"] == "LOCKED":
        plan = STORE["plans"][run["plan_id"]]
        if plan.get("active_revision_id"):
            for line in lines_of_revision(plan["active_revision_id"]):
                comp = STORE["components"][line["component_id"]]
                qty = line["qty_per_box"] * run["planned_box_count"]
                if qty > 0:
                    append_event(comp["id"], run["id"], "RELEASE", -qty, None)
                    comp["reserved_units"] -= qty
                    touch(comp)
        for sh in shipments_of_run(rid):
            if sh["fulfill_status"] == "QUEUED":
                sh["fulfill_status"] = "CANCELLED"
                touch(sh)
    run["status"] = "CANCELLED"
    touch(run)
    return ok(pub(run))

# ============================================================ shipping waves
@bp.post("/shipping-waves")
def create_wave():
    require_roles("WarehouseOps")
    b = body()
    carrier = req_enum(b, "carrier", {"USPS", "UPS", "FEDEX"})
    service = req_enum(b, "service_level", {"GROUND", "EXPRESS"})
    start_raw = req_str(b, "pickup_start")
    end_raw = req_str(b, "pickup_end")
    start = parse_dt(start_raw)
    end = parse_dt(end_raw)
    if start is None or end is None:
        raise bad_request("pickup_start / pickup_end must be ISO 8601 timestamps")
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW", 400,
                       "pickup_end must be strictly after pickup_start")
    for w in STORE["waves"].values():
        if w["carrier"] != carrier or w["status"] == "CANCELLED":
            continue
        ws, we = parse_dt(w["pickup_start"]), parse_dt(w["pickup_end"])
        overlap = start < we and ws < end
        if overlap:
            raise conflict("ERR_WAVE_WINDOW_CONFLICT",
                           "Pickup window overlaps an existing wave")
        if ws >= end:
            gap = ws - end
        else:
            gap = start - we
        if gap < timedelta(minutes=30):
            raise conflict("ERR_WAVE_WINDOW_CONFLICT",
                           "Pickup window gap below 30 minutes")
    rec = base_record()
    rec.update({"carrier": carrier, "service_level": service,
                "pickup_start": iso(start), "pickup_end": iso(end),
                "status": "SCHEDULED"})
    STORE["waves"][rec["id"]] = rec
    return ok(ser_wave(rec), "object", 201)

@bp.get("/shipping-waves/<wid>")
def get_wave(wid):
    require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    rec = get_or_404("waves", wid)
    return ok(ser_wave(rec))

@bp.get("/shipping-waves/<wid>/shipments")
def list_wave_shipments(wid):
    require_roles("PlatformAdmin", "ClientOps", "WarehouseOps", "CustomerService")
    get_or_404("waves", wid)
    res = [s for s in STORE["shipments"].values() if s["wave_id"] == wid]
    f = request.args.get("fulfill_status")
    if f is not None:
        res = [s for s in res if s["fulfill_status"] == f]
    return list_resp(res, pub)

@bp.post("/shipping-waves/<wid>/assign-shipments")
def assign_shipments(wid):
    require_roles("WarehouseOps")
    wave = get_or_404("waves", wid)
    b = body()
    ids = req_field(b, "shipment_ids")
    if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
        raise bad_request("shipment_ids must be an array of strings")
    targets = [get_or_404("shipments", i) for i in ids]
    if wave["status"] != "SCHEDULED":
        raise invalid_state_exc("Wave is not SCHEDULED")
    for sh in targets:
        if sh["fulfill_status"] != "STAGED":
            raise invalid_state_exc("Shipment is not STAGED")
        if sh["label_status"] not in ("NONE", "VOIDED"):
            raise invalid_state_exc("Shipment label is not assignable")
        run = STORE["runs"][sh["run_id"]]
        if run["status"] not in ("KITTING", "KITTED", "CLOSED"):
            raise invalid_state_exc("Owning run is not in an assignable state")
    for sh in targets:
        if sh["fulfill_status"] == "STAGED":
            sh["fulfill_status"] = "ASSIGNED"
            sh["wave_id"] = wid
            touch(sh)
    return ok(ser_wave(wave))

@bp.post("/shipping-waves/<wid>/manifest")
def manifest_wave(wid):
    require_roles("WarehouseOps")
    wave = get_or_404("waves", wid)
    if wave["status"] != "SCHEDULED":
        raise invalid_state_exc()
    assigned = [s for s in STORE["shipments"].values()
                if s["wave_id"] == wid and s["fulfill_status"] == "ASSIGNED"]
    if not assigned:
        raise conflict("ERR_WAVE_EMPTY", "Wave has no assigned shipments")
    for sh in sorted(assigned, key=lambda s: s["_seq"]):
        run = STORE["runs"][sh["run_id"]]
        plan = STORE["plans"][run["plan_id"]]
        sub = STORE["subscribers"][sh["subscriber_id"]]
        sh["postage_cents"] = postage_for(wave, sub, plan)
        sh["label_status"] = "PURCHASED"
        sh["tracking_code"] = "TRK-" + uuid.uuid4().hex[:12].upper()
        sh["fulfill_status"] = "MANIFESTED"
        touch(sh)
    wave["status"] = "MANIFESTED"
    touch(wave)
    recompute_statements_for_shipments(assigned)
    return ok(ser_wave(wave))

@bp.post("/shipping-waves/<wid>/tender")
def tender_wave(wid):
    require_roles("WarehouseOps")
    wave = get_or_404("waves", wid)
    if wave["status"] != "MANIFESTED":
        raise invalid_state_exc()
    for sh in STORE["shipments"].values():
        if sh["wave_id"] == wid and sh["fulfill_status"] == "MANIFESTED":
            sh["fulfill_status"] = "SHIPPED"
            touch(sh)
    wave["status"] = "TENDERED"
    touch(wave)
    return ok(ser_wave(wave))

@bp.post("/shipping-waves/<wid>/cancel")
def cancel_wave(wid):
    require_roles("WarehouseOps")
    wave = get_or_404("waves", wid)
    if wave["status"] not in ("SCHEDULED", "MANIFESTED"):
        raise invalid_state_exc()
    affected = []
    for sh in STORE["shipments"].values():
        if sh["wave_id"] != wid:
            continue
        if sh["fulfill_status"] in ("ASSIGNED", "MANIFESTED"):
            sh["fulfill_status"] = "STAGED"
            sh["wave_id"] = None
            if sh["label_status"] == "PURCHASED":
                sh["label_status"] = "VOIDED"
            touch(sh)
            affected.append(sh)
    wave["status"] = "CANCELLED"
    touch(wave)
    recompute_statements_for_shipments(affected)
    return ok(ser_wave(wave))

# ============================================================ shipments
@bp.get("/shipments/<sid>")
def get_shipment(sid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps",
                              "CustomerService")
    rec = get_or_404("shipments", sid)
    check_own(uid, role, owner_of_shipment(rec))
    return ok(pub(rec))

@bp.post("/shipments/<sid>/cancel")
def cancel_shipment(sid):
    require_roles("WarehouseOps")
    rec = get_or_404("shipments", sid)
    if rec["fulfill_status"] not in ("QUEUED", "STAGED"):
        raise invalid_state_exc()
    rec["fulfill_status"] = "CANCELLED"
    touch(rec)
    return ok(pub(rec))

@bp.post("/shipments/<sid>/void-label")
def void_label(sid):
    require_roles("WarehouseOps")
    rec = get_or_404("shipments", sid)
    if not (rec["fulfill_status"] == "MANIFESTED" and rec["label_status"] == "PURCHASED"):
        raise conflict("ERR_LABEL_NOT_VOIDABLE",
                       "Label may only be voided while MANIFESTED and PURCHASED")
    rec["label_status"] = "VOIDED"
    touch(rec)
    recompute_statements_for_shipments([rec])
    return ok(pub(rec))

@bp.post("/shipments/<sid>/scan")
def scan_shipment(sid):
    require_roles("WarehouseOps")
    rec = get_or_404("shipments", sid)
    b = body()
    scan_type = req_enum(b, "scan_type", {"DELIVERED", "RETURNED"})
    if rec["fulfill_status"] != "SHIPPED":
        raise invalid_state_exc()
    if scan_type == "DELIVERED":
        rec["fulfill_status"] = "DELIVERED"
        rec["delivered_at"] = iso(clock())
    else:
        rec["fulfill_status"] = "RETURNED"
    touch(rec)
    return ok(pub(rec))

# ============================================================ return cases
@bp.post("/return-cases")
def create_return_case():
    require_roles("CustomerService")
    b = body()
    shipment_id = req_str(b, "shipment_id")
    reason = req_enum(b, "reason", {"DAMAGED", "LOST", "WRONG_ITEM", "OTHER"})
    resolution = req_enum(b, "requested_resolution", {"REPLACE", "REFUND"})
    get_or_404("shipments", shipment_id)
    rec = base_record()
    rec.update({"shipment_id": shipment_id, "reason": reason,
                "requested_resolution": resolution, "status": "REQUESTED",
                "resolution_applied": None, "credit_cents": 0,
                "replacement_shipment_id": None})
    STORE["return_cases"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)

@bp.get("/return-cases")
def list_return_cases():
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps",
                              "CustomerService")
    res = list(STORE["return_cases"].values())
    if role == "ClientOps":
        res = [rc for rc in res if owner_of_case(rc) == uid]
    f_ship = request.args.get("shipment_id")
    f_repl = request.args.get("replacement_shipment_id")
    f_status = request.args.get("status")
    if f_ship is not None:
        res = [rc for rc in res if rc["shipment_id"] == f_ship]
    if f_repl is not None:
        res = [rc for rc in res if rc["replacement_shipment_id"] == f_repl]
    if f_status is not None:
        res = [rc for rc in res if rc["status"] == f_status]
    return list_resp(res, pub)

@bp.get("/return-cases/<rcid>")
def get_return_case(rcid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps",
                              "CustomerService")
    rec = get_or_404("return_cases", rcid)
    check_own(uid, role, owner_of_case(rec))
    return ok(pub(rec))

@bp.post("/return-cases/<rcid>/approve")
def approve_return(rcid):
    require_roles("CustomerService")
    rec = get_or_404("return_cases", rcid)
    if rec["status"] != "REQUESTED":
        raise invalid_state_exc()
    sh = STORE["shipments"][rec["shipment_id"]]
    if sh["fulfill_status"] != "DELIVERED":
        raise conflict("ERR_SHIPMENT_NOT_DELIVERED", "Shipment is not DELIVERED")
    delivered = parse_dt(sh["delivered_at"])
    if clock() > delivered + timedelta(days=30):
        raise conflict("ERR_RETURN_WINDOW_EXPIRED",
                       "Return window of 30 days has expired")
    rec["status"] = "APPROVED"
    touch(rec)
    return ok(pub(rec))

@bp.post("/return-cases/<rcid>/reject")
def reject_return(rcid):
    require_roles("CustomerService")
    rec = get_or_404("return_cases", rcid)
    if rec["status"] != "REQUESTED":
        raise invalid_state_exc()
    rec["status"] = "REJECTED"
    touch(rec)
    return ok(pub(rec))

@bp.post("/return-cases/<rcid>/receive")
def receive_return(rcid):
    require_roles("WarehouseOps")
    rec = get_or_404("return_cases", rcid)
    if rec["status"] != "APPROVED":
        raise invalid_state_exc()
    rec["status"] = "RECEIVED"
    touch(rec)
    return ok(pub(rec))

@bp.post("/return-cases/<rcid>/resolve")
def resolve_return(rcid):
    require_roles("CustomerService")
    rec = get_or_404("return_cases", rcid)
    if rec["status"] != "RECEIVED":
        raise invalid_state_exc()
    sh = STORE["shipments"][rec["shipment_id"]]
    run = STORE["runs"][sh["run_id"]]
    plan = STORE["plans"][run["plan_id"]]
    if rec["requested_resolution"] == "REPLACE":
        lines = lines_of_revision(plan["active_revision_id"]) if plan.get("active_revision_id") else []
        for line in lines:
            comp = STORE["components"][line["component_id"]]
            if comp_available(comp) < line["qty_per_box"]:
                raise conflict("ERR_COMPONENT_SHORTAGE",
                               "Component available_units below required units")
        repl = new_shipment(sh["run_id"], sh["subscriber_id"],
                            is_replacement=True, fulfill="STAGED")
        for line in lines:
            comp = STORE["components"][line["component_id"]]
            qty = line["qty_per_box"]
            append_event(comp["id"], sh["run_id"], "COMMIT", -qty, None)
            comp["on_hand_units"] -= qty
            touch(comp)
        rec["replacement_shipment_id"] = repl["id"]
        rec["resolution_applied"] = "REPLACED"
    else:
        rec["credit_cents"] = plan["price_per_box_cents"]
        rec["resolution_applied"] = "REFUNDED"
    rec["status"] = "RESOLVED"
    touch(rec)
    if rec["resolution_applied"] == "REFUNDED":
        st = statement_for_run(run)
        if st is not None:
            recompute_provisional(st)
    return ok(pub(rec))

# ============================================================ billing statements
@bp.get("/billing-statements/<sid>")
def get_statement(sid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "BillingAdmin")
    rec = get_or_404("statements", sid)
    check_own(uid, role, rec["client_id"])
    return ok(pub(rec))

@bp.post("/billing-statements/<sid>/finalize")
def finalize_statement(sid):
    require_roles("BillingAdmin")
    rec = get_or_404("statements", sid)
    if rec["status"] != "PROVISIONAL":
        raise invalid_state_exc()
    _, end = period_bounds(rec["period"])
    if clock() < end:
        raise conflict("ERR_STATEMENT_PERIOD_OPEN",
                       "Statement period has not ended")
    computed = compute_statement(rec, "final")
    client = STORE["clients"][rec["client_id"]]
    if client["credit_balance_cents"] < computed["net_cents"]:
        raise conflict("ERR_INSUFFICIENT_CREDIT",
                       "Client wallet below final net amount")
    rec.update(computed)
    rec["status"] = "FINALIZED"
    touch(rec)
    client["credit_balance_cents"] -= rec["net_cents"]
    touch(client)
    return ok(pub(rec))

@bp.post("/billing-statements/<sid>/dispute")
def dispute_statement(sid):
    uid, role = require_roles("ClientOps")
    rec = get_or_404("statements", sid)
    check_own(uid, role, rec["client_id"])
    if rec["status"] != "FINALIZED":
        raise invalid_state_exc()
    client = STORE["clients"][rec["client_id"]]
    client["credit_balance_cents"] += rec["net_cents"]
    touch(client)
    rec["status"] = "DISPUTED"
    touch(rec)
    return ok(pub(rec))

@bp.post("/billing-statements/<sid>/resolve-dispute")
def resolve_dispute(sid):
    require_roles("BillingAdmin")
    rec = get_or_404("statements", sid)
    if rec["status"] != "DISPUTED":
        raise invalid_state_exc()
    b = body()
    adj = req_int(b, "adjustment_credit_cents")
    if adj < 0 or adj > rec["net_cents"]:
        raise ApiError("ERR_INVALID_QUANTITY", 400,
                       "adjustment_credit_cents must be between 0 and net_cents")
    rec["adjustment_credit_cents"] = adj
    rec["net_cents"] -= adj
    client = STORE["clients"][rec["client_id"]]
    client["credit_balance_cents"] -= rec["net_cents"]
    touch(client)
    rec["status"] = "FINALIZED"
    touch(rec)
    return ok(pub(rec))

@bp.post("/billing-statements/<sid>/mark-paid")
def mark_paid(sid):
    require_roles("BillingAdmin")
    rec = get_or_404("statements", sid)
    if rec["status"] != "FINALIZED":
        raise invalid_state_exc()
    rec["status"] = "PAID"
    touch(rec)
    return ok(pub(rec))
