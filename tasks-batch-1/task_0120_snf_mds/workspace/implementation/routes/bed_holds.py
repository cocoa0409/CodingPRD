"""BedHold endpoints: open, fetch, list, close (PRD §3.6)."""
from flask import request

import db
import errors
import response
import serialize
import validation as V
from clock import parse_iso, to_utc_date
from gate import gate
from services import calc, lookups, transitions


LEAVE_REASONS = {"HOSPITAL", "THERAPEUTIC", "OTHER"}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; touching endpoints are NOT an overlap
    (PRD §3.6)."""
    return a_start < b_end and b_start < a_end


def register(app):
    @app.route("/snf/admissions/<aid>/bed-holds", methods=["POST"])
    def open_bed_hold(aid):
        gate(["AdmissionsCoordinator"])
        adm = lookups.get_admission(aid)
        body = V.get_body()
        leave_reason = V.as_enum(V.require(body, "leave_reason"), "leave_reason", LEAVE_REASONS)
        leave_start_at = V.require(body, "leave_start_at")
        expected_return_at = V.require(body, "expected_return_at")
        start_dt = V.as_datetime(leave_start_at, "leave_start_at")
        end_dt = V.as_datetime(expected_return_at, "expected_return_at")
        if not (end_dt > start_dt):
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "expected_return_at must be strictly after leave_start_at")
        # State / capacity: admission ACTIVE and no other OPEN hold (priority 18).
        existing = lookups.bed_holds_for_admission(aid)
        if adm["status"] != "ACTIVE" or any(b["status"] == "OPEN" for b in existing):
            raise errors.err(errors.ERR_BEDHOLD_ALREADY_OPEN,
                             "admission not ACTIVE or a bed-hold is already OPEN")
        # Temporal overlap with any existing bed-hold window (priority 10).
        for b in existing:
            b_start = parse_iso(b["leave_start_at"])
            b_end_iso = b.get("actual_return_at") or b["expected_return_at"]
            b_end = parse_iso(b_end_iso)
            if _intervals_overlap(start_dt, end_dt, b_start, b_end):
                raise errors.err(errors.ERR_BEDHOLD_OVERLAP,
                                 "leave window overlaps an existing bed-hold")
        leave_days, paid = calc.bed_hold_days(
            leave_start_at, expected_return_at, adm["payer_source"])
        obj = {
            "admission_id": aid,
            "leave_reason": leave_reason,
            "leave_start_at": leave_start_at,
            "expected_return_at": expected_return_at,
            "actual_return_at": None,
            "leave_day_count": leave_days,
            "paid_day_count": paid,
            "status": "OPEN",
        }
        db.stamp_create(obj)
        db.bed_holds[obj["id"]] = obj
        # Resident ADMITTED -> ON_LEAVE; census unchanged (bed still held).
        res = db.residents.get(adm["resident_id"])
        if res is not None:
            res["status"] = "ON_LEAVE"
            db.touch(res)
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/admissions/<aid>/bed-holds", methods=["GET"])
    def list_bed_holds(aid):
        gate(["AdmissionsCoordinator", "BillingAnalyst"])
        lookups.get_admission(aid)
        limit, offset = V.pagination(request.args)
        rows = lookups.bed_holds_for_admission(aid)
        status = request.args.get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    @app.route("/snf/bed-holds/<bid>", methods=["GET"])
    def get_bed_hold(bid):
        gate(["AdmissionsCoordinator", "BillingAnalyst"])
        obj = lookups.get_bed_hold(bid)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/bed-holds/<bid>/close", methods=["POST"])
    def close_bed_hold(bid):
        gate(["AdmissionsCoordinator"])
        bh = lookups.get_bed_hold(bid)
        body = V.get_body()
        return_outcome = V.as_enum(V.require(body, "return_outcome"), "return_outcome",
                                   {"RETURNED", "DID_NOT_RETURN"})
        actual_return_at = V.opt(body, "actual_return_at", None)
        if actual_return_at is not None:
            V.as_datetime(actual_return_at, "actual_return_at")
        transitions.close_bed_hold(bh, return_outcome, actual_return_at)
        return response.success(serialize.public(bh), 200)
