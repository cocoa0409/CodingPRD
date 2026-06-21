"""TheftReport routes (PRD §3.1): file proactive report, clear report."""
from flask import Blueprint

import errors
import response
import serializers
from db import db, stamp_create, touch
from helpers import (as_string, get_json_body, parse_pagination, paginate,
                     query_arg, require_fields)
from middleware import authenticate, require_roles

bp = Blueprint("theft_reports", __name__)

REPORT_STATUSES = {"OPEN", "CLEARED"}
READ_ROLES = {"ComplianceOfficer", "WeighMaster", "YardManager"}


@bp.route("/yard/theft-reports", methods=["POST"])
def create_theft_report():
    _uid, role = authenticate()
    require_roles(role, {"ComplianceOfficer"})
    body = get_json_body()
    require_fields(body, ["seller_id", "reason"])
    seller_id = as_string(body["seller_id"], "seller_id")
    reason = as_string(body["reason"], "reason")
    ticket_id = body.get("ticket_id")
    if ticket_id is not None and not isinstance(ticket_id, str):
        raise errors.invalid_request("ticket_id must be a string or null.")
    # Existence (priority 3): seller and ticket (if provided).
    seller = db.sellers.get(seller_id)
    if seller is None:
        raise errors.not_found("Seller not found.")
    if ticket_id is not None and ticket_id not in db.tickets:
        raise errors.not_found("Ticket not found.")

    record = {
        "seller_id": seller_id,
        "ticket_id": ticket_id,
        "reason": reason,
        "status": "OPEN",
    }
    stamp_create(record)
    db.theft_reports[record["id"]] = record
    # Cross-entity: flag seller, bump open count.
    seller["status"] = "FLAGGED"
    seller["open_theft_reports"] += 1
    touch(seller)
    return response.success(serializers.theft_report(record), 201)


@bp.route("/yard/theft-reports/<rid>", methods=["GET"])
def get_theft_report(rid):
    authenticate()
    record = db.theft_reports.get(rid)
    if not record:
        raise errors.not_found("Theft report not found.")
    return response.success(serializers.theft_report(record), 200)


@bp.route("/yard/theft-reports", methods=["GET"])
def list_theft_reports():
    authenticate()
    limit, offset = parse_pagination()
    seller_id = query_arg("seller_id")
    ticket_id = query_arg("ticket_id")
    status = query_arg("status")
    if status is not None and status not in REPORT_STATUSES:
        raise errors.invalid_request("status filter is invalid.")
    rows = list(db.theft_reports.values())
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if ticket_id is not None:
        rows = [r for r in rows if r.get("ticket_id") == ticket_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.theft_report(r) for r in page], limit, offset, total)


@bp.route("/yard/theft-reports/<rid>/clear", methods=["POST"])
def clear_theft_report(rid):
    _uid, role = authenticate()
    require_roles(role, {"ComplianceOfficer"})
    record = db.theft_reports.get(rid)
    if not record:
        raise errors.not_found("Theft report not found.")
    if record["status"] != "OPEN":
        raise errors.invalid_state("Theft report is not OPEN.")
    record["status"] = "CLEARED"
    touch(record)
    # Cross-entity: decrement open count; unfreeze if 0 and not BANNED.
    seller = db.sellers.get(record["seller_id"])
    if seller is not None:
        seller["open_theft_reports"] = max(0, seller["open_theft_reports"] - 1)
        if seller["open_theft_reports"] == 0 and seller["status"] != "BANNED":
            seller["status"] = "ACTIVE"
        touch(seller)
    return response.success(serializers.theft_report(record), 200)
