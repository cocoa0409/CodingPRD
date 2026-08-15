"""Remittance endpoints (PRD 3.6)."""

from flask import Blueprint

import clock
import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import new_entity, touch, get_report_or_404, get_remittance_or_404

bp = Blueprint("remittances", __name__)


def remittance_view(r):
    return {
        "id": r["id"],
        "report_id": r["report_id"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
        "failure_reason": r["failure_reason"],
        "confirmed_date": r["confirmed_date"].isoformat() if r["confirmed_date"] else None,
        "variance_cents": r["variance_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.post("/escheatment/holder-reports/<reportId>/remittances")
def create_remittance(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("TreasuryOps",))
    data = mw.body_json()
    amount = mw.req_int(data, "amount_cents", min_value=0)
    report = get_report_or_404(reportId)
    if report["status"] != "ACCEPTED":
        raise_error(
            errors.ERR_REPORT_NOT_ACCEPTED,
            "Remittance creation requires an ACCEPTED report",
        )
    for existing in db.remittances.values():
        if existing["report_id"] == report["id"] and existing["status"] == "PENDING":
            raise_error(
                errors.ERR_REMITTANCE_ALREADY_PENDING,
                "A PENDING remittance already exists for this report",
            )
    # Deliberately no all-final or variance check at creation (PRD 3.6).
    rem = new_entity({
        "report_id": report["id"],
        "amount_cents": amount,
        "status": "PENDING",
        "failure_reason": None,
        "confirmed_date": None,
        "variance_cents": None,
    })
    db.remittances[rem["id"]] = rem
    return resp.success(remittance_view(rem), "object", 201)


@bp.get("/escheatment/holder-reports/<reportId>/remittances")
def list_remittances(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    report = get_report_or_404(reportId)
    limit, offset = mw.pagination_params()
    items = [r for r in db.remittances.values() if r["report_id"] == report["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([remittance_view(r) for r in page], "array", 200, pagination=meta)


@bp.get("/escheatment/remittances/<remittanceId>")
def get_remittance(remittanceId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    rem = get_remittance_or_404(remittanceId)
    return resp.success(remittance_view(rem), "object", 200)


@bp.post("/escheatment/remittances/<remittanceId>/confirm")
def confirm_remittance(remittanceId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    mw.body_json(required=False)
    rem = get_remittance_or_404(remittanceId)
    if rem["status"] != "PENDING":
        raise_error(
            errors.ERR_REMITTANCE_NOT_PENDING,
            "Confirm requires the remittance to be PENDING",
        )
    report = get_report_or_404(rem["report_id"])
    lines = [l for l in db.line_items.values()
             if l["report_id"] == report["id"] and l["status"] != "REMOVED"]
    if any(l["status"] != "FINAL" for l in lines):
        raise_error(
            errors.ERR_LINES_NOT_FINAL,
            "Every non-REMOVED line of the report must be FINAL",
        )
    variance = rem["amount_cents"] - report["total_final_cents"]
    rem["variance_cents"] = variance
    if variance != 0:
        raise_error(
            errors.ERR_REMITTANCE_VARIANCE_NONZERO,
            "Confirm requires amount_cents - report.total_final_cents == 0 exactly",
        )
    rem["status"] = "CONFIRMED"
    rem["confirmed_date"] = clock.today()
    touch(rem)
    # Cascade hop 2: report accumulates confirmed remittance, version bumps.
    report["confirmed_remittance_cents"] += rem["amount_cents"]
    touch(report)
    # Cascade hop 3: every lined property REPORTED -> REMITTED.
    for line in lines:
        prop = db.properties.get(line["property_id"])
        if prop is not None and prop["status"] == "REPORTED":
            prop["status"] = "REMITTED"
            touch(prop)
    return resp.success(remittance_view(rem), "object", 200)


@bp.post("/escheatment/remittances/<remittanceId>/fail")
def fail_remittance(remittanceId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    data = mw.body_json()
    reason = mw.req_string(data, "failure_reason")
    rem = get_remittance_or_404(remittanceId)
    if rem["status"] != "PENDING":
        raise_error(
            errors.ERR_REMITTANCE_NOT_PENDING,
            "Fail requires the remittance to be PENDING",
        )
    rem["status"] = "FAILED"
    rem["failure_reason"] = reason
    touch(rem)
    return resp.success(remittance_view(rem), "object", 200)


@bp.post("/escheatment/remittances/<remittanceId>/requeue")
def requeue_remittance(remittanceId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("TreasuryOps",))
    data = mw.body_json()
    amount = mw.req_int(data, "amount_cents", min_value=0)
    rem = get_remittance_or_404(remittanceId)
    if rem["status"] != "FAILED":
        raise_error(
            errors.ERR_REMITTANCE_NOT_FAILED,
            "Requeue requires the remittance to be FAILED",
        )
    rem["status"] = "PENDING"
    rem["amount_cents"] = amount
    rem["failure_reason"] = None
    # variance_cents is recomputed lazily at the next confirmation.
    rem["variance_cents"] = None
    touch(rem)
    return resp.success(remittance_view(rem), "object", 200)
