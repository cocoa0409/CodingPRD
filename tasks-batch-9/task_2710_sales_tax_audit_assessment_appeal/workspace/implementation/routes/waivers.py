"""StatuteWaiver endpoints (PRD 3.2)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import bad, body, guard, req_date, req_id, req_str
from routes.common import body_fk, one, path_get, require_owner
from services import derive

bp = Blueprint("waivers", __name__)

VOIDABLE_AUDIT_STATUSES = ("SCOPED", "FIELDWORK", "REVIEW_COMPLETE")


def _running_expiry(audit):
    base, days_added, _tolled, _expiry = derive.statute_replay(audit, write=False)
    if base is None:
        return None
    return db.add_days(base, days_added)


@bp.post("/statute-waivers")
@guard("AuditSupervisor", "FieldAuditor")
def create_waiver():
    data = body()
    audit_id = req_id(data, "audit_id")
    covers_period_end = req_date(data, "covers_period_end")
    extended_to_date = req_date(data, "extended_to_date")
    signed_by_name = req_str(data, "signed_by_name", 1, None)

    audit = body_fk("audits", audit_id)
    if audit["status"] in ("CLOSED", "ABANDONED") or audit.get("scope_period_end") is None:
        raise ApiError("ERR_INVALID_STATE")
    if db.format_date(covers_period_end) != audit["scope_period_end"]:
        bad("covers_period_end must equal the audit's scope_period_end.")

    for existing in derive.waivers_of_audit(audit["id"]):
        if existing["status"] == "DRAFTED":
            raise ApiError("ERR_WAIVER_ALREADY_PENDING")

    # PRD 3.2: "the `extended_to_date` being requested, which must fall strictly
    # after the audit's current `statute_expiry_date`". PRD 2.8 tier 12 lists
    # POST /statute-waivers with ERR_WAIVER_NOT_EXTENDING (422).
    current_expiry = db.parse_date(derive.refresh_audit(audit)["statute_expiry_date"])
    if current_expiry is not None and extended_to_date <= current_expiry:
        raise ApiError("ERR_WAIVER_NOT_EXTENDING")

    rec = db.new_record(
        {
            "audit_id": audit["id"],
            "status": "DRAFTED",
            "covers_period_end": db.format_date(covers_period_end),
            "extended_to_date": db.format_date(extended_to_date),
            "prior_expiry_date": None,
            "days_added": 0,
            "signed_by_name": signed_by_name,
            "signed_date": None,
            "void_reason": None,
        }
    )
    db.insert("statute_waivers", rec)
    return one("statute_waivers", rec, 201)


@bp.get("/statute-waivers/<wid>")
@guard("AuditSupervisor", "FieldAuditor", "Taxpayer")
def read_waiver(wid):
    return one("statute_waivers", path_get("statute_waivers", wid))


@bp.post("/statute-waivers/<wid>/execute")
@guard("Taxpayer")
def execute_waiver(wid):
    waiver = path_get("statute_waivers", wid)
    audit = db.get("audits", waiver["audit_id"])
    require_owner(audit["taxpayer_id"] if audit else None)

    data = body()
    signed_date = req_date(data, "signed_date")
    if signed_date != db.clock_date():
        bad("signed_date must equal the current logical clock date.")

    if waiver["status"] != "DRAFTED":
        raise ApiError("ERR_INVALID_STATE")
    if audit is None or audit["status"] not in VOIDABLE_AUDIT_STATUSES:
        raise ApiError("ERR_INVALID_STATE")
    if derive.audit_statute_status(audit) == "EXPIRED":
        raise ApiError("ERR_STATUTE_EXPIRED")

    running = _running_expiry(audit)
    extended = db.parse_date(waiver["extended_to_date"])
    if running is None or extended is None or extended <= running:
        raise ApiError("ERR_WAIVER_NOT_EXTENDING")

    waiver["status"] = "EXECUTED"
    waiver["signed_date"] = db.format_date(signed_date)
    derive.rewrite_statute(audit)
    db.touch(waiver)
    db.touch(audit)
    return one("statute_waivers", waiver)


@bp.post("/statute-waivers/<wid>/void")
@guard("AuditSupervisor")
def void_waiver(wid):
    waiver = path_get("statute_waivers", wid)
    data = body()
    reason = req_str(data, "void_reason", 1, None)

    if waiver["status"] not in ("DRAFTED", "EXECUTED"):
        raise ApiError("ERR_INVALID_STATE")
    audit = db.get("audits", waiver["audit_id"])
    was_executed = waiver["status"] == "EXECUTED"
    if was_executed:
        if audit is None or audit["status"] not in VOIDABLE_AUDIT_STATUSES:
            raise ApiError("ERR_INVALID_STATE")
        # a void that would leave the audit already lapsed is refused
        previous_status = waiver["status"]
        previous_days = waiver["days_added"]
        waiver["status"] = "VOIDED"
        waiver["days_added"] = 0
        if derive.audit_statute_status(audit) == "EXPIRED":
            waiver["status"] = previous_status
            waiver["days_added"] = previous_days
            raise ApiError("ERR_STATUTE_EXPIRED")
    else:
        waiver["status"] = "VOIDED"
        waiver["days_added"] = 0

    waiver["void_reason"] = reason
    db.touch(waiver)
    if was_executed and audit is not None:
        derive.rewrite_statute(audit)
        db.touch(audit)
    return one("statute_waivers", waiver)
