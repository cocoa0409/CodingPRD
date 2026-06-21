"""TimeEntry endpoints: post, fetch, list, void.

Validation order (PRD §2.11): cross-employer FK integrity (priority 4) precedes
body well-formedness (priority 5), which precedes the temporal window check
(priority 14) and the shift-overlap/rest-buffer check (priority 14.5).
"""
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import object_response, array_response
from services import domain, serialize, validate
from services.money import round_half_up
from timeutil import parse_iso8601

bp = Blueprint("time_entries", __name__)

MIN_REST_GAP_MINUTES = 30


@bp.route("/time-entries", methods=["POST"])
def create_time_entry():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    body = validate.get_body()

    # FK fields must be present (string) before the cross-employer check; absence is
    # a 400 (priority 5 well-formedness), but the resolution/cross-employer outcome
    # is priority 4.
    pay_period_id = validate.require_str(body, "pay_period_id")
    worker_id = validate.require_str(body, "worker_id")

    period = db.pay_periods.get(pay_period_id)
    worker = db.workers.get(worker_id)
    # Cross-employer / referential integrity (priority 4).
    if period is None or worker is None:
        raise errors.cross_employer("Body foreign key does not resolve")
    if period["employer_id"] != worker["employer_id"]:
        raise errors.cross_employer("worker and pay_period belong to different employers")

    # Body well-formedness (priority 5).
    shift_start = validate.require_datetime(body, "shift_start_at")
    shift_end = validate.require_datetime(body, "shift_end_at")
    hours = validate.require_number(body, "hours_worked")
    if not (0 < hours <= 24):
        raise errors.invalid_request("hours_worked must be in (0, 24]")

    # Temporal window check (priority 14): ERR_TIME_ENTRY_OUT_OF_WINDOW.
    period_start = parse_iso8601(period["start_at"])
    period_end = parse_iso8601(period["end_at"])
    window_ok = True
    if period["status"] != "OPEN":
        window_ok = False
    elif not (shift_end > shift_start):
        window_ok = False
    elif not (period_start <= shift_start < period_end):
        window_ok = False
    elif not (period_start <= shift_end < period_end):
        # shift_end is inclusive and must fall within the period (PRD §3.3).
        window_ok = False
    else:
        span_hours = (shift_end - shift_start).total_seconds() / 3600.0
        if abs(span_hours - float(hours)) > 0.01:
            window_ok = False
    if not window_ok:
        raise errors.ApiError(errors.ERR_TIME_ENTRY_OUT_OF_WINDOW, 422,
                              "Time entry outside the period window or inconsistent")

    # Shift overlap / rest-buffer check (priority 14.5): closed intervals separated
    # by >= 30 minutes from any POSTED entry of the same worker.
    gap = Decimal(MIN_REST_GAP_MINUTES) * Decimal(60)  # seconds
    for te in db.time_entries.values():
        if te["worker_id"] != worker_id or te["status"] != "POSTED":
            continue
        other_start = parse_iso8601(te["shift_start_at"])
        other_end = parse_iso8601(te["shift_end_at"])
        # Closed-interval overlap: new_start <= other_end and other_start <= new_end.
        if shift_start <= other_end and other_start <= shift_end:
            raise errors.ApiError(errors.ERR_SHIFT_OVERLAP, 409, "Shift overlaps an existing shift")
        # Rest buffer: gap between closed intervals must be >= 30 minutes.
        if shift_start > other_end:
            gap_secs = (shift_start - other_end).total_seconds()
        else:
            gap_secs = (other_start - shift_end).total_seconds()
        if gap_secs < float(gap):
            raise errors.ApiError(errors.ERR_SHIFT_OVERLAP, 409, "Shift within rest buffer")

    gross_earned = round_half_up(Decimal(str(hours)) * Decimal(worker["hourly_rate_cents"]))
    ledger = db.new_ledger_fields()
    entry = {
        **ledger,
        "pay_period_id": pay_period_id,
        "worker_id": worker_id,
        "shift_start_at": body["shift_start_at"],
        "shift_end_at": body["shift_end_at"],
        "hours_worked": hours,
        "gross_earned_cents": gross_earned,
        "status": "POSTED",
    }
    db.time_entries[entry["id"]] = entry

    # Recompute period gross + worker available earnings (PRD §3.3).
    period["gross_accrued_cents"] = domain.gross_accrued_for_period(period)
    db.touch(period)
    db.touch(worker)  # net_available_earnings recomputed at read; bump version on change of inputs

    return object_response(serialize.time_entry(entry), status=201)


@bp.route("/time-entries/<time_entry_id>", methods=["GET"])
def get_time_entry(time_entry_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    entry = db.time_entries.get(time_entry_id)
    if entry is None:
        raise errors.not_found()
    return object_response(serialize.time_entry(entry))


@bp.route("/time-entries", methods=["GET"])
def list_time_entries():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    limit, offset = validate.pagination()
    pp_filter = request.args.get("pay_period_id")
    w_filter = request.args.get("worker_id")
    items = []
    for te in db.time_entries.values():
        if pp_filter is not None and te["pay_period_id"] != pp_filter:
            continue
        if w_filter is not None and te["worker_id"] != w_filter:
            continue
        items.append(te)
    page, total = validate.paginate(items, limit, offset)
    return array_response([serialize.time_entry(te) for te in page], limit, offset, total)


@bp.route("/time-entries/<time_entry_id>/void", methods=["POST"])
def void_time_entry(time_entry_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    entry = db.time_entries.get(time_entry_id)
    if entry is None:
        raise errors.not_found()
    if entry["status"] != "POSTED":
        raise errors.invalid_state()
    entry["status"] = "VOIDED"
    # Recompute affected period and worker earnings (PRD §3.3).
    period = db.pay_periods.get(entry["pay_period_id"])
    if period is not None:
        period["gross_accrued_cents"] = domain.gross_accrued_for_period(period)
        db.touch(period)
    worker = db.workers.get(entry["worker_id"])
    if worker is not None:
        db.touch(worker)
    return object_response(serialize.time_entry(entry))
