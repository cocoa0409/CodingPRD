"""Warranty adjudication, reimbursement and part shipment (PRD 3.9)."""
from flask import Blueprint

import errors
import lookups
import validators as v
from db import db, new_id, public, public_list, stamp_new, touch
from middleware import actor, endpoint, is_dealer
from response import created, listing, ok
from services import calc, rollups

bp = Blueprint("claims", __name__)

COMPLAINT_CODES = ("AXLE", "BRAKE", "LIGHTING", "FRAME", "FLOORING", "COUPLER")
CLAIM_STATUSES = ("SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED", "PARTS_SHIPPED",
                  "CLOSED")
DECISIONS = ("APPROVE", "DENY", "REQUEST_INFO")
INFO_REQUEST_MAX = 2
READ_ROLES = ["SalesAdmin", "PlantEngineer", "Dealer"]


def _part_lines(data, field="part_lines"):
    raw = data.get(field)
    if raw is None:
        raise errors.invalid("%s is required" % field)
    if not isinstance(raw, list):
        raise errors.invalid("%s must be an array" % field)
    lines = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise errors.invalid("%s[%d] must be an object" % (field, index))
        quantity = v.req_int(entry, "quantity", minimum=1)
        unit_cost = v.req_int(entry, "unit_cost_cents", minimum=0)
        line = {"quantity": quantity, "unit_cost_cents": unit_cost}
        if v.present(entry, "part_number"):
            line["part_number"] = v.req_str(entry, "part_number", max_len=64)
        lines.append(line)
    return lines


def _guard_labor_and_window(complaint_code, labor_hours, unit, failure_dt):
    ceiling = calc.flat_rate_ceiling(complaint_code)
    if calc.dec(labor_hours) > ceiling:
        raise errors.ApiError("ERR_LABOR_HOURS_EXCEED_FLAT_RATE", 422,
                              "%s hours exceeds the flat-rate ceiling of %s for %s"
                              % (labor_hours, ceiling, complaint_code))
    start = unit.get("_warranty_start_dt")
    if start is not None:
        if calc.days_past_expiry(start, failure_dt) > calc.WARRANTY_GRACE_DAYS:
            raise errors.ApiError("ERR_WARRANTY_WINDOW_EXPIRED", 422,
                                  "The failure date falls more than %s days past warranty expiry"
                                  % calc.WARRANTY_GRACE_DAYS)


@bp.route("/warranty-claims", methods=["POST"])
@endpoint(["Dealer", "SalesAdmin"])
def file_claim():
    data = v.body()
    if is_dealer() and data.get("dealer_id") != actor():
        raise errors.dealer_scope(actor(), data.get("dealer_id"))
    unit = lookups.unit_or_404(v.req_id(data, "unit_id"))
    dealer = lookups.dealer_or_404(v.req_id(data, "dealer_id"))
    claim_ref = v.req_str(data, "claim_ref", min_len=4, max_len=24)
    complaint_code = v.req_enum(data, "complaint_code", COMPLAINT_CODES)
    labor_hours = v.req_num(data, "labor_hours", minimum=0.1)
    part_lines = _part_lines(data)
    failure_raw, failure_dt = v.req_dt(data, "failure_date")

    lookups.unique_or_409(db.claims, "claim_ref", claim_ref)
    ceiling = calc.flat_rate_ceiling(complaint_code)
    if calc.dec(labor_hours) > ceiling:
        raise errors.ApiError("ERR_LABOR_HOURS_EXCEED_FLAT_RATE", 422,
                              "%s hours exceeds the flat-rate ceiling of %s for %s"
                              % (labor_hours, ceiling, complaint_code))
    if unit["build_status"] != "SHIPPED" or unit.get("warranty_start_date") is None:
        raise errors.ApiError("ERR_UNIT_NOT_DELIVERED", 409,
                              "Trailer %s has not been delivered" % unit["id"])
    if calc.days_past_expiry(unit["_warranty_start_dt"], failure_dt) > calc.WARRANTY_GRACE_DAYS:
        raise errors.ApiError("ERR_WARRANTY_WINDOW_EXPIRED", 422,
                              "The failure date falls more than %s days past warranty expiry"
                              % calc.WARRANTY_GRACE_DAYS)

    row = {
        "id": new_id(),
        "claim_ref": claim_ref,
        "unit_id": unit["id"],
        "dealer_id": dealer["id"],
        "complaint_code": complaint_code,
        "labor_hours": calc.num(calc.dec(labor_hours)),
        "part_lines": part_lines,
        "part_line_count": len(part_lines),
        "failure_date": failure_raw,
        "status": "SUBMITTED",
        "info_request_round": 0,
        "coverage_variant": None,
        "coverage_factor": None,
        "labor_cents": None,
        "parts_subtotal_cents": None,
        "freight_cents": None,
        "reimbursement_total_cents": None,
        "shipped_line_count": 0,
        "tracking_number": None,
        "reviewed_by_user_id": None,
        "denial_reason": None,
        "_failure_dt": failure_dt,
    }
    stamp_new(row)
    db.claims[row["id"]] = row
    return created(public(row))


def _close_and_credit(claim):
    claim["status"] = "CLOSED"
    touch(claim)
    rollups.recompute_dealer(db.dealers.get(claim["dealer_id"]))


@bp.route("/warranty-claims/<claim_id>/review", methods=["POST"])
@endpoint(["SalesAdmin"])
def review_claim(claim_id):
    claim = lookups.claim_or_404(claim_id)
    data = v.body()
    decision = v.req_enum(data, "decision", DECISIONS)
    note = v.opt_str(data, "review_note", max_len=1000)

    if claim["status"] != "SUBMITTED":
        raise errors.ApiError("ERR_CLAIM_STATE_INVALID", 409,
                              "A claim in status %s may not be reviewed" % claim["status"])

    claim["reviewed_by_user_id"] = actor()
    if note is not None:
        claim["review_note"] = note

    if decision == "REQUEST_INFO":
        if claim["info_request_round"] >= INFO_REQUEST_MAX:
            claim["info_request_round"] = INFO_REQUEST_MAX + 1
            claim["status"] = "DENIED"
            claim["denial_reason"] = "INFO_REQUEST_LIMIT_REACHED"
        else:
            claim["info_request_round"] += 1
            claim["status"] = "INFO_REQUESTED"
        touch(claim)
        return ok(public(claim))

    if decision == "DENY":
        claim["status"] = "DENIED"
        claim["denial_reason"] = "REVIEWER_DENIED"
        touch(claim)
        return ok(public(claim))

    unit = db.units.get(claim["unit_id"])
    dealer = db.dealers.get(claim["dealer_id"])
    figures = calc.reimbursement(claim["part_lines"], claim["labor_hours"],
                                dealer["labor_rate_cents_per_hour"],
                                unit["_warranty_start_dt"], claim["_failure_dt"])
    if figures is None:
        raise errors.ApiError("ERR_WARRANTY_WINDOW_EXPIRED", 422,
                              "The failure date falls beyond every goodwill band")
    claim.update(figures)
    claim["status"] = "APPROVED"
    touch(claim)
    if claim["part_line_count"] == 0:
        _close_and_credit(claim)
    return ok(public(claim))


@bp.route("/warranty-claims/<claim_id>/resubmission", methods=["POST"])
@endpoint(["Dealer"])
def resubmit_claim(claim_id):
    claim = lookups.claim_or_404(claim_id)
    if is_dealer() and claim["dealer_id"] != actor():
        raise errors.dealer_scope(actor(), claim["dealer_id"])
    data = v.body()
    note = v.opt_str(data, "response_note", max_len=1000)
    labor_hours = None
    if v.present(data, "labor_hours"):
        labor_hours = v.req_num(data, "labor_hours", minimum=0.1)
    part_lines = None
    if v.present(data, "part_lines"):
        part_lines = _part_lines(data)

    if claim["status"] != "INFO_REQUESTED":
        raise errors.ApiError("ERR_CLAIM_STATE_INVALID", 409,
                              "A claim in status %s may not be resubmitted" % claim["status"])

    unit = db.units.get(claim["unit_id"])
    effective_hours = claim["labor_hours"] if labor_hours is None else labor_hours
    _guard_labor_and_window(claim["complaint_code"], effective_hours, unit,
                            claim["_failure_dt"])

    if labor_hours is not None:
        claim["labor_hours"] = calc.num(calc.dec(labor_hours))
    if part_lines is not None:
        claim["part_lines"] = part_lines
        claim["part_line_count"] = len(part_lines)
    if note is not None:
        claim["response_note"] = note
    claim["status"] = "SUBMITTED"
    touch(claim)
    return ok(public(claim))


@bp.route("/warranty-claims/<claim_id>/part-shipment", methods=["POST"])
@endpoint(["SalesAdmin"])
def ship_parts(claim_id):
    claim = lookups.claim_or_404(claim_id)
    data = v.body()
    tracking_number = v.req_str(data, "tracking_number", min_len=1, max_len=64)
    line_count = v.opt_int(data, "line_count", 1, 1)

    if claim["status"] not in ("APPROVED", "PARTS_SHIPPED") or claim["part_line_count"] == 0:
        raise errors.ApiError("ERR_CLAIM_STATE_INVALID", 409,
                              "A claim in status %s may not ship parts" % claim["status"])
    if claim["shipped_line_count"] + line_count > claim["part_line_count"]:
        raise errors.ApiError("ERR_CLAIM_STATE_INVALID", 409,
                              "Shipping %s more line(s) would exceed the claim's %s part line(s)"
                              % (line_count, claim["part_line_count"]))

    claim["shipped_line_count"] += line_count
    claim["tracking_number"] = tracking_number
    if claim["shipped_line_count"] >= claim["part_line_count"]:
        claim["status"] = "CLOSED"
        touch(claim)
        rollups.recompute_dealer(db.dealers.get(claim["dealer_id"]))
    else:
        claim["status"] = "PARTS_SHIPPED"
        touch(claim)
    return ok(public(claim))


@bp.route("/warranty-claims/<claim_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_claim(claim_id):
    return ok(public(lookups.claim_or_404(claim_id)))


@bp.route("/warranty-claims", methods=["GET"])
@endpoint(READ_ROLES)
def list_claims():
    dealer_id = v.request_arg("dealer_id")
    if is_dealer() and dealer_id != actor():
        raise errors.dealer_scope(actor(), dealer_id)
    unit_id = v.request_arg("unit_id")
    status = v.query_enum("status", CLAIM_STATUSES)
    limit, offset = v.pagination()
    rows = list(db.claims.values())
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if unit_id is not None:
        rows = [r for r in rows if r["unit_id"] == unit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return listing(public_list(rows[offset:offset + limit]), limit, offset, total)
