"""Appliance & Electronics Installation Marketplace API — entry point + routes."""
import os
from datetime import timedelta

from flask import Flask, request

import common
from common import (
    db, clock, LOCK, err, success, error_response, ApiError,
    authenticate, get_body, require_fields, is_int, get_or_404,
    new_entity, touch, paginate, parse_iso, iso_ms, CATEGORIES,
    VETTING_VALID_DAYS,
)
import calc

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_VALIDATION", 404, "Not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_VALIDATION", 405, "Method not allowed.")


# ===========================================================================
# Helpers
# ===========================================================================
def validate_category(value, field="category"):
    if value not in CATEGORIES:
        err("ERR_VALIDATION", f"Invalid {field}: {value}")


def require_positive_int(body, name, minimum=0):
    v = body.get(name)
    if not is_int(v):
        err("ERR_VALIDATION", f"{name} must be an integer.")
    if v < minimum:
        err("ERR_VALIDATION", f"{name} must be >= {minimum}.")
    return v


def unique_check(collection, field, value, err_msg):
    for e in collection.values():
        if e.get(field) == value:
            err("ERR_VALIDATION", err_msg)


def list_filter(collection, filters):
    """Return rows matching all provided (field,value) filters (value not None)."""
    rows = []
    for e in collection.values():
        ok = True
        for field, val in filters.items():
            if val is not None and e.get(field) != val:
                ok = False
                break
        if ok:
            rows.append(e)
    return rows


# ===========================================================================
# Clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    with LOCK:
        authenticate(["PlatformAdmin"])
        body = get_body()
        require_fields(body, ["to_iso8601"])
        try:
            dt = parse_iso(body["to_iso8601"])
        except ValueError:
            err("ERR_VALIDATION", "to_iso8601 must be an ISO8601 datetime.")
        clock.set(dt)
        return success({"current_utc": iso_ms(clock.now())}, 200)


# ===========================================================================
# Retailer
# ===========================================================================
@app.route("/retailers", methods=["POST"])
def create_retailer():
    with LOCK:
        authenticate(["PlatformAdmin"])
        body = get_body()
        require_fields(body, ["name", "commission_rate_bps"])
        rate = require_positive_int(body, "commission_rate_bps", 0)
        if rate > 10000:
            err("ERR_VALIDATION", "commission_rate_bps must be 0..10000.")
        ent = new_entity(
            name=body["name"],
            status="ACTIVE",
            commission_rate_bps=rate,
            settlement_balance_cents=0,
        )
        db.retailers[ent["id"]] = ent
        return success(ent, 201)


@app.route("/retailers/<rid>", methods=["GET"])
def get_retailer(rid):
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer"])
        ent = get_or_404(db.retailers, rid, "ERR_RETAILER_NOT_FOUND")
        return success(ent, 200)


@app.route("/retailers/<rid>/status", methods=["PATCH"])
def set_retailer_status(rid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        ent = get_or_404(db.retailers, rid, "ERR_RETAILER_NOT_FOUND")
        body = get_body()
        require_fields(body, ["status"])
        status = body["status"]
        if status not in ("ACTIVE", "SUSPENDED"):
            err("ERR_VALIDATION", "status must be ACTIVE or SUSPENDED.")
        ent["status"] = status
        touch(ent)
        return success(ent, 200)


# ===========================================================================
# ServiceZone
# ===========================================================================
@app.route("/service-zones", methods=["POST"])
def create_zone():
    with LOCK:
        authenticate(["PlatformAdmin"])
        body = get_body()
        require_fields(body, ["zone_code", "name", "max_concurrent_appointments"])
        cap = require_positive_int(body, "max_concurrent_appointments", 1)
        coverage = body.get("coverage_active", True)
        if not isinstance(coverage, bool):
            err("ERR_VALIDATION", "coverage_active must be a boolean.")
        unique_check(db.service_zones, "zone_code", body["zone_code"],
                     "zone_code must be unique.")
        ent = new_entity(
            zone_code=body["zone_code"],
            name=body["name"],
            max_concurrent_appointments=cap,
            coverage_active=coverage,
        )
        db.service_zones[ent["id"]] = ent
        return success(ent, 201)


@app.route("/service-zones/<zid>", methods=["GET"])
def get_zone(zid):
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer", "Pro"])
        ent = get_or_404(db.service_zones, zid, "ERR_SERVICE_ZONE_NOT_FOUND")
        return success(ent, 200)


# ===========================================================================
# Customer
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer"])
        body = get_body()
        require_fields(body, ["full_name", "email", "phone", "address_line"])
        ent = new_entity(
            full_name=body["full_name"],
            email=body["email"],
            phone=body["phone"],
            address_line=body["address_line"],
        )
        db.customers[ent["id"]] = ent
        return success(ent, 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer", "Customer"])
        ent = get_or_404(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
        return success(ent, 200)


# ===========================================================================
# Pro
# ===========================================================================
@app.route("/pros", methods=["POST"])
def create_pro():
    with LOCK:
        authenticate(["PlatformAdmin"])
        body = get_body()
        # existence of referenced zone (priority 4) before body wellformed
        zone_id = body.get("service_zone_id")
        if zone_id is not None:
            get_or_404(db.service_zones, zone_id, "ERR_SERVICE_ZONE_NOT_FOUND")
        require_fields(body, ["full_name", "email", "service_zone_id", "skills"])
        skills = body["skills"]
        if (not isinstance(skills, list) or len(skills) == 0
                or any(s not in CATEGORIES for s in skills)):
            err("ERR_VALIDATION", "skills must be a non-empty subset of install categories.")
        ent = new_entity(
            full_name=body["full_name"],
            email=body["email"],
            service_zone_id=zone_id,
            skills=list(skills),
            pending_payout_cents=0,
            reserved_slot_count=0,
            rating_sum=0,
            rating_count=0,
            rating_avg=0,
        )
        db.pros[ent["id"]] = ent
        return success(ent, 201)


@app.route("/pros/<pid>", methods=["GET"])
def get_pro(pid):
    with LOCK:
        authenticate(["PlatformAdmin", "Pro"])
        ent = get_or_404(db.pros, pid, "ERR_PRO_NOT_FOUND")
        return success(ent, 200)


@app.route("/pros", methods=["GET"])
def list_pros():
    with LOCK:
        authenticate(["PlatformAdmin"])
        rows = list_filter(db.pros, {"service_zone_id": request.args.get("service_zone_id")})
        window, pg = paginate(rows)
        return success(window, 200, response_type="array", pagination=pg)


# ===========================================================================
# ProApplication
# ===========================================================================
@app.route("/pros/<pid>/applications", methods=["POST"])
def create_application(pid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        get_or_404(db.pros, pid, "ERR_PRO_NOT_FOUND")
        body = get_body()
        require_fields(body, ["background_check_ref"])
        ent = new_entity(
            pro_id=pid,
            status="PENDING_REVIEW",
            background_check_ref=body["background_check_ref"],
            approved_at=None,
            expires_at=None,
        )
        db.applications[ent["id"]] = ent
        return success(ent, 201)


@app.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    with LOCK:
        authenticate(["PlatformAdmin", "Pro"])
        ent = get_or_404(db.applications, aid, "ERR_APPLICATION_NOT_FOUND")
        return success(ent, 200)


@app.route("/applications", methods=["GET"])
def list_applications():
    with LOCK:
        authenticate(["PlatformAdmin", "Pro"])
        rows = list_filter(db.applications, {"pro_id": request.args.get("pro_id")})
        window, pg = paginate(rows)
        return success(window, 200, response_type="array", pagination=pg)


def _app_transition(aid, valid_from, terminal_states):
    ent = get_or_404(db.applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if ent["status"] in terminal_states:
        err("ERR_ALREADY_TERMINAL")
    if ent["status"] != valid_from:
        err("ERR_INVALID_STATE")
    return ent


APP_TERMINAL = ("REJECTED", "EXPIRED")


@app.route("/applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        ent = _app_transition(aid, "PENDING_REVIEW", APP_TERMINAL)
        now = clock.now()
        ent["status"] = "APPROVED"
        ent["approved_at"] = now
        ent["expires_at"] = now + timedelta(days=VETTING_VALID_DAYS)
        touch(ent)
        return success(ent, 200)


@app.route("/applications/<aid>/reject", methods=["POST"])
def reject_application(aid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        ent = _app_transition(aid, "PENDING_REVIEW", APP_TERMINAL)
        ent["status"] = "REJECTED"
        touch(ent)
        return success(ent, 200)


@app.route("/applications/<aid>/suspend", methods=["POST"])
def suspend_application(aid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        ent = _app_transition(aid, "APPROVED", APP_TERMINAL)
        ent["status"] = "SUSPENDED"
        touch(ent)
        return success(ent, 200)


@app.route("/applications/<aid>/reinstate", methods=["POST"])
def reinstate_application(aid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        ent = _app_transition(aid, "SUSPENDED", APP_TERMINAL)
        ent["status"] = "APPROVED"
        touch(ent)
        return success(ent, 200)


# ===========================================================================
# InstallTask
# ===========================================================================
@app.route("/install-tasks", methods=["POST"])
def create_install_task():
    with LOCK:
        authenticate(["PlatformAdmin"])
        body = get_body()
        require_fields(body, ["task_code", "name", "category", "required_skill",
                              "base_price_cents", "estimated_minutes", "warranty_days"])
        validate_category(body["category"], "category")
        validate_category(body["required_skill"], "required_skill")
        base = require_positive_int(body, "base_price_cents", 0)
        est = require_positive_int(body, "estimated_minutes", 1)
        warranty = require_positive_int(body, "warranty_days", 0)
        unique_check(db.install_tasks, "task_code", body["task_code"],
                     "task_code must be unique.")
        ent = new_entity(
            task_code=body["task_code"],
            name=body["name"],
            category=body["category"],
            required_skill=body["required_skill"],
            base_price_cents=base,
            estimated_minutes=est,
            warranty_days=warranty,
        )
        db.install_tasks[ent["id"]] = ent
        return success(ent, 201)


@app.route("/install-tasks/<tid>", methods=["GET"])
def get_install_task(tid):
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer"])
        ent = get_or_404(db.install_tasks, tid, "ERR_INSTALL_TASK_NOT_FOUND")
        return success(ent, 200)


# ===========================================================================
# AddOn
# ===========================================================================
@app.route("/add-ons", methods=["POST"])
def create_addon():
    with LOCK:
        authenticate(["PlatformAdmin"])
        body = get_body()
        require_fields(body, ["addon_code", "name", "category", "price_cents"])
        validate_category(body["category"], "category")
        price = require_positive_int(body, "price_cents", 0)
        unique_check(db.addons, "addon_code", body["addon_code"],
                     "addon_code must be unique.")
        ent = new_entity(
            addon_code=body["addon_code"],
            name=body["name"],
            category=body["category"],
            price_cents=price,
        )
        db.addons[ent["id"]] = ent
        return success(ent, 201)


@app.route("/add-ons/<aid>", methods=["GET"])
def get_addon(aid):
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer"])
        ent = get_or_404(db.addons, aid, "ERR_ADDON_NOT_FOUND")
        return success(ent, 200)


# ===========================================================================
# WorkOrder helpers
# ===========================================================================
WO_TERMINAL = ("CANCELLED", "CLOSED")
BUFFER = timedelta(minutes=common.TRAVEL_BUFFER_MINUTES)


def active_assignment(wo):
    active = [a for a in db.assignments.values()
              if a["work_order_id"] == wo["id"] and a["status"] in ("OFFERED", "ACCEPTED")]
    if not active:
        return None
    return max(active, key=lambda a: a["_seq"])


def payout_for_wo(wo):
    rows = [p for p in db.payouts.values() if p["work_order_id"] == wo["id"]]
    if not rows:
        return None
    return max(rows, key=lambda p: p["_seq"])


def charge_entry_for_wo(wo):
    rows = [e for e in db.settlement_entries.values()
            if e["work_order_id"] == wo["id"] and e["entry_type"] == "CHARGE"]
    if not rows:
        return None
    return max(rows, key=lambda e: e["_seq"])


def approved_application(pro):
    for a in db.applications.values():
        if a["pro_id"] == pro["id"] and a["status"] == "APPROVED":
            return a
    return None


def _overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def has_valid_vetting(pro, now):
    a = approved_application(pro)
    return a is not None and a["expires_at"] is not None and now <= a["expires_at"]


def pro_has_accepted_conflict(pro, start, end, exclude_id=None, exclude_wo_id=None):
    for a in db.assignments.values():
        if a["pro_id"] != pro["id"] or a["status"] != "ACCEPTED":
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if exclude_wo_id is not None and a["work_order_id"] == exclude_wo_id:
            continue
        if _overlap(start - BUFFER, end + BUFFER, a["appointment_start"], a["appointment_end"]):
            return True
    return False


def zone_capacity_exceeded(zone_id, start, end, exclude_id=None, exclude_wo_id=None):
    zone = db.service_zones.get(zone_id)
    if zone is None:
        return False
    count = 0
    for a in db.assignments.values():
        if a["status"] != "ACCEPTED":
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if exclude_wo_id is not None and a["work_order_id"] == exclude_wo_id:
            continue
        wo = db.work_orders.get(a["work_order_id"])
        if wo is None or wo["service_zone_id"] != zone_id:
            continue
        if _overlap(start, end, a["appointment_start"], a["appointment_end"]):
            count += 1
    return count >= zone["max_concurrent_appointments"]


def eligible_pros(wo, task):
    now = clock.now()
    result = []
    for pro in db.pros.values():
        if task["required_skill"] not in pro["skills"]:
            continue
        if pro["service_zone_id"] != wo["service_zone_id"]:
            continue
        if not has_valid_vetting(pro, now):
            continue
        if pro_has_accepted_conflict(pro, wo["scheduled_start"], wo["scheduled_end"],
                                     exclude_wo_id=wo["id"]):
            continue
        result.append(pro)
    result.sort(key=lambda p: (-p["rating_avg"], p["pending_payout_cents"],
                               p["created_at"], p["_seq"]))
    return result


# ===========================================================================
# WorkOrder CRUD
# ===========================================================================
@app.route("/work-orders", methods=["POST"])
def create_work_order():
    with LOCK:
        uid, role = authenticate(["Retailer"])
        body = get_body()
        rid = body.get("retailer_id")
        if rid is not None and rid != uid:
            err("ERR_UNAUTHORIZED", "Retailer may only create orders for itself.")
        # existence (left-to-right)
        if rid is not None:
            get_or_404(db.retailers, rid, "ERR_RETAILER_NOT_FOUND")
        cid = body.get("customer_id")
        if cid is not None:
            get_or_404(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
        tid = body.get("install_task_id")
        if tid is not None:
            get_or_404(db.install_tasks, tid, "ERR_INSTALL_TASK_NOT_FOUND")
        zid = body.get("service_zone_id")
        if zid is not None:
            get_or_404(db.service_zones, zid, "ERR_SERVICE_ZONE_NOT_FOUND")
        require_fields(body, ["retailer_id", "customer_id", "install_task_id",
                              "service_zone_id", "product_sku", "product_category"])
        validate_category(body["product_category"], "product_category")
        task = db.install_tasks[tid]
        if body["product_category"] != task["category"]:
            err("ERR_VALIDATION", "product_category must equal the install task category.")
        ent = new_entity(
            retailer_id=rid,
            customer_id=cid,
            install_task_id=tid,
            service_zone_id=zid,
            appointment_pro_id=None,
            product_sku=body["product_sku"],
            product_category=body["product_category"],
            scope_notes=body.get("scope_notes"),
            selected_addon_ids=[],
            status="DRAFT",
            scheduled_start=None,
            scheduled_end=None,
            quoted_price_cents=0,
            final_price_cents=0,
            completed_at=None,
            warranty_expires_at=None,
            redo_count=0,
            reason=None,
        )
        db.work_orders[ent["id"]] = ent
        return success(ent, 201)


@app.route("/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer", "Pro", "Customer"])
        ent = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        return success(ent, 200)


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer", "Pro"])
        a = request.args
        rows = list_filter(db.work_orders, {
            "retailer_id": a.get("retailer_id"),
            "customer_id": a.get("customer_id"),
            "install_task_id": a.get("install_task_id"),
            "service_zone_id": a.get("service_zone_id"),
            "appointment_pro_id": a.get("appointment_pro_id"),
        })
        window, pg = paginate(rows)
        return success(window, 200, response_type="array", pagination=pg)


@app.route("/work-orders/<wid>/schedule", methods=["POST"])
def schedule_work_order(wid):
    with LOCK:
        uid, role = authenticate(["Retailer"])
        wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        if wo["retailer_id"] != uid:
            err("ERR_UNAUTHORIZED", "Retailer does not own this work order.")
        body = get_body()
        addon_ids = body.get("selected_addon_ids")
        if addon_ids is None:
            addon_ids = []
        if not isinstance(addon_ids, list):
            err("ERR_VALIDATION", "selected_addon_ids must be an array.")
        # addon existence (priority 4)
        for aid in addon_ids:
            get_or_404(db.addons, aid, "ERR_ADDON_NOT_FOUND")
        # body wellformed (priority 5)
        require_fields(body, ["scheduled_start", "scheduled_end"])
        try:
            start = parse_iso(body["scheduled_start"])
            end = parse_iso(body["scheduled_end"])
        except ValueError:
            err("ERR_VALIDATION", "scheduled_start/scheduled_end must be ISO8601 datetimes.")
        # appointment window (priority 6)
        if not (start < end):
            err("ERR_INVALID_APPOINTMENT_WINDOW", "scheduled_start must be before scheduled_end.")
        # state (priority 7/8)
        if wo["status"] in WO_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if wo["status"] != "DRAFT":
            err("ERR_INVALID_STATE")
        # retailer suspended (priority 9)
        retailer = db.retailers[wo["retailer_id"]]
        if retailer["status"] != "ACTIVE":
            err("ERR_RETAILER_SUSPENDED")
        # zone coverage (priority 10)
        zone = db.service_zones[wo["service_zone_id"]]
        if not zone["coverage_active"]:
            err("ERR_ZONE_COVERAGE_INACTIVE")
        # addon category (priority 11)
        task = db.install_tasks[wo["install_task_id"]]
        for aid in addon_ids:
            if db.addons[aid]["category"] != task["category"]:
                err("ERR_ADDON_CATEGORY_MISMATCH")
        # apply
        wo["scheduled_start"] = start
        wo["scheduled_end"] = end
        wo["selected_addon_ids"] = list(addon_ids)
        wo["quoted_price_cents"] = task["base_price_cents"] + sum(
            db.addons[aid]["price_cents"] for aid in addon_ids)
        wo["status"] = "SCHEDULED"
        touch(wo)
        return success(wo, 200)


@app.route("/work-orders/<wid>/dispatch", methods=["POST"])
def dispatch_work_order(wid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        body = get_body()
        require_fields(body, ["expected_work_order_version"])
        ev = body["expected_work_order_version"]
        if not is_int(ev):
            err("ERR_VALIDATION", "expected_work_order_version must be an integer.")
        # state
        if wo["status"] in WO_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if wo["status"] not in ("SCHEDULED", "REDO_REQUESTED"):
            err("ERR_INVALID_STATE")
        # OCC
        if ev != wo["version"]:
            err("ERR_STALE_VERSION")
        # selection
        task = db.install_tasks[wo["install_task_id"]]
        candidates = eligible_pros(wo, task)
        if not candidates:
            err("ERR_NO_ELIGIBLE_PRO")
        pro = candidates[0]
        wo["appointment_pro_id"] = pro["id"]
        asg = new_entity(
            work_order_id=wo["id"],
            pro_id=pro["id"],
            status="OFFERED",
            appointment_start=wo["scheduled_start"],
            appointment_end=wo["scheduled_end"],
            offered_at=clock.now(),
            responded_at=None,
        )
        db.assignments[asg["id"]] = asg
        wo["status"] = "DISPATCHED"
        touch(wo)  # increments WorkOrder.version by 1
        calc.recompute_pro(pro)
        return success(wo, 200)


@app.route("/work-orders/<wid>/start", methods=["POST"])
def start_work_order(wid):
    with LOCK:
        uid, role = authenticate(["Pro"])
        wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        if wo["appointment_pro_id"] != uid:
            err("ERR_UNAUTHORIZED", "Caller is not the appointment pro.")
        if wo["status"] in WO_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if wo["status"] != "DISPATCHED":
            err("ERR_INVALID_STATE")
        asg = active_assignment(wo)
        if asg is None or asg["status"] != "ACCEPTED":
            err("ERR_INVALID_STATE")
        wo["status"] = "IN_PROGRESS"
        touch(wo)
        return success(wo, 200)


@app.route("/work-orders/<wid>/parts", methods=["POST"])
def add_part(wid):
    with LOCK:
        uid, role = authenticate(["Pro"])
        wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        if wo["appointment_pro_id"] != uid:
            err("ERR_UNAUTHORIZED", "Caller is not the appointment pro.")
        body = get_body()
        require_fields(body, ["name", "unit_cost_cents", "quantity", "markup_bps"])
        unit = require_positive_int(body, "unit_cost_cents", 0)
        qty = require_positive_int(body, "quantity", 1)
        markup = require_positive_int(body, "markup_bps", 0)
        if markup > 20000:
            err("ERR_VALIDATION", "markup_bps must be 0..20000.")
        if wo["status"] in WO_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if wo["status"] != "IN_PROGRESS":
            err("ERR_INVALID_STATE")
        line = common.rhu(unit * qty * (10000 + markup), 10000)
        part = new_entity(
            work_order_id=wo["id"],
            name=body["name"],
            unit_cost_cents=unit,
            quantity=qty,
            markup_bps=markup,
            line_billed_cents=line,
        )
        db.parts[part["id"]] = part
        return success(part, 201)


@app.route("/work-orders/<wid>/parts", methods=["GET"])
def list_parts(wid):
    with LOCK:
        authenticate(["PlatformAdmin", "Pro", "Retailer"])
        get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        rows = [p for p in db.parts.values() if p["work_order_id"] == wid]
        window, pg = paginate(rows)
        return success(window, 200, response_type="array", pagination=pg)


@app.route("/work-orders/<wid>/complete", methods=["POST"])
def complete_work_order(wid):
    with LOCK:
        uid, role = authenticate(["Pro"])
        wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        if wo["appointment_pro_id"] != uid:
            err("ERR_UNAUTHORIZED", "Caller is not the appointment pro.")
        if wo["status"] in WO_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if wo["status"] != "IN_PROGRESS":
            err("ERR_INVALID_STATE")
        now = clock.now()
        if now < wo["scheduled_start"]:
            err("ERR_APPOINTMENT_NOT_STARTED")
        task = db.install_tasks[wo["install_task_id"]]
        wo["final_price_cents"] = calc.work_order_final_price(wo, task)
        wo["completed_at"] = now
        wo["warranty_expires_at"] = now + timedelta(days=task["warranty_days"])
        existing = payout_for_wo(wo)
        if existing is None:
            money = calc.payout_money_fields(wo, task)
            payout = new_entity(
                work_order_id=wo["id"],
                pro_id=wo["appointment_pro_id"],
                retailer_id=wo["retailer_id"],
                status="PENDING",
                **money,
            )
            db.payouts[payout["id"]] = payout
            retailer = db.retailers[wo["retailer_id"]]
            referral = calc.referral_fee_cents(task, retailer)
            entry = new_entity(
                retailer_id=wo["retailer_id"],
                work_order_id=wo["id"],
                payout_record_id=payout["id"],
                entry_type="CHARGE",
                amount_cents=wo["final_price_cents"] - referral,
                status="PENDING",
                settled_at=None,
            )
            db.settlement_entries[entry["id"]] = entry
            calc.recompute_retailer(retailer)
            calc.recompute_pro(db.pros[wo["appointment_pro_id"]])
        elif existing["status"] == "HELD":
            # redo re-completion: held payout returns to PENDING (no new payout/entry)
            existing["status"] = "PENDING"
            touch(existing)
            calc.recompute_pro(db.pros[existing["pro_id"]])
            if wo["appointment_pro_id"] != existing["pro_id"]:
                calc.recompute_pro(db.pros[wo["appointment_pro_id"]])
        wo["status"] = "COMPLETED"
        touch(wo)
        return success(wo, 200)


@app.route("/work-orders/<wid>/request-redo", methods=["POST"])
def request_redo(wid):
    with LOCK:
        uid, role = authenticate(["Customer"])
        wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        if wo["customer_id"] != uid:
            err("ERR_UNAUTHORIZED", "Caller does not own this work order.")
        if wo["status"] in WO_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if wo["status"] != "COMPLETED":
            err("ERR_INVALID_STATE")
        now = clock.now()
        if now > wo["warranty_expires_at"]:
            err("ERR_WARRANTY_EXPIRED")
        wo["redo_count"] += 1
        wo["status"] = "REDO_REQUESTED"
        touch(wo)
        payout = payout_for_wo(wo)
        if payout is not None and payout["status"] == "PENDING":
            payout["status"] = "HELD"
            touch(payout)
        calc.recompute_pro(db.pros[wo["appointment_pro_id"]])
        return success(wo, 200)


@app.route("/work-orders/<wid>/close", methods=["POST"])
def close_work_order(wid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        if wo["status"] in WO_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if wo["status"] != "COMPLETED":
            err("ERR_INVALID_STATE")
        now = clock.now()
        if not (now > wo["warranty_expires_at"]):
            err("ERR_INVALID_STATE", "Warranty window has not yet elapsed.")
        payout = payout_for_wo(wo)
        if payout is not None and payout["status"] == "PENDING":
            payout["status"] = "RELEASED"
            payout["payout_cents"] = max(
                0, payout["payout_cents"] - common.REDO_PENALTY_CENTS * wo["redo_count"])
            touch(payout)
        wo["status"] = "CLOSED"
        touch(wo)
        if wo["appointment_pro_id"] is not None:
            calc.recompute_pro(db.pros[wo["appointment_pro_id"]])
        return success(wo, 200)


@app.route("/work-orders/<wid>/cancel", methods=["POST"])
def cancel_work_order(wid):
    with LOCK:
        uid, role = authenticate(["PlatformAdmin", "Retailer"])
        wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        if role == "Retailer" and wo["retailer_id"] != uid:
            err("ERR_UNAUTHORIZED", "Retailer does not own this work order.")
        body = get_body()
        reason = body.get("reason")
        if wo["status"] in WO_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if role == "Retailer":
            valid_from = ("DRAFT", "SCHEDULED")
        else:
            valid_from = ("DRAFT", "SCHEDULED", "DISPATCHED", "COMPLETED")
        if wo["status"] not in valid_from:
            err("ERR_INVALID_STATE")
        prev = wo["status"]
        wo["status"] = "CANCELLED"
        wo["reason"] = reason
        if prev == "DISPATCHED":
            asg = active_assignment(wo)
            if asg is not None:
                asg["status"] = "CANCELLED"
                touch(asg)
            if wo["appointment_pro_id"] is not None:
                calc.recompute_pro(db.pros[wo["appointment_pro_id"]])
        elif prev == "COMPLETED":
            pro_id = wo["appointment_pro_id"]
            payout = payout_for_wo(wo)
            if payout is not None and payout["status"] in ("PENDING", "HELD"):
                payout["status"] = "REVERSED"
                touch(payout)
            retailer = db.retailers[wo["retailer_id"]]
            charge = charge_entry_for_wo(wo)
            if charge is not None:
                if charge["status"] == "PENDING":
                    charge["status"] = "REVERSED"
                    touch(charge)
                elif charge["status"] == "SETTLED":
                    rev = new_entity(
                        retailer_id=wo["retailer_id"],
                        work_order_id=wo["id"],
                        payout_record_id=charge["payout_record_id"],
                        entry_type="REVERSAL",
                        amount_cents=-charge["amount_cents"],
                        status="PENDING",
                        settled_at=None,
                    )
                    db.settlement_entries[rev["id"]] = rev
            calc.recompute_retailer(retailer)
            if pro_id is not None:
                calc.recompute_pro(db.pros[pro_id])
        touch(wo)
        return success(wo, 200)


@app.route("/work-orders/<wid>/ratings", methods=["POST"])
def create_rating(wid):
    with LOCK:
        uid, role = authenticate(["Customer"])
        wo = get_or_404(db.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
        if wo["customer_id"] != uid:
            err("ERR_UNAUTHORIZED", "Caller does not own this work order.")
        body = get_body()
        require_fields(body, ["stars"])
        stars = body["stars"]
        if not is_int(stars) or stars < 1 or stars > 5:
            err("ERR_VALIDATION", "stars must be an integer 1..5.")
        # duplicate (priority 20)
        for r in db.ratings.values():
            if r["work_order_id"] == wo["id"]:
                err("ERR_DUPLICATE_RATING")
        # rating-state (priority 21)
        if wo["status"] not in ("COMPLETED", "CLOSED"):
            err("ERR_RATING_NOT_ALLOWED")
        rating = new_entity(
            common=False,
            work_order_id=wo["id"],
            pro_id=wo["appointment_pro_id"],
            customer_id=wo["customer_id"],
            stars=stars,
            comment=body.get("comment"),
        )
        db.ratings[rating["id"]] = rating
        if wo["appointment_pro_id"] is not None:
            calc.recompute_pro(db.pros[wo["appointment_pro_id"]])
        return success(rating, 201)


# ===========================================================================
# Assignment lifecycle
# ===========================================================================
@app.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    with LOCK:
        authenticate(["PlatformAdmin", "Pro"])
        ent = get_or_404(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
        return success(ent, 200)


@app.route("/assignments", methods=["GET"])
def list_assignments():
    with LOCK:
        authenticate(["PlatformAdmin", "Pro"])
        a = request.args
        rows = list_filter(db.assignments, {
            "work_order_id": a.get("work_order_id"),
            "pro_id": a.get("pro_id"),
        })
        window, pg = paginate(rows)
        return success(window, 200, response_type="array", pagination=pg)


ASG_TERMINAL = ("DECLINED", "EXPIRED", "CANCELLED")


@app.route("/assignments/<aid>/accept", methods=["POST"])
def accept_assignment(aid):
    with LOCK:
        uid, role = authenticate(["Pro"])
        asg = get_or_404(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
        if asg["pro_id"] != uid:
            err("ERR_UNAUTHORIZED", "Caller is not the offered pro.")
        if asg["status"] in ASG_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if asg["status"] != "OFFERED":
            err("ERR_INVALID_STATE")
        pro = db.pros[asg["pro_id"]]
        now = clock.now()
        appr = approved_application(pro)
        if appr is None:
            err("ERR_PRO_NOT_APPROVED")
        if now > appr["expires_at"]:
            err("ERR_VETTING_EXPIRED")
        wo = db.work_orders[asg["work_order_id"]]
        if pro_has_accepted_conflict(pro, asg["appointment_start"], asg["appointment_end"],
                                     exclude_id=asg["id"], exclude_wo_id=asg["work_order_id"]):
            err("ERR_PRO_SCHEDULE_CONFLICT")
        if zone_capacity_exceeded(wo["service_zone_id"], asg["appointment_start"],
                                  asg["appointment_end"], exclude_id=asg["id"],
                                  exclude_wo_id=asg["work_order_id"]):
            err("ERR_ZONE_CAPACITY_EXCEEDED")
        asg["status"] = "ACCEPTED"
        asg["responded_at"] = now
        touch(asg)
        calc.recompute_pro(pro)
        return success(asg, 200)


@app.route("/assignments/<aid>/decline", methods=["POST"])
def decline_assignment(aid):
    with LOCK:
        uid, role = authenticate(["Pro"])
        asg = get_or_404(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
        if asg["pro_id"] != uid:
            err("ERR_UNAUTHORIZED", "Caller is not the offered pro.")
        if asg["status"] in ASG_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if asg["status"] != "OFFERED":
            err("ERR_INVALID_STATE")
        asg["status"] = "DECLINED"
        asg["responded_at"] = clock.now()
        touch(asg)
        wo = db.work_orders[asg["work_order_id"]]
        if wo["status"] == "DISPATCHED":
            wo["status"] = "SCHEDULED"
            wo["appointment_pro_id"] = None
            touch(wo)
        calc.recompute_pro(db.pros[asg["pro_id"]])
        return success(asg, 200)


@app.route("/assignments/<aid>/expire", methods=["POST"])
def expire_assignment(aid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        asg = get_or_404(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
        if asg["status"] in ASG_TERMINAL:
            err("ERR_ALREADY_TERMINAL")
        if asg["status"] != "OFFERED":
            err("ERR_INVALID_STATE")
        asg["status"] = "EXPIRED"
        touch(asg)
        wo = db.work_orders[asg["work_order_id"]]
        if wo["status"] == "DISPATCHED":
            wo["status"] = "SCHEDULED"
            wo["appointment_pro_id"] = None
            touch(wo)
        calc.recompute_pro(db.pros[asg["pro_id"]])
        return success(asg, 200)


# ===========================================================================
# Rating reads
# ===========================================================================
@app.route("/ratings/<rid>", methods=["GET"])
def get_rating(rid):
    with LOCK:
        authenticate(["PlatformAdmin", "Pro", "Customer"])
        ent = get_or_404(db.ratings, rid, "ERR_RATING_NOT_FOUND")
        return success(ent, 200)


@app.route("/ratings", methods=["GET"])
def list_ratings():
    with LOCK:
        authenticate(["PlatformAdmin", "Pro", "Customer"])
        a = request.args
        rows = list_filter(db.ratings, {
            "work_order_id": a.get("work_order_id"),
            "pro_id": a.get("pro_id"),
            "customer_id": a.get("customer_id"),
        })
        window, pg = paginate(rows)
        return success(window, 200, response_type="array", pagination=pg)


# ===========================================================================
# PayoutRecord reads
# ===========================================================================
@app.route("/payout-records/<pid>", methods=["GET"])
def get_payout(pid):
    with LOCK:
        authenticate(["PlatformAdmin", "Pro"])
        ent = get_or_404(db.payouts, pid, "ERR_PAYOUT_NOT_FOUND")
        return success(ent, 200)


@app.route("/payout-records", methods=["GET"])
def list_payouts():
    with LOCK:
        authenticate(["PlatformAdmin", "Pro"])
        a = request.args
        rows = list_filter(db.payouts, {
            "work_order_id": a.get("work_order_id"),
            "pro_id": a.get("pro_id"),
            "retailer_id": a.get("retailer_id"),
        })
        window, pg = paginate(rows)
        return success(window, 200, response_type="array", pagination=pg)


# ===========================================================================
# RetailerSettlementEntry reads + settlement run
# ===========================================================================
@app.route("/settlement-entries/<sid>", methods=["GET"])
def get_settlement_entry(sid):
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer"])
        ent = get_or_404(db.settlement_entries, sid, "ERR_SETTLEMENT_ENTRY_NOT_FOUND")
        return success(ent, 200)


@app.route("/settlement-entries", methods=["GET"])
def list_settlement_entries():
    with LOCK:
        authenticate(["PlatformAdmin", "Retailer"])
        a = request.args
        rows = list_filter(db.settlement_entries, {
            "retailer_id": a.get("retailer_id"),
            "work_order_id": a.get("work_order_id"),
            "payout_record_id": a.get("payout_record_id"),
        })
        window, pg = paginate(rows)
        return success(window, 200, response_type="array", pagination=pg)


@app.route("/retailers/<rid>/settlements", methods=["POST"])
def run_settlement(rid):
    with LOCK:
        authenticate(["PlatformAdmin"])
        retailer = get_or_404(db.retailers, rid, "ERR_RETAILER_NOT_FOUND")
        body = get_body()
        require_fields(body, ["period_end"])
        try:
            period_end = parse_iso(body["period_end"])
        except ValueError:
            err("ERR_VALIDATION", "period_end must be an ISO8601 datetime.")
        selected = [e for e in db.settlement_entries.values()
                    if e["retailer_id"] == rid and e["status"] == "PENDING"
                    and e["created_at"] <= period_end]
        count = len(selected)
        gross = sum(e["amount_cents"] for e in selected)
        now = clock.now()
        for e in selected:
            e["status"] = "SETTLED"
            e["settled_at"] = now
            touch(e)
        calc.recompute_retailer(retailer)
        summary = {
            "retailer_id": rid,
            "settled_entry_count": count,
            "gross_settled_cents": gross,
            "remaining_balance_cents": retailer["settlement_balance_cents"],
        }
        return success(summary, 200)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
