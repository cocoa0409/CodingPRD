"""QC report endpoints: file and decide."""

from decimal import Decimal

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_QC_REPORT_NOT_FOUND,
    ERR_ORDER_INVALID_STATE, ERR_QC_REPORT_ALREADY_DECIDED,
    ERR_SEGREGATION_OF_DUTIES, ERR_QC_HOLD_REQUIRES_REPRESS,
    ERR_PRINT_JOBS_NOT_DELIVERED,
)
from middleware import get_auth, require_role
from response import success_object
from services import risk as risk_service, allocations
from services.pricing import round_half_up_2dp
from .press_orders import get_order_or_404, maybe_fulfill_release

bp = Blueprint("qc", __name__)


@bp.route("/press-orders/<oid>/qc-reports", methods=["POST"])
def file_qc_report(oid):
    user_id, role = get_auth()
    require_role(role, ["QaInspector"])
    order = get_order_or_404(oid)
    body = request.get_json(silent=True) or {}

    units_pressed = body.get("units_pressed")
    units_rejected = body.get("units_rejected")

    if not isinstance(units_pressed, int) or isinstance(units_pressed, bool) or units_pressed <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "units_pressed must be a positive integer", 400)
    if (not isinstance(units_rejected, int) or isinstance(units_rejected, bool)
            or units_rejected < 0 or units_rejected > units_pressed):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "units_rejected must be an integer with 0 <= rejected <= pressed",
            400,
        )

    # state precondition
    if order["production_status"] != "QC_REVIEW":
        raise ApiError(ERR_ORDER_INVALID_STATE, "Order must be QC_REVIEW to file a report", 409)

    reject_rate = round_half_up_2dp(
        Decimal("100.0") * Decimal(units_rejected) / Decimal(units_pressed)
    )
    tolerance = order["tolerance_pct"]
    outcome = "HOLD" if reject_rate > Decimal(str(tolerance)) else "PASS"

    now = db.timestamp_now()
    report = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "press_order_id": order["id"],
        "units_pressed": units_pressed,
        "units_rejected": units_rejected,
        "reject_rate_pct": float(reject_rate),
        "tolerance_pct_snapshot": tolerance,
        "outcome": outcome,
        "status": "FILED",
        "decision": "NONE",
        "fault": "NONE",
        "filed_by": user_id,
        "decided_by": None,
    }
    db.qc_reports[report["id"]] = report
    return success_object(serializers.qc_report(report), 201)


@bp.route("/qc-reports/<qid>/decision", methods=["POST"])
def decide_qc_report(qid):
    user_id, role = get_auth()
    require_role(role, ["ProductionManager"])
    report = db.qc_reports.get(qid)
    if not report:
        raise ApiError(ERR_QC_REPORT_NOT_FOUND, "QC report id does not exist", 404)

    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    fault = body.get("fault")

    if decision not in ("ACCEPT", "REPRESS"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be ACCEPT or REPRESS", 400)
    if decision == "REPRESS" and fault not in ("PLANT", "CUSTOMER"):
        raise ApiError(ERR_INVALID_REQUEST, "REPRESS requires fault of PLANT or CUSTOMER", 400)

    # state precondition (priority 5)
    if report["status"] == "DECIDED":
        raise ApiError(ERR_QC_REPORT_ALREADY_DECIDED, "QC report already DECIDED", 409)

    # segregation of duties (priority 6)
    if user_id == report["filed_by"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "QC decision may not be made by the filing inspector",
            403,
        )

    order = db.press_orders[report["press_order_id"]]
    release = db.releases[order["release_id"]]

    # linked-entity gates (priority 7)
    if decision == "ACCEPT":
        if report["outcome"] != "PASS":
            raise ApiError(
                ERR_QC_HOLD_REQUIRES_REPRESS,
                "QC report outcome is HOLD; decision must be REPRESS",
                409,
            )
        for pj in db.print_jobs.values():
            if pj["press_order_id"] == order["id"] and pj["status"] not in ("DELIVERED", "CANCELLED"):
                raise ApiError(
                    ERR_PRINT_JOBS_NOT_DELIVERED,
                    "Not all non-CANCELLED print jobs are DELIVERED",
                    409,
                )

    report["status"] = "DECIDED"
    report["decision"] = decision
    report["decided_by"] = user_id
    if decision == "REPRESS":
        report["fault"] = fault
    report["version"] += 1
    report["updated_at"] = db.timestamp_now()

    good_units = report["units_pressed"] - report["units_rejected"]

    if decision == "ACCEPT":
        order["accepted_units"] += good_units
        order["pressed_units_total"] += report["units_pressed"]
        order["rejected_units_total"] += report["units_rejected"]
        order["production_status"] = "COMPLETED"
        order["version"] += 1
        order["updated_at"] = db.timestamp_now()

        # inventory credit: find-or-create zone-A lot for the release
        lot = None
        for l in db.inventory_lots.values():
            if l["release_id"] == release["id"] and l["zone"] == "A":
                lot = l
                break
        now = db.timestamp_now()
        if lot is None:
            lot = {
                "id": db.new_id(),
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "release_id": release["id"],
                "zone": "A",
                "receipt_seq": db.next_receipt_seq(release["id"]),
                "on_hand_units": 0,
                "allocated_units": 0,
                "shipped_units_cum": 0,
                "damaged_units_cum": 0,
                "received_units_cum": 0,
                "storage_daily_accrual_cents": 0,
                "storage_monthly_statement_cents": 0,
                "_receive_events": [],
                "_daily_on_hand": {},
            }
            db.inventory_lots[lot["id"]] = lot
        lot["on_hand_units"] += good_units
        lot["received_units_cum"] += good_units
        lot["version"] += 1
        lot["updated_at"] = now
        lot["_daily_on_hand"][db.today_logical().isoformat()] = lot["on_hand_units"]

        # backorder sweep
        allocations.backorder_sweep(release["id"])

        # risk recompute + possible FULFILLED
        risk_service.recompute_release_risk(release, "SCHEDULE", order["id"])
        maybe_fulfill_release(release)
    else:
        # REPRESS: bank good units, loop back to QUEUED
        order["repress_round"] += 1
        order["repress_fault"] = fault
        order["pressed_units_total"] += report["units_pressed"]
        order["rejected_units_total"] += report["units_rejected"]
        order["accepted_units"] += good_units
        order["production_status"] = "QUEUED"
        order["version"] += 1
        order["updated_at"] = db.timestamp_now()

        risk_service.recompute_release_risk(release, "REPRESS", order["id"])

    return success_object(serializers.qc_report(report))
