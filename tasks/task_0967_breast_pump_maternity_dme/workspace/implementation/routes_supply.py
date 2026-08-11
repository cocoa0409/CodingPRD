"""Resupply schedules, resupply orders, warranty claims."""
from flask import Blueprint

from db import store, now_iso, today, next_seq
from errors import ApiError
from response import ok
from middleware import (
    authorize, check_ownership, body, get_or_404, req_str, opt_str, req_int,
    req_enum, parse_date, paginate, filter_query, scope_member_list, public,
)
from services import (
    create_entity, bump, compute_next_eligible, recompute_member_aggregates,
    add_months, rhu, MAX_WARRANTY_REPLACEMENTS, MAX_REOPENS,
)
from routes_ops import (
    _check_fk, SCHEDULE_READ_ROLES, RESUPPLY_READ_ROLES, WARRANTY_READ_ROLES,
    WARRANTY_ISSUES, WARRANTY_DECISIONS, SCHEDULE_PATCH_STATUSES,
)

bp = Blueprint("supply", __name__, url_prefix="/dme")


# ------------------------------------------------------ resupply schedules ----

@bp.route("/resupply-schedules/<sid>", methods=["GET"])
def get_schedule(sid):
    uid, role = authorize(SCHEDULE_READ_ROLES)
    s = get_or_404(store.schedules, sid, "ERR_SCHEDULE_NOT_FOUND")
    check_ownership(role, uid, s["member_id"])
    return ok(public(s))


@bp.route("/resupply-schedules", methods=["GET"])
def list_schedules():
    uid, role = authorize(SCHEDULE_READ_ROLES)
    items = scope_member_list(store.schedules.values(), role, uid)
    items = filter_query(items, {
        "member_id": "member_id",
        "pump_order_id": "pump_order_id",
        "catalog_item_id": "catalog_item_id",
        "status": "status",
    })
    return paginate(items)


@bp.route("/resupply-schedules/<sid>", methods=["PATCH"])
def patch_schedule(sid):
    authorize(["CareCoordinator"])
    s = get_or_404(store.schedules, sid, "ERR_SCHEDULE_NOT_FOUND")
    b = body()
    ver = b.get("expected_schedule_version")
    if isinstance(ver, bool) or not isinstance(ver, int):
        raise ApiError("ERR_VALIDATION", "expected_schedule_version is required", 400)
    new_freq = None
    if "frequency_days" in b and b["frequency_days"] is not None:
        new_freq = b["frequency_days"]
        if isinstance(new_freq, bool) or not isinstance(new_freq, int) or new_freq < 1:
            raise ApiError("ERR_VALIDATION", "frequency_days must be an integer >= 1", 400)
    new_status = None
    if "status" in b and b["status"] is not None:
        new_status = req_enum(b, "status", SCHEDULE_PATCH_STATUSES)
    if ver != s["version"]:
        raise ApiError("ERR_STALE_VERSION", "ResupplySchedule version has advanced", 412)
    if s["status"] == "ENDED":
        raise ApiError("ERR_INVALID_STATE", "Schedule is ENDED", 409)
    if new_status is not None and new_status == s["status"]:
        raise ApiError("ERR_INVALID_STATE", "Invalid schedule status transition", 409)
    if new_freq is not None:
        s["frequency_days"] = new_freq
    if new_status is not None:
        s["status"] = new_status
    s["next_eligible_date"] = compute_next_eligible(s)
    bump(s)
    recompute_member_aggregates(store.members[s["member_id"]])
    return ok(public(s))


# -------------------------------------------------------- resupply orders ----

@bp.route("/resupply-orders", methods=["POST"])
def create_resupply_order():
    uid, role = authorize(["Member", "CareCoordinator"])
    b = body()
    if role == "Member" and isinstance(b.get("member_id"), str) and b["member_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", "Members may only order for themselves", 403)
    _check_fk(b, "schedule_id", store.schedules, "ERR_SCHEDULE_NOT_FOUND")
    _check_fk(b, "member_id", store.members, "ERR_MEMBER_NOT_FOUND")
    schedule_id = req_str(b, "schedule_id")
    member_id = req_str(b, "member_id")
    quantity = req_int(b, "quantity")
    if quantity < 1:
        raise ApiError("ERR_VALIDATION", "quantity must be at least 1", 400)
    sched = store.schedules[schedule_id]
    if role == "Member" and sched["member_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", "Members may only use their own schedules", 403)
    if sched["member_id"] != member_id:
        raise ApiError("ERR_VALIDATION", "member_id must equal the schedule's member_id", 400)
    if sched["status"] != "ACTIVE":
        raise ApiError("ERR_SCHEDULE_NOT_ACTIVE", "Schedule is not ACTIVE", 409)
    order = store.pump_orders[sched["pump_order_id"]]
    policy = store.policies[order["policy_id"]]
    t = today()
    if t >= parse_date(policy["benefit_period_end"]):
        # lazy evaluation: benefit period closed, schedule flips to ENDED
        sched["status"] = "ENDED"
        bump(sched)
        recompute_member_aggregates(store.members[sched["member_id"]])
        raise ApiError("ERR_BENEFIT_PERIOD_ENDED", "Benefit period has ended", 422)
    if t < parse_date(policy["benefit_period_start"]):
        raise ApiError("ERR_BENEFIT_PERIOD_ENDED", "Current date is outside the benefit period", 422)
    if t < parse_date(sched["next_eligible_date"]):
        raise ApiError("ERR_RESUPPLY_WINDOW_NOT_OPEN", "Resupply window is not yet open", 422)
    item = store.catalog_items[sched["catalog_item_id"]]
    if quantity > item["max_qty_per_frequency"]:
        raise ApiError("ERR_RESUPPLY_QUANTITY_CAP_EXCEEDED", "Quantity exceeds max_qty_per_frequency", 422)
    ro = create_entity(store.resupply_orders, {
        "schedule_id": sched["id"],
        "member_id": member_id,
        "quantity": quantity,
        "unit_price_cents": item["unit_price_cents"],
        "total_cents": rhu(quantity * item["unit_price_cents"]),
        "status": "APPROVED",
        "fulfilled_date": t.isoformat(),
    })
    sched["last_fulfilled_date"] = ro["fulfilled_date"]
    sched["next_eligible_date"] = compute_next_eligible(sched)
    bump(sched)
    return ok(public(ro), 201)


@bp.route("/resupply-orders/<rid>", methods=["GET"])
def get_resupply_order(rid):
    uid, role = authorize(RESUPPLY_READ_ROLES)
    ro = get_or_404(store.resupply_orders, rid, "ERR_RESUPPLY_ORDER_NOT_FOUND")
    check_ownership(role, uid, ro["member_id"])
    return ok(public(ro))


@bp.route("/resupply-orders", methods=["GET"])
def list_resupply_orders():
    uid, role = authorize(RESUPPLY_READ_ROLES)
    items = scope_member_list(store.resupply_orders.values(), role, uid)
    items = filter_query(items, {
        "schedule_id": "schedule_id",
        "member_id": "member_id",
        "status": "status",
    })
    return paginate(items)


@bp.route("/resupply-orders/<rid>/cancel", methods=["POST"])
def cancel_resupply_order(rid):
    uid, role = authorize(["Member", "CareCoordinator"])
    ro = get_or_404(store.resupply_orders, rid, "ERR_RESUPPLY_ORDER_NOT_FOUND")
    check_ownership(role, uid, ro["member_id"])
    if ro["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Resupply order is not APPROVED", 409)
    ro["status"] = "CANCELLED"
    bump(ro)
    sched = store.schedules[ro["schedule_id"]]
    if sched["last_fulfilled_date"] == ro["fulfilled_date"]:
        others = [
            o for o in store.resupply_orders.values()
            if o["schedule_id"] == sched["id"]
            and o["id"] != ro["id"]
            and o["status"] != "CANCELLED"
        ]
        if others:
            latest = max(others, key=lambda o: (o["fulfilled_date"], o["_seq"]))
            sched["last_fulfilled_date"] = latest["fulfilled_date"]
        else:
            sched["last_fulfilled_date"] = None
        sched["next_eligible_date"] = compute_next_eligible(sched)
    bump(sched)
    return ok(public(ro))


# ---------------------------------------------------------- warranty claims ----

@bp.route("/warranty-claims", methods=["POST"])
def create_warranty_claim():
    uid, role = authorize(["Member", "CareCoordinator"])
    b = body()
    _check_fk(b, "pump_order_id", store.pump_orders, "ERR_ORDER_NOT_FOUND")
    oid = req_str(b, "pump_order_id")
    serial_number = req_str(b, "serial_number")
    issue_type = req_enum(b, "issue_type", WARRANTY_ISSUES)
    description = opt_str(b, "description")
    order = store.pump_orders[oid]
    check_ownership(role, uid, order["member_id"])
    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", "Pump order is not DELIVERED", 409)
    item = store.catalog_items[order["pump_item_id"]]
    if today() > add_months(parse_date(order["delivery_date"]), item["warranty_months"]):
        raise ApiError("ERR_WARRANTY_EXPIRED", "Warranty window has closed", 422)
    if order["warranty_blocked"]:
        raise ApiError(
            "ERR_WARRANTY_REPLACEMENT_EXHAUSTED",
            "Warranty replacement budget is exhausted",
            422,
        )
    wc = create_entity(store.warranty_claims, {
        "pump_order_id": order["id"],
        "member_id": order["member_id"],
        "serial_number": serial_number,
        "issue_type": issue_type,
        "description": description,
        "status": "OPENED",
        "reopen_count": 0,
        "resolution_notes": None,
        "replacement_shipment_id": None,
    })
    return ok(public(wc), 201)


@bp.route("/warranty-claims/<wid>", methods=["GET"])
def get_warranty_claim(wid):
    uid, role = authorize(WARRANTY_READ_ROLES)
    wc = get_or_404(store.warranty_claims, wid, "ERR_WARRANTY_CLAIM_NOT_FOUND")
    check_ownership(role, uid, wc["member_id"])
    return ok(public(wc))


@bp.route("/warranty-claims", methods=["GET"])
def list_warranty_claims():
    uid, role = authorize(WARRANTY_READ_ROLES)
    items = scope_member_list(store.warranty_claims.values(), role, uid)
    items = filter_query(items, {
        "pump_order_id": "pump_order_id",
        "member_id": "member_id",
        "status": "status",
        "replacement_shipment_id": "replacement_shipment_id",
    })
    return paginate(items)


@bp.route("/warranty-claims/<wid>/decide", methods=["POST"])
def decide_warranty_claim(wid):
    authorize(["PlatformAdmin"])
    wc = get_or_404(store.warranty_claims, wid, "ERR_WARRANTY_CLAIM_NOT_FOUND")
    b = body()
    decision = req_enum(b, "decision", WARRANTY_DECISIONS)
    notes = opt_str(b, "resolution_notes")
    if wc["status"] != "OPENED":
        raise ApiError("ERR_INVALID_STATE", "Warranty claim is not OPENED", 409)
    wc["status"] = decision
    wc["resolution_notes"] = notes
    bump(wc)
    return ok(public(wc))


@bp.route("/warranty-claims/<wid>/reopen", methods=["POST"])
def reopen_warranty_claim(wid):
    uid, role = authorize(["Member", "CareCoordinator"])
    wc = get_or_404(store.warranty_claims, wid, "ERR_WARRANTY_CLAIM_NOT_FOUND")
    check_ownership(role, uid, wc["member_id"])
    if wc["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", "Warranty claim is not DENIED", 409)
    if wc["reopen_count"] >= MAX_REOPENS:
        raise ApiError("ERR_MAX_REOPENS_EXCEEDED", "Reopen budget exhausted", 422)
    wc["status"] = "OPENED"
    wc["reopen_count"] += 1
    bump(wc)
    return ok(public(wc))


@bp.route("/warranty-claims/<wid>/resolve", methods=["POST"])
def resolve_warranty_claim(wid):
    import uuid as _uuid

    authorize(["PlatformAdmin"])
    wc = get_or_404(store.warranty_claims, wid, "ERR_WARRANTY_CLAIM_NOT_FOUND")
    if wc["status"] not in ("APPROVED_REPAIR", "APPROVED_REPLACE"):
        raise ApiError("ERR_INVALID_STATE", "Warranty claim is not in an approved state", 409)
    if wc["status"] == "APPROVED_REPLACE":
        order = store.pump_orders[wc["pump_order_id"]]
        shipment = create_entity(store.shipments, {
            "pump_order_id": order["id"],
            "resupply_order_id": None,
            "carrier": "WARRANTY_REPLACEMENT",
            "tracking_number": "WR-" + _uuid.uuid4().hex[:12].upper(),
            "status": "LABEL_CREATED",
            "is_warranty_replacement": True,
            "shipped_at": now_iso(),
            "delivered_at": None,
        })
        wc["replacement_shipment_id"] = shipment["id"]
        order["replacement_count"] += 1
        if order["replacement_count"] >= MAX_WARRANTY_REPLACEMENTS:
            order["warranty_blocked"] = True
        bump(order)
    wc["status"] = "RESOLVED"
    bump(wc)
    return ok(public(wc))
