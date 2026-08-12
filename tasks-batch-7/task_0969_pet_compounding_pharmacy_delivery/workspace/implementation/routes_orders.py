from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, body, require_ownership
from response import success, paged
from services import (get_or_404, order_allocations, release_reserved_allocations,
                      refund_order, cancel_order_internal, check_no_active_recall,
                      check_recall_hold, fefo_candidates, compute_final_price,
                      cs_append, update_lot_exhaustion)
from util import (new_resource, touch, req, opt, as_str, as_int, as_enum,
                  as_datetime_str, parse_datetime, rhu, dec)
from decimal import Decimal

bp = Blueprint("orders", __name__)

ORDER_READ = ("Owner", "Pharmacist", "PharmacyTech", "ComplianceOfficer",
              "PharmacyAdmin")


def _filter(items, names):
    out = []
    for it in items:
        ok = True
        for n in names:
            v = request.args.get(n)
            if v is not None and str(it.get(n)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


@bp.route("/compound-orders", methods=["GET"])
def list_orders():
    auth(*ORDER_READ)
    return paged(_filter(list(db.compound_orders.values()),
                         ["owner_id", "prescription_id", "flavoring_id",
                          "supersedes_order_id", "status"]))


@bp.route("/compound-orders/<rid>", methods=["GET"])
def get_order(rid):
    auth("Owner", "Pharmacist", "PharmacyTech", "ComplianceOfficer",
         "InsuranceAdjuster", "PharmacyAdmin")
    return success(get_or_404(db.compound_orders, rid, "compound order"))


@bp.route("/compound-orders/<rid>/allocations", methods=["GET"])
def list_order_allocations(rid):
    auth("Pharmacist", "PharmacyTech", "ComplianceOfficer", "PharmacyAdmin")
    get_or_404(db.compound_orders, rid, "compound order")
    return paged([a for a in db.lot_allocations.values()
                  if a["compound_order_id"] == rid])


@bp.route("/lot-allocations", methods=["GET"])
def list_allocations():
    auth("Pharmacist", "PharmacyTech", "ComplianceOfficer", "PharmacyAdmin")
    return paged(_filter(list(db.lot_allocations.values()),
                         ["lot_id", "compound_order_id", "status"]))


@bp.route("/lot-allocations/<rid>", methods=["GET"])
def get_allocation(rid):
    auth("Pharmacist", "PharmacyTech", "ComplianceOfficer", "PharmacyAdmin")
    return success(get_or_404(db.lot_allocations, rid, "lot allocation"))


# ---- lifecycle actions ----

@bp.route("/compound-orders/<rid>/allocate", methods=["POST"])
def allocate(rid):
    auth("PharmacyTech")
    order = get_or_404(db.compound_orders, rid, "compound order")
    check_recall_hold(order, "allocate")
    rx = db.prescriptions[order["prescription_id"]]
    if rx["status"] != "VERIFIED":
        raise ApiError("ERR_PRESCRIPTION_NOT_VERIFIED",
                       "prescription is not VERIFIED", 409)
    if order["status"] != "CREATED":
        raise ApiError("ERR_INVALID_STATE", "order is not in CREATED", 409)
    formula = db.formulas[rx["formula_id"]]
    candidates = fefo_candidates(rx, formula)
    need = order["quantity_snapshot"]
    plan = []
    remaining = need
    for lot in candidates:
        if remaining <= 0:
            break
        take = min(remaining, lot["qty_on_hand"])
        if take > 0:
            plan.append((lot, take))
            remaining -= take
    if remaining > 0:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY",
                       "FEFO candidates cannot cover the order quantity", 422)
    for lot, take in plan:
        alloc = new_resource({
            "compound_order_id": order["id"], "lot_id": lot["id"],
            "qty_allocated": take, "qty_consumed": 0, "status": "RESERVED",
        })
        db.lot_allocations[alloc["id"]] = alloc
        lot["qty_reserved"] += take
        lot["qty_on_hand"] -= take
        update_lot_exhaustion(lot)
        touch(lot)
    order["status"] = "ALLOCATED"
    touch(order)
    return success(order)


def _bench_overlap(bench_id, start, end):
    for r in db.bench_reservations.values():
        if r["bench_id"] != bench_id or r["status"] not in ("BOOKED", "IN_USE"):
            continue
        ex_start = parse_datetime(r["start_at"])
        ex_end = parse_datetime(r["end_at"])
        if ex_start < end and start < ex_end:
            return True
    return False


@bp.route("/compound-orders/<rid>/start-compounding", methods=["POST"])
def start_compounding(rid):
    _, user_id = auth("Pharmacist")
    order = get_or_404(db.compound_orders, rid, "compound order")
    d = body()
    bench_id = d.get("bench_id")
    bench = None
    if bench_id is not None:
        bench = get_or_404(db.benches, bench_id, "compounding bench")
    bench_id = as_str(req(d, "bench_id"), "bench_id")
    start_s = as_datetime_str(req(d, "start_at"), "start_at")
    end_s = as_datetime_str(req(d, "end_at"), "end_at")
    start = parse_datetime(start_s)
    end = parse_datetime(end_s)
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "end_at must be after start_at", 400)
    check_recall_hold(order, "start-compounding")
    if order["status"] not in ("ALLOCATED", "REWORK"):
        raise ApiError("ERR_INVALID_STATE",
                       "order is not in ALLOCATED or REWORK", 409)
    if bench["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "bench is not ACTIVE", 409)
    rx = db.prescriptions[order["prescription_id"]]
    if rx["is_controlled"] and not bench["supports_controlled"]:
        raise ApiError("ERR_BENCH_NOT_CONTROLLED_CAPABLE",
                       "controlled order requires a controlled-capable bench", 422)
    check_no_active_recall(order)
    if _bench_overlap(bench_id, start, end):
        raise ApiError("ERR_BENCH_OVERLAP",
                       "reservation overlaps an existing bench reservation", 409)
    if order["status"] == "REWORK":
        covered = sum(a["qty_allocated"] for a in order_allocations(order)
                      if a["status"] == "RESERVED")
        needed = order["quantity_snapshot"] - order.get("_wasted_total", 0)
        if covered < needed:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY",
                           "remaining reserved allocations do not cover the order", 422)
    reservation = new_resource({
        "bench_id": bench_id, "compound_order_id": order["id"],
        "start_at": start_s, "end_at": end_s, "status": "IN_USE",
    })
    db.bench_reservations[reservation["id"]] = reservation
    order["compounding_pharmacist_id"] = user_id
    order["status"] = "COMPOUNDING"
    touch(order)
    return success(order)


def _require_same_pharmacist(order, user_id):
    if user_id != order.get("compounding_pharmacist_id"):
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "only the compounding pharmacist may perform this step", 403)


@bp.route("/compound-orders/<rid>/complete-compounding", methods=["POST"])
def complete_compounding(rid):
    _, user_id = auth("Pharmacist")
    order = get_or_404(db.compound_orders, rid, "compound order")
    check_recall_hold(order, "complete-compounding")
    if order["status"] != "COMPOUNDING":
        raise ApiError("ERR_INVALID_STATE", "order is not COMPOUNDING", 409)
    _require_same_pharmacist(order, user_id)
    order["status"] = "FLAVORING" if order.get("flavoring_id") else "QA_PENDING"
    touch(order)
    return success(order)


@bp.route("/compound-orders/<rid>/complete-flavoring", methods=["POST"])
def complete_flavoring(rid):
    _, user_id = auth("Pharmacist")
    order = get_or_404(db.compound_orders, rid, "compound order")
    check_recall_hold(order, "complete-flavoring")
    if order["status"] != "FLAVORING":
        raise ApiError("ERR_INVALID_STATE", "order is not FLAVORING", 409)
    _require_same_pharmacist(order, user_id)
    order["status"] = "QA_PENDING"
    touch(order)
    return success(order)


def _segregation(order, user_id):
    if user_id == order.get("compounding_pharmacist_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "QA reviewer must differ from the compounding pharmacist", 422)


@bp.route("/compound-orders/<rid>/qa-pass", methods=["POST"])
def qa_pass(rid):
    _, user_id = auth("Pharmacist")
    order = get_or_404(db.compound_orders, rid, "compound order")
    check_recall_hold(order, "qa-pass")
    if order["status"] != "QA_PENDING":
        raise ApiError("ERR_INVALID_STATE", "order is not QA_PENDING", 409)
    _segregation(order, user_id)
    order["qa_pharmacist_id"] = user_id
    for a in order_allocations(order):
        if a["status"] != "RESERVED":
            continue
        a["status"] = "CONSUMED"
        a["qty_consumed"] = a["qty_allocated"]
        touch(a)
        lot = db.lots[a["lot_id"]]
        lot["qty_reserved"] -= a["qty_allocated"]
        lot["qty_dispensed"] += a["qty_allocated"]
        update_lot_exhaustion(lot)
        touch(lot)
    for r in db.bench_reservations.values():
        if r["compound_order_id"] == order["id"] and r["status"] == "IN_USE":
            r["status"] = "COMPLETED"
            touch(r)
    rx = db.prescriptions[order["prescription_id"]]
    pet = db.pets[rx["pet_id"]]
    flavoring = db.flavorings.get(order["flavoring_id"]) if order.get(
        "flavoring_id") else None
    order["final_price_cents"] = compute_final_price(order, rx, pet, flavoring)
    order["status"] = "READY_TO_DISPATCH"
    touch(order)
    return success(order)


@bp.route("/compound-orders/<rid>/qa-fail", methods=["POST"])
def qa_fail(rid):
    _, user_id = auth("Pharmacist")
    order = get_or_404(db.compound_orders, rid, "compound order")
    d = body()
    check_recall_hold(order, "qa-fail")
    if order["status"] != "QA_PENDING":
        raise ApiError("ERR_INVALID_STATE", "order is not QA_PENDING", 409)
    _segregation(order, user_id)
    waste_qty = as_int(opt(d, "waste_qty", 0), "waste_qty")
    if waste_qty < 0:
        raise ApiError("ERR_INVALID_REQUEST", "waste_qty must be >= 0", 400)
    allocs = [a for a in order_allocations(order) if a["status"] == "RESERVED"]
    total_reserved = sum(a["qty_allocated"] for a in allocs)
    if waste_qty > total_reserved:
        raise ApiError("ERR_WASTE_EXCEEDS_ON_HAND",
                       "waste qty exceeds the order's reserved units", 422)
    remaining = waste_qty
    for a in allocs:
        if remaining <= 0:
            break
        take = min(remaining, a["qty_allocated"])
        a["qty_allocated"] -= take
        touch(a)
        lot = db.lots[a["lot_id"]]
        lot["qty_reserved"] -= take
        lot["qty_wasted"] += take
        cs_append(lot, "WASTE", -take, user_id, order_id=order["id"])
        update_lot_exhaustion(lot)
        touch(lot)
        remaining -= take
    order["_wasted_total"] = order.get("_wasted_total", 0) + waste_qty
    order["status"] = "REWORK"
    touch(order)
    return success(order)


@bp.route("/compound-orders/<rid>/resume", methods=["POST"])
def resume_order(rid):
    auth("Pharmacist")
    order = get_or_404(db.compound_orders, rid, "compound order")
    if order["status"] != "RECALL_HOLD":
        raise ApiError("ERR_INVALID_STATE", "order is not in RECALL_HOLD", 409)
    check_no_active_recall(order)
    order["status"] = order["hold_origin_state"]
    order["hold_origin_state"] = None
    touch(order)
    return success(order)


@bp.route("/compound-orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    auth("Pharmacist", "PharmacyTech")
    order = get_or_404(db.compound_orders, rid, "compound order")
    if order["status"] not in ("CREATED", "ALLOCATED", "RECALL_HOLD"):
        raise ApiError("ERR_INVALID_STATE",
                       "order cannot be cancelled from its current state", 409)
    cancel_order_internal(order)
    return success(order)


# ---- payment ----

@bp.route("/compound-orders/<rid>/pay", methods=["POST"])
def pay_order(rid):
    _, user_id = auth("Owner")
    order = get_or_404(db.compound_orders, rid, "compound order")
    require_ownership(user_id, order["owner_id"])
    d = body()
    enrollment = None
    enrollment_id = d.get("enrollment_id")
    if enrollment_id is not None:
        enrollment = get_or_404(db.enrollments, enrollment_id, "enrollment")
    method = as_enum(req(d, "payment_method"), "payment_method",
                     {"CARD", "WELLNESS_CREDIT"})
    check_recall_hold(order, "pay")
    if order["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_STATE", "order is not UNPAID", 409)
    if method == "CARD":
        order["payment_status"] = "PAID"
        order["paid_via"] = "CARD"
        touch(order)
        return success(order)
    # WELLNESS_CREDIT
    if enrollment is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "enrollment_id is required for WELLNESS_CREDIT payment", 400)
    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", "enrollment is not ACTIVE", 409)
    rx = db.prescriptions[order["prescription_id"]]
    if enrollment["pet_id"] != rx["pet_id"]:
        raise ApiError("ERR_ENROLLMENT_PET_MISMATCH",
                       "enrollment pet differs from the prescription pet", 422)
    plan = db.wellness_plans[enrollment["plan_id"]]
    if rx["schedule_snapshot"] != "NON_CONTROLLED" and not plan["covers_controlled"]:
        raise ApiError("ERR_CREDIT_LIMIT",
                       "plan does not cover controlled compounds", 402)
    subtotal = order["final_price_cents"] if order["final_price_cents"] is not None \
        else order["provisional_price_cents"]
    discount = rhu(dec(subtotal) * dec(plan["discount_pct"]))
    credit_cap = rhu(Decimal("0.5") * dec(subtotal - discount))
    credits_used = min(enrollment["credits_remaining"],
                       credit_cap // plan["credit_value_cents"])
    amount_due = subtotal - discount - credits_used * plan["credit_value_cents"]
    if credits_used < 1 or amount_due < 0:
        raise ApiError("ERR_CREDIT_LIMIT",
                       "wellness credit cannot cover any share of this order", 402)
    enrollment["credits_remaining"] -= credits_used
    enrollment["credits_consumed"] += credits_used
    touch(enrollment)
    order["payment_status"] = "PAID"
    order["paid_via"] = "WELLNESS_CREDIT"
    order["_credits_used"] = credits_used
    order["_credit_enrollment_id"] = enrollment["id"]
    touch(order)
    return success(order)


@bp.route("/compound-orders/<rid>/refund", methods=["POST"])
def refund(rid):
    auth("Pharmacist")
    order = get_or_404(db.compound_orders, rid, "compound order")
    if order["payment_status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", "order is not PAID", 409)
    refund_order(order)
    return success(order)
