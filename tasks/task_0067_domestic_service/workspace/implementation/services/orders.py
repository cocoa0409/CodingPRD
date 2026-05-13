"""Orders, dispatch, execution, and order-derived workflows."""
from datetime import timedelta
from decimal import Decimal

from db import store, iso_to_dt
from errors import (
    ERR_VALIDATION_ERROR, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_NOT_ASSIGNED,
    ERR_AREA_NOT_SERVICED, ERR_ITEM_INACTIVE, ERR_LEAD_TIME_TOO_SHORT,
    ERR_CANCEL_WINDOW_CLOSED, ERR_MODIFY_WINDOW_CLOSED,
    ERR_COMPLAINT_PERIOD_EXPIRED, ERR_DISPATCH_DEADLINE_PASSED,
    ERR_NO_ELIGIBLE_PERSONNEL, ERR_CHECKIN_LOCATION_MISMATCH,
    ERR_CHECKLIST_INCOMPLETE, ERR_EXECUTION_ALREADY_EXISTS,
    ERR_PERSONNEL_NOT_ELIGIBLE, raise_error,
)
from services.utils import (
    stamp_create, stamp_update, check_occ,
    haversine_km, round_half_up_int,
)
from services.audit import append_audit
from services.personnel import recompute_tier


# ----- helpers -----
def _validate_order_creation(customer_id, service_item_id, mode, scheduled_start_at, duration_hours):
    if customer_id not in store.customers:
        raise_error(ERR_NOT_FOUND, "Customer not found")
    if service_item_id not in store.service_items:
        raise_error(ERR_NOT_FOUND, "Service item not found")
    if mode not in {"SINGLE", "RECURRING"}:
        raise_error(ERR_VALIDATION_ERROR, "mode must be SINGLE or RECURRING")
    try:
        dh = float(duration_hours)
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION_ERROR, "duration_hours must be a number")
    if dh <= 0:
        raise_error(ERR_VALIDATION_ERROR, "duration_hours must be positive")
    # Multiple of 0.5
    if (dh * 2) != int(dh * 2):
        raise_error(ERR_VALIDATION_ERROR, "duration_hours must be a multiple of 0.5")

    sched_dt = iso_to_dt(scheduled_start_at)
    if sched_dt is None:
        raise_error(ERR_VALIDATION_ERROR, "Invalid scheduled_start_at")
    customer = store.customers[customer_id]
    item = store.service_items[service_item_id]

    # PRD §3.4: at create time only area + active-item checks apply
    # (lead-time + min-duration are enforced at submission).
    if customer["area_code"] not in item["service_areas"]:
        raise_error(ERR_AREA_NOT_SERVICED, "Customer area not in service areas")
    if not item["active"]:
        raise_error(ERR_ITEM_INACTIVE, "Service item is inactive")
    return customer, item, sched_dt, dh


def create_order(body: dict, caller_role: str, caller_id: str) -> dict:
    required = ["customer_id", "service_item_id", "mode", "scheduled_start_at", "duration_hours"]
    for f in required:
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION_ERROR, f"Missing required field: {f}")
    customer, item, sched_dt, dh = _validate_order_creation(
        body["customer_id"], body["service_item_id"], body["mode"],
        body["scheduled_start_at"], body["duration_hours"],
    )
    # Customer ownership check
    if caller_role == "Customer" and caller_id != body["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Customer not found")
    record = {
        "customer_id": body["customer_id"],
        "service_item_id": body["service_item_id"],
        "mode": body["mode"],
        "recurring_order_id": None,
        "scheduled_start_at": body["scheduled_start_at"],
        "duration_hours": dh,
        "gross_price_cents": 0,
        "status": "DRAFT",
        "assigned_personnel_id": None,
        "dispatch_round": 0,
        "dispatch_deadline_at": None,
        "completed_at": None,
        "accepted_at": None,
        "refunded_at": None,
        "rated": False,
    }
    stamp_create(record)
    store.orders[record["id"]] = record
    return record


def patch_order(order_id: str, body: dict, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o["status"] != "PENDING_DISPATCH":
        raise_error(ERR_MODIFY_WINDOW_CLOSED, "Order is not in PENDING_DISPATCH")
    sched_dt = iso_to_dt(o["scheduled_start_at"])
    if store.now() >= sched_dt - timedelta(hours=12):
        raise_error(ERR_MODIFY_WINDOW_CLOSED, "Modification window has closed")
    if caller_role == "Customer" and caller_id != o["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Order not found")
    check_occ(o, body)

    if "scheduled_start_at" in body and body["scheduled_start_at"] is not None:
        new_dt = iso_to_dt(body["scheduled_start_at"])
        if new_dt is None:
            raise_error(ERR_VALIDATION_ERROR, "Invalid scheduled_start_at")
        o["scheduled_start_at"] = body["scheduled_start_at"]
    if "duration_hours" in body and body["duration_hours"] is not None:
        try:
            dh = float(body["duration_hours"])
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION_ERROR, "duration_hours must be a number")
        if dh <= 0:
            raise_error(ERR_VALIDATION_ERROR, "duration_hours must be positive")
        if (dh * 2) != int(dh * 2):
            raise_error(ERR_VALIDATION_ERROR, "duration_hours must be a multiple of 0.5")
        item = store.service_items[o["service_item_id"]]
        if dh < float(item.get("min_duration_hours", 1)):
            raise_error(ERR_VALIDATION_ERROR, "duration_hours below minimum")
        o["duration_hours"] = dh
        # Recompute gross_price_cents (in case it was already set via submission)
        bp = int(item["base_price_cents"])
        o["gross_price_cents"] = int(round(bp * dh))
    stamp_update(o)
    return o


def submit_order(order_id: str, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Order must be DRAFT to submit")
    if caller_role == "Customer" and caller_id != o["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Order not found")
    customer = store.customers[o["customer_id"]]
    item = store.service_items[o["service_item_id"]]
    if customer["area_code"] not in item["service_areas"]:
        raise_error(ERR_AREA_NOT_SERVICED, "Customer area not in service areas")
    if not item["active"]:
        raise_error(ERR_ITEM_INACTIVE, "Service item is inactive")
    sched_dt = iso_to_dt(o["scheduled_start_at"])
    if sched_dt < store.now() + timedelta(hours=1):
        raise_error(ERR_LEAD_TIME_TOO_SHORT, "Lead time too short")
    if float(o["duration_hours"]) < float(item.get("min_duration_hours", 1)):
        raise_error(ERR_VALIDATION_ERROR, "duration_hours below minimum")
    # Compute gross_price_cents
    bp = int(item["base_price_cents"])
    dh = float(o["duration_hours"])
    o["gross_price_cents"] = int(round(bp * dh))
    o["status"] = "PENDING_DISPATCH"
    stamp_update(o)
    return o


# ----- dispatch selection -----
def _personnel_eligible(p: dict, order: dict, item: dict, customer: dict, exclusion: set) -> bool:
    if p["status"] != "ACTIVE":
        return False
    if p["id"] in exclusion:
        return False
    if item["required_skill_tag"] not in p.get("skill_tags", []):
        return False
    health_dt = iso_to_dt(p.get("health_cert_expires_at"))
    if health_dt is None or health_dt <= store.now():
        return False
    # Distance check
    d = haversine_km(
        p["service_lat"], p["service_lng"],
        customer["address_lat"], customer["address_lng"],
    )
    if d > Decimal(str(p["service_radius_km"])):
        return False
    if int(p.get("workload_active_orders", 0)) >= 5:
        return False
    if customer.get("pref_gender") and p["gender"] != customer["pref_gender"]:
        return False
    if customer.get("pref_min_age") is not None and int(p["age"]) < int(customer["pref_min_age"]):
        return False
    if customer.get("pref_max_age") is not None and int(p["age"]) > int(customer["pref_max_age"]):
        return False
    if customer.get("pref_language") and customer["pref_language"] not in p.get("languages", []):
        return False
    return True


TIER_PRIORITY = {"PLATINUM": 4, "GOLD": 3, "SILVER": 2, "BRONZE": 1}


def _rank_key(p: dict, customer: dict):
    """Sort key: tier desc, rating_score desc, distance asc, id asc.

    We return a tuple suitable for ascending sort by negating where needed:
    (-tier_priority, -rating_score, +distance, id)."""
    d = haversine_km(
        p["service_lat"], p["service_lng"],
        customer["address_lat"], customer["address_lng"],
    )
    return (
        -TIER_PRIORITY.get(p["tier"], 0),
        -Decimal(str(p.get("rating_score", 0))),
        d,
        p["id"],
    )


def _select_personnel(order: dict, exclude_extra: set = None):
    item = store.service_items[order["service_item_id"]]
    customer = store.customers[order["customer_id"]]
    exclusion = set(store.exclusion_sets.get(order["id"], set()))
    if exclude_extra:
        exclusion |= exclude_extra
    eligible = [p for p in store.personnel.values()
                if _personnel_eligible(p, order, item, customer, exclusion)]
    if not eligible:
        return None
    eligible.sort(key=lambda p: _rank_key(p, customer))
    return eligible[0]


def dispatch_order(order_id: str, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o["status"] != "PENDING_DISPATCH":
        raise_error(ERR_INVALID_STATE, "Order must be PENDING_DISPATCH to dispatch")
    chosen = _select_personnel(o)
    if chosen is None:
        raise_error(ERR_NO_ELIGIBLE_PERSONNEL, "No eligible personnel")
    # Transition
    o["assigned_personnel_id"] = chosen["id"]
    o["dispatch_round"] = int(o.get("dispatch_round", 0)) + 1
    o["dispatch_deadline_at"] = (store.now() + timedelta(minutes=15)).strftime(
        "%Y-%m-%dT%H:%M:%S.") + f"{(store.now() + timedelta(minutes=15)).microsecond // 1000:03d}Z"
    o["status"] = "DISPATCHED"
    chosen["workload_active_orders"] = int(chosen.get("workload_active_orders", 0)) + 1
    stamp_update(chosen)
    stamp_update(o)
    append_audit("DISPATCH", "Order", o["id"], caller_role, caller_id,
                 {"personnel_id": chosen["id"], "dispatch_round": o["dispatch_round"]})
    return o


def reassign_order(order_id: str, body: dict, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o["status"] != "PENDING_DISPATCH":
        raise_error(ERR_INVALID_STATE, "Order must be PENDING_DISPATCH to reassign")
    personnel_id = body.get("personnel_id")
    if not personnel_id:
        raise_error(ERR_VALIDATION_ERROR, "Missing personnel_id")
    if personnel_id not in store.personnel:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    p = store.personnel[personnel_id]
    item = store.service_items[o["service_item_id"]]
    customer = store.customers[o["customer_id"]]
    exclusion = set(store.exclusion_sets.get(o["id"], set()))
    if not _personnel_eligible(p, o, item, customer, exclusion):
        raise_error(ERR_PERSONNEL_NOT_ELIGIBLE, "Personnel does not satisfy eligibility predicate")
    o["assigned_personnel_id"] = personnel_id
    o["dispatch_round"] = int(o.get("dispatch_round", 0)) + 1
    new_deadline = store.now() + timedelta(minutes=15)
    o["dispatch_deadline_at"] = new_deadline.strftime(
        "%Y-%m-%dT%H:%M:%S.") + f"{new_deadline.microsecond // 1000:03d}Z"
    o["status"] = "DISPATCHED"
    p["workload_active_orders"] = int(p.get("workload_active_orders", 0)) + 1
    stamp_update(p)
    stamp_update(o)
    append_audit("REASSIGN", "Order", o["id"], caller_role, caller_id,
                 {"personnel_id": personnel_id, "dispatch_round": o["dispatch_round"]})
    return o


def accept_order(order_id: str, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    # PRD §3.5: ownership precedes business-temporal, so the assignment guard
    # still fires first (a non-assignee on a DISPATCHED order yields
    # ERR_NOT_ASSIGNED). When the caller IS the assignee, the deadline check
    # fires before the state check so that an accept past dispatch_deadline_at
    # surfaces ERR_DISPATCH_DEADLINE_PASSED (PRD §3.5) rather than the more
    # generic ERR_INVALID_STATE produced by a lazy auto-revert.
    if o["status"] == "DISPATCHED" and o.get("assigned_personnel_id") == caller_id:
        deadline = iso_to_dt(o.get("dispatch_deadline_at"))
        if deadline is not None and store.now() >= deadline:
            # Auto-revert before raising so subsequent reads observe the
            # PENDING_DISPATCH state (PRD §3.5 system-driven branch).
            from services.sweeps import _expire_one_dispatched
            _expire_one_dispatched(o)
            raise_error(ERR_DISPATCH_DEADLINE_PASSED, "Dispatch deadline passed")
    if o["status"] != "DISPATCHED":
        raise_error(ERR_INVALID_STATE, "Order must be DISPATCHED to accept")
    if o.get("assigned_personnel_id") != caller_id:
        raise_error(ERR_NOT_ASSIGNED, "Caller is not the assigned personnel")
    o["status"] = "ACCEPTED"
    stamp_update(o)
    return o


def reject_order(order_id: str, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o["status"] != "DISPATCHED":
        raise_error(ERR_INVALID_STATE, "Order must be DISPATCHED to reject")
    if o.get("assigned_personnel_id") != caller_id:
        raise_error(ERR_NOT_ASSIGNED, "Caller is not the assigned personnel")
    prev = o.get("assigned_personnel_id")
    if prev and prev in store.personnel:
        p = store.personnel[prev]
        p["workload_active_orders"] = max(0, int(p.get("workload_active_orders", 0)) - 1)
        stamp_update(p)
    o["assigned_personnel_id"] = None
    o["status"] = "PENDING_DISPATCH"
    # exclusion set for next dispatch
    s = store.exclusion_sets.setdefault(o["id"], set())
    if prev:
        s.add(prev)
    stamp_update(o)
    append_audit("DISPATCH_EXPIRED", "Order", o["id"], caller_role, caller_id,
                 {"previous_personnel_id": prev, "reason": "rejected"})
    return o


def checkin_order(order_id: str, body: dict, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_STATE, "Order must be ACCEPTED to check in")
    if o.get("assigned_personnel_id") != caller_id:
        raise_error(ERR_NOT_ASSIGNED, "Caller is not the assigned personnel")
    if o["id"] in store.executions_by_order:
        raise_error(ERR_EXECUTION_ALREADY_EXISTS, "Execution already exists for this order")
    for f in ("checkin_lat", "checkin_lng", "checkin_face_passed"):
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION_ERROR, f"Missing required field: {f}")
    if not bool(body["checkin_face_passed"]):
        raise_error(ERR_CHECKIN_LOCATION_MISMATCH, "Face verification failed")
    customer = store.customers[o["customer_id"]]
    d = haversine_km(
        body["checkin_lat"], body["checkin_lng"],
        customer["address_lat"], customer["address_lng"],
    )
    if d > Decimal("0.2"):
        raise_error(ERR_CHECKIN_LOCATION_MISMATCH, "Check-in location too far from address")
    sched_dt = iso_to_dt(o["scheduled_start_at"])
    if store.now() < sched_dt - timedelta(minutes=15):
        raise_error(ERR_CHECKIN_LOCATION_MISMATCH, "Check-in too early")
    # Create execution
    exec_record = {
        "order_id": o["id"],
        "checkin_lat": float(body["checkin_lat"]),
        "checkin_lng": float(body["checkin_lng"]),
        "checkin_face_passed": True,
        "checkin_at": store.now_iso(),
        "procedure_checklist": list(body.get("procedure_checklist", [])),
        "before_photo_url": body.get("before_photo_url"),
        "after_photo_url": body.get("after_photo_url"),
        "abnormal_reported": False,
        "completion_submitted_at": None,
    }
    exec_record["id"] = store.new_id()
    exec_record["created_at"] = store.now_iso()
    store.executions[exec_record["id"]] = exec_record
    store.executions_by_order[o["id"]] = exec_record["id"]
    o["status"] = "IN_PROGRESS"
    stamp_update(o)
    return o


def patch_execution(order_id: str, body: dict, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o.get("assigned_personnel_id") != caller_id:
        raise_error(ERR_NOT_ASSIGNED, "Caller is not the assigned personnel")
    if o["id"] not in store.executions_by_order:
        raise_error(ERR_NOT_FOUND, "ServiceExecution not found")
    if o["status"] not in {"IN_PROGRESS"}:
        raise_error(ERR_INVALID_STATE, "Order must be IN_PROGRESS to update execution")
    eid = store.executions_by_order[o["id"]]
    ex = store.executions[eid]
    if "procedure_checklist" in body and body["procedure_checklist"] is not None:
        if not isinstance(body["procedure_checklist"], list):
            raise_error(ERR_VALIDATION_ERROR, "procedure_checklist must be array")
        ex["procedure_checklist"] = list(body["procedure_checklist"])
    if "before_photo_url" in body:
        ex["before_photo_url"] = body["before_photo_url"]
    if "after_photo_url" in body:
        ex["after_photo_url"] = body["after_photo_url"]
    return ex


def complete_order(order_id: str, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "Order must be IN_PROGRESS to complete")
    if o.get("assigned_personnel_id") != caller_id:
        raise_error(ERR_NOT_ASSIGNED, "Caller is not the assigned personnel")
    if o["id"] not in store.executions_by_order:
        raise_error(ERR_CHECKLIST_INCOMPLETE, "No service execution exists")
    ex = store.executions[store.executions_by_order[o["id"]]]
    checklist = ex.get("procedure_checklist") or []
    if not checklist or not all(bool(x) for x in checklist):
        raise_error(ERR_CHECKLIST_INCOMPLETE, "Procedure checklist incomplete")
    if not ex.get("before_photo_url") or not ex.get("after_photo_url"):
        raise_error(ERR_CHECKLIST_INCOMPLETE, "Photos missing")
    now = store.now()
    now_iso = store.now_iso()
    o["completed_at"] = now_iso
    ex["completion_submitted_at"] = now_iso
    o["status"] = "COMPLETED"
    # Post provisional commission
    gross = int(o["gross_price_cents"])
    provisional = round_half_up_int(Decimal(str(gross)) * Decimal("0.70"))
    withheld_until = (now + timedelta(hours=72))
    withheld_iso = withheld_until.strftime("%Y-%m-%dT%H:%M:%S.") + f"{withheld_until.microsecond // 1000:03d}Z"
    cycle_id = now.strftime("%Y-%m")
    entry = {
        "personnel_id": o["assigned_personnel_id"],
        "order_id": o["id"],
        "kind": "COMMISSION",
        "amount_cents": int(provisional),
        "posted_at": now_iso,
        "cycle_id": cycle_id,
        "withheld_until": withheld_iso,
    }
    entry["id"] = store.new_id()
    entry["created_at"] = now_iso
    store.settlement_entries[entry["id"]] = entry
    stamp_update(o)
    return o


def customer_accept_order(order_id: str, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE, "Order must be COMPLETED to accept")
    if caller_id != o["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Order not found")
    now = store.now()
    o["accepted_at"] = store.now_iso()
    # Final commission delta
    p = store.personnel.get(o["assigned_personnel_id"])
    gross = Decimal(str(o["gross_price_cents"]))
    base_rate = Decimal("0.70")
    bonus_rate = _tier_bonus_rate(p["tier"]) if p else Decimal("0")
    final_amount = round_half_up_int(gross * base_rate * (Decimal("1") + bonus_rate))
    # Provisional was the previous COMMISSION entry posted on this order
    commission_entries = [e for e in store.settlement_entries.values()
                          if e["order_id"] == o["id"] and e["kind"] == "COMMISSION"]
    provisional = sum(int(e["amount_cents"]) for e in commission_entries)
    delta = int(final_amount) - int(provisional)
    if delta != 0:
        kind = "BONUS" if delta > 0 else "REVERSAL"
        amount = abs(delta) if kind == "BONUS" else -abs(delta)
        cycle_id = now.strftime("%Y-%m")
        # BONUS still receives withheld_until = accepted_at + 72h (per scaffold:
        # withheld_until is null only for REVERSAL/TAX/PAYOUT).
        if kind == "BONUS":
            wu = (now + timedelta(hours=72))
            withheld_iso = wu.strftime("%Y-%m-%dT%H:%M:%S.") + f"{wu.microsecond // 1000:03d}Z"
        else:
            withheld_iso = None
        entry = {
            "personnel_id": o["assigned_personnel_id"],
            "order_id": o["id"],
            "kind": kind,
            "amount_cents": int(amount),
            "posted_at": store.now_iso(),
            "cycle_id": cycle_id,
            "withheld_until": withheld_iso,
        }
        entry["id"] = store.new_id()
        entry["created_at"] = store.now_iso()
        store.settlement_entries[entry["id"]] = entry
    # Decrement workload
    if p:
        p["workload_active_orders"] = max(0, int(p.get("workload_active_orders", 0)) - 1)
        stamp_update(p)
    o["status"] = "ACCEPTED_BY_CUSTOMER"
    stamp_update(o)
    return o


def _tier_bonus_rate(tier: str) -> Decimal:
    return {
        "PLATINUM": Decimal("0.20"),
        "GOLD": Decimal("0.10"),
        "SILVER": Decimal("0.05"),
        "BRONZE": Decimal("0.00"),
    }.get(tier, Decimal("0.00"))


def cancel_order(order_id: str, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    if o["status"] not in {"PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"}:
        raise_error(ERR_INVALID_STATE, "Order cannot be cancelled in its current state")
    if caller_role == "Customer" and caller_id != o["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Order not found")
    sched_dt = iso_to_dt(o["scheduled_start_at"])
    if store.now() >= sched_dt - timedelta(hours=2):
        raise_error(ERR_CANCEL_WINDOW_CLOSED, "Cancel window closed")
    # Side effects
    if o["status"] in {"DISPATCHED", "ACCEPTED"} and o.get("assigned_personnel_id"):
        p = store.personnel.get(o["assigned_personnel_id"])
        if p:
            p["workload_active_orders"] = max(0, int(p.get("workload_active_orders", 0)) - 1)
            stamp_update(p)
    customer = store.customers.get(o["customer_id"])
    if customer:
        customer["wallet_credit_cents"] = int(customer.get("wallet_credit_cents", 0)) + int(o["gross_price_cents"])
        stamp_update(customer)
    o["status"] = "CANCELLED"
    stamp_update(o)
    return o


def refund_order(order_id: str, caller_role: str, caller_id: str) -> dict:
    if order_id not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[order_id]
    # PRD §3.8: a refund attempt past the 72h window OR against an order
    # already in ACCEPTED_BY_CUSTOMER surfaces ERR_COMPLAINT_PERIOD_EXPIRED.
    if o["status"] == "ACCEPTED_BY_CUSTOMER":
        raise_error(ERR_COMPLAINT_PERIOD_EXPIRED, "Order already accepted by customer")
    if o["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE, "Order must be COMPLETED to refund")
    completed_dt = iso_to_dt(o.get("completed_at"))
    if completed_dt is None or store.now() >= completed_dt + timedelta(hours=72):
        raise_error(ERR_COMPLAINT_PERIOD_EXPIRED, "Complaint period expired")
    # Compensating reversal entry
    commission_entries = [e for e in store.settlement_entries.values()
                          if e["order_id"] == o["id"] and e["kind"] == "COMMISSION"]
    prior_total = sum(int(e["amount_cents"]) for e in commission_entries)
    entry = {
        "personnel_id": o["assigned_personnel_id"],
        "order_id": o["id"],
        "kind": "REVERSAL",
        "amount_cents": -int(prior_total),
        "posted_at": store.now_iso(),
        "cycle_id": store.now().strftime("%Y-%m"),
        "withheld_until": None,
    }
    entry["id"] = store.new_id()
    entry["created_at"] = store.now_iso()
    store.settlement_entries[entry["id"]] = entry
    # Wallet credit
    customer = store.customers.get(o["customer_id"])
    if customer:
        customer["wallet_credit_cents"] = int(customer.get("wallet_credit_cents", 0)) + int(o["gross_price_cents"])
        stamp_update(customer)
    # Decrement workload
    if o.get("assigned_personnel_id"):
        p = store.personnel.get(o["assigned_personnel_id"])
        if p:
            p["workload_active_orders"] = max(0, int(p.get("workload_active_orders", 0)) - 1)
            stamp_update(p)
    o["refunded_at"] = store.now_iso()
    o["status"] = "REFUNDED"
    stamp_update(o)
    return o
