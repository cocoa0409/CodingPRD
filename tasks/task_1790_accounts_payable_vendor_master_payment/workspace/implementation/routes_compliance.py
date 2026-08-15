"""Watchlist entries, screening checks, sanctions review cases."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    raise_err,
)
from middleware import (
    require_auth,
    require_role,
    get_body,
    req_str,
    opt_str,
    get_or_404,
    paginate,
)
from response import ok, ok_list

bp = Blueprint("compliance", __name__)


@bp.route("/watchlist-entries", methods=["POST"])
def create_watchlist_entry():
    ctx = require_auth()
    require_role(ctx, ["ComplianceOfficer"])
    body = get_body()
    name_pattern = req_str(body, "name_pattern")
    severity = body.get("severity")
    if severity not in ("BLOCK", "REVIEW"):
        raise_err(ERR_INVALID_REQUEST, "severity must be one of BLOCK, REVIEW.")
    list_source = req_str(body, "list_source")
    entry = db.stamp_new({
        "id": db.new_id(),
        "name_pattern": name_pattern,
        "severity": severity,
        "list_source": list_source,
        "status": "ACTIVE",
    })
    db.watchlist_entries[entry["id"]] = entry
    svc.audit("WatchlistEntry", entry["id"], "CREATE", ctx)
    return ok(entry, status=201)


@bp.route("/watchlist-entries/<entry_id>/retire", methods=["POST"])
def retire_watchlist_entry(entry_id):
    ctx = require_auth()
    require_role(ctx, ["ComplianceOfficer"])
    entry = get_or_404(db.watchlist_entries, entry_id, "WatchlistEntry")
    if entry["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Watchlist entry in status %s cannot be retired." % entry["status"])
    entry["status"] = "RETIRED"
    db.touch(entry)
    svc.audit("WatchlistEntry", entry["id"], "RETIRE", ctx)
    return ok(entry)


@bp.route("/screening-checks", methods=["GET"])
def list_screening_checks():
    require_auth()
    items = list(db.screening_checks.values())
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        items = [c for c in items if c["vendor_id"] == vendor_id]
    payment_id = request.args.get("payment_id")
    if payment_id is not None:
        items = [c for c in items if c.get("payment_id") == payment_id]
    matched = request.args.get("matched_watchlist_entry_id")
    if matched is not None:
        items = [c for c in items if c.get("matched_watchlist_entry_id") == matched]
    result = request.args.get("result")
    if result is not None:
        items = [c for c in items if c["result"] == result]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)


@bp.route("/screening-checks/<check_id>", methods=["GET"])
def get_screening_check(check_id):
    require_auth()
    return ok(get_or_404(db.screening_checks, check_id, "ScreeningCheck"))


@bp.route("/sanctions-cases", methods=["GET"])
def list_sanctions_cases():
    require_auth()
    items = list(db.sanctions_cases.values())
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        items = [c for c in items if c["vendor_id"] == vendor_id]
    payment_id = request.args.get("payment_id")
    if payment_id is not None:
        items = [c for c in items if c.get("payment_id") == payment_id]
    check_id = request.args.get("screening_check_id")
    if check_id is not None:
        items = [c for c in items if c["screening_check_id"] == check_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)


@bp.route("/sanctions-cases/<case_id>", methods=["GET"])
def get_sanctions_case(case_id):
    require_auth()
    return ok(get_or_404(db.sanctions_cases, case_id, "SanctionsReviewCase"))


@bp.route("/sanctions-cases/<case_id>/disposition", methods=["POST"])
def disposition_case(case_id):
    ctx = require_auth()
    require_role(ctx, ["ComplianceOfficer"])
    body = get_body()
    decision = body.get("decision")
    if decision not in ("CLEARED", "CONFIRMED_HIT"):
        raise_err(ERR_INVALID_REQUEST, "decision must be one of CLEARED, CONFIRMED_HIT.")
    note = opt_str(body, "disposition_note")
    if note is None:
        note = opt_str(body, "note")
    case = get_or_404(db.sanctions_cases, case_id, "SanctionsReviewCase")
    if case["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Sanctions review case in status %s cannot be dispositioned." % case["status"])

    case["status"] = decision
    case["dispositioned_by_user_id"] = ctx.user_id
    if note is not None:
        case["disposition_note"] = note
    db.touch(case)
    svc.audit("SanctionsReviewCase", case["id"], "DISPOSITION", ctx)

    vendor = db.vendors.get(case["vendor_id"])
    if vendor is not None:
        if decision == "CLEARED":
            # reinstate a suspended vendor with no other OPEN case, firing resume cascade
            if vendor["status"] == "SUSPENDED" and svc.open_case_for_vendor(vendor["id"]) is None:
                vendor["status"] = "ACTIVE"
                svc.resume_cascade(vendor["id"])
                db.touch(vendor)
                svc.audit_status_change("Vendor", vendor["id"], "SUSPENDED", "ACTIVE", ctx)
        else:  # CONFIRMED_HIT -> ordered block cascade
            if vendor["status"] == "SUSPENDED":
                svc.block_cascade(vendor, ctx)
    return ok(case)
