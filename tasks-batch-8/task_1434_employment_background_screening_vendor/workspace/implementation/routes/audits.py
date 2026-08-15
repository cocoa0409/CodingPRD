"""VendorAccuracyAudit endpoints, including finalize + re-screen sweep."""
from flask import Blueprint, request

import db
from db import bump
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_AUDIT_NOT_DRAFT, ERR_AUDIT_OVERLAP,
)
from middleware import (
    auth, require_role, get_body, req_str, req_int, invalid,
    parse_pagination, sort_key, ALL_ROLES,
)
from response import success_object, success_list
from services import (
    mismatch_rate_bps, refresh_vendor_accuracy, cancel_order_cascade,
)
from timeutil import parse_iso

bp = Blueprint("audits", __name__)

FAIL_THRESHOLD_BPS = 200


@bp.route("/vendor-accuracy-audits", methods=["POST"])
def create_audit():
    auth_uid, role = auth()
    require_role(role, {"Auditor"})
    body = get_body()
    # existence (priority 3): body vendor_id must resolve
    raw_vendor = body.get("vendor_id")
    if raw_vendor is not None and raw_vendor not in db.vendors:
        raise ApiError(ERR_NOT_FOUND, 404, "Vendor not found")
    # shape (priority 3.8)
    vendor_id = req_str(body, "vendor_id")
    raw_start = req_str(body, "period_start")
    raw_end = req_str(body, "period_end")
    try:
        period_start = parse_iso(raw_start)
        period_end = parse_iso(raw_end)
    except (ValueError, TypeError):
        invalid("period_start/period_end must be ISO 8601 instants")
    sample_size = req_int(body, "sample_size", minimum=1)
    mismatches = req_int(body, "mismatches_found", minimum=0)
    if mismatches > sample_size:
        invalid("mismatches_found may not exceed sample_size")
    if period_end <= period_start:
        invalid("period_end must be strictly after period_start")
    # uniqueness (priority 6.5): half-open overlap per vendor
    for existing in db.audits.values():
        if existing["vendor_id"] != vendor_id:
            continue
        if (period_start < existing["period_end"]
                and period_end > existing["period_start"]):
            raise ApiError(ERR_AUDIT_OVERLAP, 409,
                           "Audit period overlaps an existing audit for this vendor")
    audit = db.new_entity({
        "vendor_id": vendor_id,
        "period_start": period_start,
        "period_end": period_end,
        "sample_size": sample_size,
        "mismatches_found": mismatches,
        "mismatch_rate_bps": mismatch_rate_bps(mismatches, sample_size),
        "status": "DRAFT",
        "rescreen_order_ids": [],
    })
    db.audits[audit["id"]] = audit
    refresh_vendor_accuracy(vendor_id)
    return success_object(audit, 201)


@bp.route("/vendor-accuracy-audits", methods=["GET"])
def list_audits():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.audits.values())
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        rows = [a for a in rows if a["vendor_id"] == vendor_id]
    rows.sort(key=sort_key)
    total = len(rows)
    return success_list(rows[offset:offset + limit], limit, offset, total)


def _load_audit(audit_id):
    audit = db.audits.get(audit_id)
    if audit is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Audit not found")
    return audit


@bp.route("/vendor-accuracy-audits/<audit_id>", methods=["GET"])
def get_audit(audit_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return success_object(_load_audit(audit_id), 200)


@bp.route("/vendor-accuracy-audits/<audit_id>/finalize", methods=["POST"])
def finalize_audit(audit_id):
    auth_uid, role = auth()
    require_role(role, {"Auditor"})
    audit = _load_audit(audit_id)
    if audit["status"] != "DRAFT":
        raise ApiError(ERR_AUDIT_NOT_DRAFT, 409, "Finalize requires audit DRAFT")
    audit["status"] = "FINALIZED"
    bump(audit)
    vendor = db.vendors[audit["vendor_id"]]
    refresh_vendor_accuracy(vendor["id"])
    fail = audit["mismatch_rate_bps"] > FAIL_THRESHOLD_BPS
    if fail:
        if vendor["status"] == "ACTIVE":
            vendor["status"] = "PROBATION"
            bump(vendor)
        elif vendor["status"] == "PROBATION":
            vendor["status"] = "DECERTIFIED"
            bump(vendor)
            # In-flight cancellation cascade for this vendor.
            for order in list(db.orders.values()):
                if (order["vendor_id"] == vendor["id"]
                        and order["fulfillment_status"] == "DISPATCHED"):
                    cancel_order_cascade(order)
        # Re-screen sweep (runs on every failing audit).
        selected = []
        for report in db.reports.values():
            if report["vendor_id"] != vendor["id"]:
                continue
            if report["status"] != "DELIVERED":
                continue
            if not (audit["period_start"] <= report["delivered_at"]
                    <= audit["period_end"]):
                continue
            order = db.orders.get(report["order_id"])
            if order is None:
                continue
            if order["fulfillment_status"] != "REPORT_RECEIVED":
                continue
            if order["recommended_outcome"] not in ("IA_REQUIRED",
                                                    "ADVERSE_ELIGIBLE"):
                continue
            selected.append(report)
        selected.sort(key=lambda r: (r["delivered_at"], r["created_at"],
                                     r["_seq"]))
        for report in selected:
            order = db.orders[report["order_id"]]
            rescreen = db.new_entity({
                "candidate_id": order["candidate_id"],
                "position_id": order["position_id"],
                "order_type": "RESCREEN",
                "rescreen_of_order_id": order["id"],
                "vendor_id": None,
                "conditional_offer_extended_at":
                    order["conditional_offer_extended_at"],
                "fulfillment_status": "CONSENT_CAPTURED",
                "adjudication_status": "NOT_STARTED",
                "dispatched_at": None,
                "sla_due_at": None,
                "escalation_level": 0,
                "provisional_fee_cents": None,
                "final_fee_cents": None,
                "pinned_package_id": None,
                "pinned_package_version": None,
                "pinned_matrix_id": None,
                "pinned_matrix_version": None,
                "recommended_outcome": None,
                "adverse_initiated_by_user_id": None,
            })
            db.orders[rescreen["id"]] = rescreen
            audit["rescreen_order_ids"].append(rescreen["id"])
        if audit["rescreen_order_ids"]:
            bump(audit)
    return success_object(audit, 200)
