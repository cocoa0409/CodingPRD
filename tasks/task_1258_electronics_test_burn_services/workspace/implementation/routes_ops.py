"""Routes: customer equipment, maintenance orders, ESD audits, RMA cases, disposition reviews."""
from flask import Blueprint

from auth import require_roles, ALL_ROLES
from db import db
from envelope import success
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_FORBIDDEN_OWNERSHIP,
    ERR_MAINTENANCE_WINDOW_CONFLICT, ERR_MISSING_CORRECTIVE_ACTION,
    ERR_REVIEW_PENDING, bad_request, invalid_state,
)
from services import (
    stamp_new, touch, get_or_404, compute_suggestion,
    equipment_effective_status,
    ser_equipment, ser_maintenance_order, ser_audit, ser_rma, ser_review,
)
from util import (
    parse_dt, fmt_like, sec, json_body, require_fields, check_enum, check_int, check_str,
)
from routes_core import paginate, filter_list
from routes_lots import _create_pending_review

bp = Blueprint("ops", __name__)


# ---------------------------------------------------------------------------
# customer equipment
# ---------------------------------------------------------------------------

@bp.route("/api/customer-equipment", methods=["POST"])
def create_equipment():
    require_roles("OperationsManager")
    data = json_body()
    require_fields(data, "customer_id", "equipment_type", "serial_number",
                   "calibration_interval_days", "last_calibrated_at")
    check_str(data["customer_id"], "customer_id")
    etype = check_enum(data["equipment_type"], ("TESTER", "HANDLER", "PROBER"),
                       "equipment_type")
    serial = check_str(data["serial_number"], "serial_number")
    interval = check_int(data["calibration_interval_days"],
                         "calibration_interval_days", minimum=1)
    last_dt = parse_dt(data["last_calibrated_at"], "last_calibrated_at")
    get_or_404(db.customers, data["customer_id"], "customer")
    from datetime import timedelta
    next_due_dt = last_dt + timedelta(days=interval)
    rec = stamp_new({
        "customer_id": data["customer_id"], "equipment_type": etype,
        "serial_number": serial, "calibration_interval_days": interval,
        "last_calibrated_at": data["last_calibrated_at"],
        "next_calibration_due": fmt_like(next_due_dt, data["last_calibrated_at"]),
        "_next_due_dt": next_due_dt,
        "status": "IN_SERVICE",
    })
    db.equipment[rec["id"]] = rec
    return success(ser_equipment(rec), "object", 201)


@bp.route("/api/customer-equipment/<equipment_id>", methods=["GET"])
def get_equipment(equipment_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.equipment, equipment_id, "customer equipment")
    return success(ser_equipment(rec), "object", 200)


@bp.route("/api/customer-equipment", methods=["GET"])
def list_equipment():
    require_roles(*ALL_ROLES)
    items = filter_list(db.equipment, [("customer_id", "customer_id")])
    from flask import request as _req
    if _req.args.get("status") is not None:
        sf = _req.args.get("status")
        items = [e for e in items if equipment_effective_status(e) == sf]
    page, meta = paginate(items)
    return success([ser_equipment(e) for e in page], "array", 200, meta)


@bp.route("/api/customer-equipment/<equipment_id>/return", methods=["POST"])
def return_equipment(equipment_id):
    require_roles("OperationsManager")
    rec = get_or_404(db.equipment, equipment_id, "customer equipment")
    if equipment_effective_status(rec) not in ("IN_SERVICE", "CALIBRATION_DUE", "IN_MAINTENANCE"):
        raise invalid_state("Equipment is already RETURNED")
    rec["status"] = "RETURNED"
    touch(rec)
    return success(ser_equipment(rec), "object", 200)


# ---------------------------------------------------------------------------
# maintenance orders
# ---------------------------------------------------------------------------

@bp.route("/api/maintenance-orders", methods=["POST"])
def create_maintenance_order():
    require_roles("OperationsManager")
    data = json_body()
    require_fields(data, "target_type", "target_id", "kind", "window_start", "window_end")
    target_type = check_enum(data["target_type"], ("EQUIPMENT", "CHAMBER"), "target_type")
    check_str(data["target_id"], "target_id")
    kind = check_enum(data["kind"], ("CALIBRATION", "REPAIR", "PREVENTIVE"), "kind")
    ws = parse_dt(data["window_start"], "window_start")
    we = parse_dt(data["window_end"], "window_end")
    # existence: target per polymorphic target_type
    if target_type == "EQUIPMENT":
        get_or_404(db.equipment, data["target_id"], "customer equipment")
    else:
        get_or_404(db.chambers, data["target_id"], "chamber")
    # window well-formed: closed interval requires window_start <= window_end
    if ws > we:
        raise bad_request("window_start must be at or before window_end")
    # closed-interval conflict against live orders on the same target
    for ex in db.maintenance_orders.values():
        if ex["target_type"] != target_type or ex["target_id"] != data["target_id"]:
            continue
        if ex["status"] not in ("OPEN", "IN_PROGRESS"):
            continue
        if ws <= ex["_window_end_dt"] and ex["_window_start_dt"] <= we:
            raise ApiError(ERR_MAINTENANCE_WINDOW_CONFLICT, 409,
                           "Maintenance window conflicts with an existing order")
    rec = stamp_new({
        "target_type": target_type, "target_id": data["target_id"], "kind": kind,
        "window_start": data["window_start"], "window_end": data["window_end"],
        "_window_start_dt": ws, "_window_end_dt": we,
        "status": "OPEN",
    })
    db.maintenance_orders[rec["id"]] = rec
    return success(ser_maintenance_order(rec), "object", 201)


@bp.route("/api/maintenance-orders/<order_id>", methods=["GET"])
def get_maintenance_order(order_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.maintenance_orders, order_id, "maintenance order")
    return success(ser_maintenance_order(rec), "object", 200)


@bp.route("/api/maintenance-orders", methods=["GET"])
def list_maintenance_orders():
    require_roles(*ALL_ROLES)
    items = filter_list(db.maintenance_orders, [
        ("target_id", "target_id"), ("target_type", "target_type"), ("status", "status"),
    ])
    page, meta = paginate(items)
    return success([ser_maintenance_order(o) for o in page], "array", 200, meta)


def _maintenance_target(order):
    if order["target_type"] == "EQUIPMENT":
        return db.equipment[order["target_id"]]
    return db.chambers[order["target_id"]]


@bp.route("/api/maintenance-orders/<order_id>/start", methods=["POST"])
def start_maintenance_order(order_id):
    require_roles("OperationsManager")
    order = get_or_404(db.maintenance_orders, order_id, "maintenance order")
    if order["status"] != "OPEN":
        raise invalid_state("Only an OPEN order can be started")
    if not (sec(order["_window_start_dt"]) <= sec(db.clock_dt) <= sec(order["_window_end_dt"])):
        raise invalid_state("Current time is outside the maintenance window")
    target = _maintenance_target(order)
    if target["status"] in ("RETURNED", "OFFLINE"):
        raise invalid_state("Maintenance target is no longer in service")
    if order["target_type"] == "EQUIPMENT":
        target["status"] = "IN_MAINTENANCE"
    else:
        target["status"] = "MAINTENANCE"
    touch(target)
    order["status"] = "IN_PROGRESS"
    touch(order)
    return success(ser_maintenance_order(order), "object", 200)


@bp.route("/api/maintenance-orders/<order_id>/complete", methods=["POST"])
def complete_maintenance_order(order_id):
    require_roles("OperationsManager")
    order = get_or_404(db.maintenance_orders, order_id, "maintenance order")
    if order["status"] != "IN_PROGRESS":
        raise invalid_state("Only an IN_PROGRESS order can be completed")
    target = _maintenance_target(order)
    if order["target_type"] == "EQUIPMENT":
        target["status"] = "IN_SERVICE"
        if order["kind"] == "CALIBRATION":
            from datetime import timedelta
            target["last_calibrated_at"] = db.clock_raw
            next_due_dt = db.clock_dt + timedelta(days=target["calibration_interval_days"])
            target["next_calibration_due"] = fmt_like(next_due_dt, db.clock_raw)
            target["_next_due_dt"] = next_due_dt
    else:
        target["status"] = "ONLINE"
    touch(target)
    order["status"] = "DONE"
    touch(order)
    return success(ser_maintenance_order(order), "object", 200)


@bp.route("/api/maintenance-orders/<order_id>/cancel", methods=["POST"])
def cancel_maintenance_order(order_id):
    require_roles("OperationsManager")
    order = get_or_404(db.maintenance_orders, order_id, "maintenance order")
    if order["status"] != "OPEN":
        raise invalid_state("Only an OPEN order can be cancelled")
    order["status"] = "CANCELLED"
    touch(order)
    return success(ser_maintenance_order(order), "object", 200)


# ---------------------------------------------------------------------------
# ESD audits
# ---------------------------------------------------------------------------

@bp.route("/api/esd-audits", methods=["POST"])
def create_audit():
    uid, role = require_roles("QualityEngineer")
    data = json_body()
    require_fields(data, "area_code", "findings")
    area_code = check_str(data["area_code"], "area_code")
    findings = data["findings"]
    if not isinstance(findings, list):
        raise bad_request("findings must be an array")
    for f in findings:
        if not isinstance(f, dict):
            raise bad_request("findings entries must be objects")
        check_enum(f.get("severity"), ("MINOR", "MAJOR"), "severity")
    rec = stamp_new({
        "area_code": area_code, "findings": findings, "corrective_actions": [],
        "outcome": None, "auditor_user_id": uid, "status": "OPEN",
    })
    db.audits[rec["id"]] = rec
    return success(ser_audit(rec), "object", 201)


@bp.route("/api/esd-audits/<audit_id>", methods=["GET"])
def get_audit(audit_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.audits, audit_id, "ESD audit")
    return success(ser_audit(rec), "object", 200)


@bp.route("/api/esd-audits", methods=["GET"])
def list_audits():
    require_roles(*ALL_ROLES)
    items = filter_list(db.audits, [("area_code", "area_code"), ("status", "status")])
    page, meta = paginate(items)
    return success([ser_audit(a) for a in page], "array", 200, meta)


@bp.route("/api/esd-audits/<audit_id>/close", methods=["POST"])
def close_audit(audit_id):
    require_roles("QualityEngineer")
    rec = get_or_404(db.audits, audit_id, "ESD audit")
    if rec["status"] != "OPEN":
        raise invalid_state("Only an OPEN audit can be closed")
    data = json_body()
    require_fields(data, "corrective_actions")
    actions = data["corrective_actions"]
    if not isinstance(actions, list):
        raise bad_request("corrective_actions must be an array")
    covered = set()
    for a in actions:
        if not isinstance(a, dict) or "finding_index" not in a:
            raise bad_request("corrective_actions entries must carry finding_index and action")
        covered.add(a["finding_index"])
    major_indices = [
        i for i, f in enumerate(rec["findings"]) if f.get("severity") == "MAJOR"
    ]
    if any(i not in covered for i in major_indices):
        raise ApiError(ERR_MISSING_CORRECTIVE_ACTION, 422,
                       "Every MAJOR finding index requires a corrective action")
    rec["corrective_actions"] = actions
    if not rec["findings"]:
        rec["outcome"] = "PASS"
    elif major_indices:
        rec["outcome"] = "FAIL"
    else:
        rec["outcome"] = "PASS_WITH_MINOR"
    rec["status"] = "CLOSED"
    touch(rec)
    return success(ser_audit(rec), "object", 200)


# ---------------------------------------------------------------------------
# RMA cases
# ---------------------------------------------------------------------------

@bp.route("/api/rma-cases", methods=["POST"])
def create_rma_case():
    uid, role = require_roles("CustomerRep")
    data = json_body()
    require_fields(data, "lot_id", "unit_id", "failure_mode")
    check_str(data["lot_id"], "lot_id")
    check_str(data["unit_id"], "unit_id")
    failure_mode = check_str(data["failure_mode"], "failure_mode")
    lot = get_or_404(db.lots, data["lot_id"], "lot")
    if lot["customer_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "CustomerRep may only open RMA cases for their own lots")
    unit = get_or_404(db.units, data["unit_id"], "unit")
    from services import unit_state
    status, _ = unit_state(unit)
    if lot["status"] != "SHIPPED" or unit["lot_id"] != lot["id"] or status != "PASSED":
        raise invalid_state(
            "RMA requires a PASSED unit belonging to the referenced SHIPPED lot")
    rec = stamp_new({
        "lot_id": lot["id"], "unit_id": unit["id"], "failure_mode": failure_mode,
        "fa_status": "INTAKE", "fa_conclusion": None, "created_by_customer_id": uid,
    })
    db.rma_cases[rec["id"]] = rec
    return success(ser_rma(rec), "object", 201)


@bp.route("/api/rma-cases/<rma_id>", methods=["GET"])
def get_rma_case(rma_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.rma_cases, rma_id, "RMA case")
    return success(ser_rma(rec), "object", 200)


@bp.route("/api/rma-cases", methods=["GET"])
def list_rma_cases():
    require_roles(*ALL_ROLES)
    items = filter_list(db.rma_cases, [
        ("lot_id", "lot_id"), ("unit_id", "unit_id"), ("fa_status", "fa_status"),
    ])
    page, meta = paginate(items)
    return success([ser_rma(r) for r in page], "array", 200, meta)


@bp.route("/api/rma-cases/<rma_id>/start-fa", methods=["POST"])
def start_fa(rma_id):
    require_roles("QualityEngineer")
    rec = get_or_404(db.rma_cases, rma_id, "RMA case")
    if rec["fa_status"] != "INTAKE":
        raise invalid_state("Only an INTAKE case can start failure analysis")
    rec["fa_status"] = "FA_IN_PROGRESS"
    touch(rec)
    return success(ser_rma(rec), "object", 200)


@bp.route("/api/rma-cases/<rma_id>/complete-fa", methods=["POST"])
def complete_fa(rma_id):
    require_roles("QualityEngineer")
    rec = get_or_404(db.rma_cases, rma_id, "RMA case")
    data = json_body()
    require_fields(data, "fa_conclusion")
    conclusion = check_enum(
        data["fa_conclusion"],
        ("TEST_ESCAPE", "CUSTOMER_INDUCED", "NO_TROUBLE_FOUND"),
        "fa_conclusion",
    )
    if rec["fa_status"] != "FA_IN_PROGRESS":
        raise invalid_state("Only an FA_IN_PROGRESS case can complete failure analysis")
    rec["fa_status"] = "FA_COMPLETE"
    rec["fa_conclusion"] = conclusion
    touch(rec)
    return success(ser_rma(rec), "object", 200)


@bp.route("/api/rma-cases/<rma_id>/close", methods=["POST"])
def close_rma(rma_id):
    require_roles("QualityEngineer")
    rec = get_or_404(db.rma_cases, rma_id, "RMA case")
    if rec["fa_status"] != "FA_COMPLETE":
        raise invalid_state("Only an FA_COMPLETE case can be closed")
    rec["fa_status"] = "CLOSED"
    touch(rec)
    if rec["fa_conclusion"] == "TEST_ESCAPE":
        lot = db.lots[rec["lot_id"]]
        unit = db.units[rec["unit_id"]]
        # escaped unit flips to FAILED with current_bin nulled
        unit["force_failed"] = True
        touch(unit)
        if lot["status"] == "SHIPPED":
            lot["status"] = "CONTAINED"
        lot["suggested_disposition"] = compute_suggestion(lot)
        touch(lot)
        _create_pending_review(lot)
    return success(ser_rma(rec), "object", 200)


# ---------------------------------------------------------------------------
# lot disposition reviews
# ---------------------------------------------------------------------------

@bp.route("/api/lot-disposition-reviews", methods=["POST"])
def create_review():
    require_roles("QualityEngineer")
    data = json_body()
    require_fields(data, "lot_id")
    check_str(data["lot_id"], "lot_id")
    lot = get_or_404(db.lots, data["lot_id"], "lot")
    if lot["status"] not in ("AWAITING_DISPOSITION", "CONTAINED"):
        raise invalid_state(
            "A review may only be opened for an AWAITING_DISPOSITION or CONTAINED lot")
    pending = any(
        rv["lot_id"] == lot["id"] and rv["status"] == "PENDING"
        for rv in db.reviews.values()
    )
    if pending:
        raise ApiError(ERR_REVIEW_PENDING, 409,
                       "A PENDING review already exists for this lot")
    rec = _create_pending_review(lot)
    return success(ser_review(rec), "object", 201)


@bp.route("/api/lot-disposition-reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.reviews, review_id, "lot disposition review")
    return success(ser_review(rec), "object", 200)


@bp.route("/api/lot-disposition-reviews", methods=["GET"])
def list_reviews():
    require_roles(*ALL_ROLES)
    items = filter_list(db.reviews, [("lot_id", "lot_id"), ("status", "status")])
    page, meta = paginate(items)
    return success([ser_review(r) for r in page], "array", 200, meta)


@bp.route("/api/lot-disposition-reviews/<review_id>/decide", methods=["POST"])
def decide_review(review_id):
    uid, role = require_roles("QualityEngineer")
    rec = get_or_404(db.reviews, review_id, "lot disposition review")
    data = json_body()
    require_fields(data, "decision", "rationale")
    decision = check_enum(data["decision"], ("SHIP", "SCRAP", "REWORK"), "decision")
    rationale = check_str(data["rationale"], "rationale")
    if rec["status"] != "PENDING":
        raise invalid_state("Only a PENDING review can be decided")
    lot = db.lots[rec["lot_id"]]
    rec["decision"] = decision
    rec["rationale"] = rationale
    rec["decided_by_user_id"] = uid
    rec["status"] = "DECIDED"
    touch(rec)
    if decision == "SHIP":
        lot["status"] = "SHIPPED"
    elif decision == "SCRAP":
        lot["status"] = "SCRAPPED"
    else:  # REWORK: full reset of the lot's test genealogy
        lot["status"] = "QUEUED"
        for u in [u for u in db.units.values() if u["lot_id"] == lot["id"]]:
            u["retest_count"] = 0
            u["force_failed"] = False
            touch(u)
        for r in db.results.values():
            if r["lot_id"] == lot["id"] and not r["voided"]:
                r["excluded_from_tally"] = True
    touch(lot)
    return success(ser_review(rec), "object", 200)
