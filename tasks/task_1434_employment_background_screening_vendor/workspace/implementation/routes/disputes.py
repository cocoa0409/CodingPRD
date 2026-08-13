"""Dispute endpoints: file, list, get, resolve (UPHELD/AMENDED), withdraw."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import bump
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REPORT_NOT_ACTIONABLE, ERR_ADJ_TERMINAL,
    ERR_DISPUTE_ALREADY_OPEN, ERR_DISPUTE_WINDOW, ERR_DISPUTE_NOT_OPEN,
)
from middleware import (
    auth, require_role, get_body, req_str, req_enum, forbid, invalid,
    parse_pagination, sort_key, ALL_ROLES,
)
from response import success_object, success_list
from services import (
    report_of_order, case_of_order, refresh_case, close_case_hold,
    dispute_overdue, active_rule_for, evaluate_finding, recommended_outcome,
)
from routes.reports import validate_finding_shape, create_finding_rows
from timeutil import now

bp = Blueprint("disputes", __name__)

DISPUTE_OUTCOMES = ("UPHELD", "AMENDED")
DISPUTE_WINDOW_DAYS = 30


@bp.route("/disputes", methods=["POST"])
def file_dispute():
    uid, role = auth()
    require_role(role, {"Candidate"})
    body = get_body()
    # existence (3): body order_id must resolve
    raw_order = body.get("order_id")
    if raw_order is not None and raw_order not in db.orders:
        raise ApiError(ERR_NOT_FOUND, 404, "Order not found")
    order_id = req_str(body, "order_id")
    order = db.orders[order_id]
    # entity-backed ownership (2.5)
    if uid != order["candidate_id"]:
        forbid("Candidate may only dispute their own order")
    # existence (3): optional finding_ids must resolve, left-to-right
    finding_ids = body.get("finding_ids")
    if finding_ids is not None:
        if not isinstance(finding_ids, list):
            invalid("finding_ids must be an array")
        for fid in finding_ids:
            if not isinstance(fid, str) or fid not in db.findings:
                raise ApiError(ERR_NOT_FOUND, 404, "Finding not found")
    # shape (3.8)
    reason = req_str(body, "reason")
    if len(reason) < 10:
        invalid("reason must be at least 10 characters")
    # state (4): an actionable report exists
    report = report_of_order(order["id"])
    if report is None or report["status"] not in ("DELIVERED", "AMENDED"):
        raise ApiError(ERR_REPORT_NOT_ACTIONABLE, 409,
                       "Dispute requires a report in DELIVERED or AMENDED")
    # state (4): adjudication must be reviewable or pre-adverse
    if order["adjudication_status"] not in ("PENDING_REVIEW",
                                            "PRE_ADVERSE_PENDING"):
        raise ApiError(ERR_ADJ_TERMINAL, 409,
                       "Dispute requires adjudication PENDING_REVIEW or "
                       "PRE_ADVERSE_PENDING")
    # uniqueness (6): one open dispute per order
    for existing in db.disputes.values():
        if (existing["order_id"] == order["id"]
                and existing["status"] == "UNDER_REINVESTIGATION"):
            raise ApiError(ERR_DISPUTE_ALREADY_OPEN, 409,
                           "An UNDER_REINVESTIGATION dispute already exists "
                           "for this order")
    # temporal (7.1): dispute window is 30 calendar days after delivery
    filed_at = now()
    if filed_at > report["delivered_at"] + timedelta(days=DISPUTE_WINDOW_DAYS):
        raise ApiError(ERR_DISPUTE_WINDOW, 409,
                       "Dispute filed after report.delivered_at + 30 days")
    dispute = db.new_entity({
        "order_id": order["id"],
        "candidate_id": order["candidate_id"],
        "reason": reason,
        "finding_ids": list(finding_ids) if finding_ids is not None else None,
        "filed_at": filed_at,
        "resolved_at": None,
        "overdue": False,
        "outcome": None,
        "status": "UNDER_REINVESTIGATION",
    })
    db.disputes[dispute["id"]] = dispute
    # cascades
    report["status"] = "DISPUTED"
    bump(report)
    order["adjudication_status"] = "DISPUTE_HOLD"
    bump(order)
    case = case_of_order(order["id"])
    if case is not None:
        refresh_case(case)
        if case["status"] in ("WAITING_PERIOD", "ELIGIBLE_FOR_FINAL"):
            case["status"] = "DISPUTE_HOLD"
            case["hold_started_at"] = now()
            bump(case)
    return success_object(dispute, 201)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.disputes.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        rows = [d for d in rows if d["order_id"] == order_id]
    candidate_id = request.args.get("candidate_id")
    if candidate_id is not None:
        rows = [d for d in rows if d["candidate_id"] == candidate_id]
    status = request.args.get("status")
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    rows.sort(key=sort_key)
    total = len(rows)
    return success_list(rows[offset:offset + limit], limit, offset, total)


def _load_dispute(dispute_id):
    dispute = db.disputes.get(dispute_id)
    if dispute is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Dispute not found")
    return dispute


@bp.route("/disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return success_object(_load_dispute(dispute_id), 200)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
def resolve_dispute(dispute_id):
    uid, role = auth()
    require_role(role, {"VendorAgent"})
    dispute = _load_dispute(dispute_id)
    order = db.orders.get(dispute["order_id"])
    report = report_of_order(dispute["order_id"]) if order else None
    # entity-backed ownership (2.5): resolving vendor owns the report
    if report is None or uid != report["vendor_id"]:
        forbid("Only the report's vendor may resolve this dispute")
    body = get_body()
    # shape (3.8)
    outcome = req_enum(body, "outcome", DISPUTE_OUTCOMES)
    corrected = body.get("corrected_findings")
    parsed = None
    if outcome == "AMENDED":
        if not isinstance(corrected, list) or len(corrected) < 1:
            invalid("corrected_findings must be a non-empty array when outcome "
                    "is AMENDED")
        parsed = [validate_finding_shape(f) for f in corrected]
    # state (4)
    if dispute["status"] != "UNDER_REINVESTIGATION":
        raise ApiError(ERR_DISPUTE_NOT_OPEN, 409,
                       "Resolve requires dispute UNDER_REINVESTIGATION")
    resolved_at = now()
    case = case_of_order(order["id"])
    if outcome == "UPHELD":
        report["status"] = "UPHELD"
        bump(report)
        order["adjudication_status"] = "PENDING_REVIEW"
        bump(order)
        if case is not None and case["status"] == "DISPUTE_HOLD":
            close_case_hold(case, resolved_at)
        dispute["outcome"] = "UPHELD"
        dispute["status"] = "RESOLVED_UPHELD"
    else:  # AMENDED
        # replace findings; re-evaluate against CURRENT active jurisdiction
        # rule but the order's PINNED matrix (even if since retired)
        for old in [f for f in db.findings.values()
                    if f["report_id"] == report["id"]]:
            del db.findings[old["id"]]
        new_findings = create_finding_rows(report, parsed)
        position = db.positions.get(order["position_id"])
        rule = active_rule_for(position["jurisdiction_code"])
        matrix = db.matrices.get(order["pinned_matrix_id"])
        for f in new_findings:
            evaluate_finding(f, rule, position, report["delivered_at"], matrix)
        order["recommended_outcome"] = recommended_outcome(new_findings)
        report["status"] = "AMENDED"
        bump(report)
        order["adjudication_status"] = "PENDING_REVIEW"
        bump(order)
        if case is not None and case["status"] == "DISPUTE_HOLD":
            case["status"] = "ABORTED"
            case["hold_started_at"] = None
            bump(case)
        dispute["outcome"] = "AMENDED"
        dispute["status"] = "RESOLVED_AMENDED"
    dispute["resolved_at"] = resolved_at
    dispute["overdue"] = dispute_overdue(dispute["filed_at"], resolved_at)
    bump(dispute)
    return success_object(dispute, 200)


@bp.route("/disputes/<dispute_id>/withdraw", methods=["POST"])
def withdraw_dispute(dispute_id):
    uid, role = auth()
    require_role(role, {"Candidate"})
    dispute = _load_dispute(dispute_id)
    # entity-backed ownership (2.5)
    if uid != dispute["candidate_id"]:
        forbid("Candidate may only withdraw their own dispute")
    if dispute["status"] != "UNDER_REINVESTIGATION":
        raise ApiError(ERR_DISPUTE_NOT_OPEN, 409,
                       "Withdraw requires dispute UNDER_REINVESTIGATION")
    resolved_at = now()
    order = db.orders.get(dispute["order_id"])
    report = report_of_order(dispute["order_id"])
    if report is not None and report["status"] == "DISPUTED":
        report["status"] = "DELIVERED"
        bump(report)
    if order is not None and order["adjudication_status"] == "DISPUTE_HOLD":
        order["adjudication_status"] = "PENDING_REVIEW"
        bump(order)
    case = case_of_order(dispute["order_id"])
    if case is not None and case["status"] == "DISPUTE_HOLD":
        close_case_hold(case, resolved_at)
    dispute["status"] = "WITHDRAWN"
    dispute["resolved_at"] = resolved_at
    dispute["overdue"] = dispute_overdue(dispute["filed_at"], resolved_at)
    bump(dispute)
    return success_object(dispute, 200)
