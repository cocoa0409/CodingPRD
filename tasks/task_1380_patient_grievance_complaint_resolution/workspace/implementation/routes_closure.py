"""Routes: satisfaction follow-ups, clock suspensions, trend snapshots."""

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import cascades
import db
import derived
import errors
import middleware
from clock import iso_ms, parse_iso
from helpers import (
    SUSPENSION_REASONS,
    check_bool,
    check_enum,
    get_body,
    paginate,
    parse_pagination,
    require_present,
    serialize_followup,
    serialize_snapshot,
    serialize_suspension,
    sorted_by_creation,
    stamp_new,
    touch,
)
from response import success_list, success_object
from routes_cases import get_case_or_404
from state import CLOCK

bp = Blueprint("closure", __name__)

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------------------
# SatisfactionFollowUp
# ---------------------------------------------------------------------------


@bp.route("/api/follow-ups", methods=["GET"])
def list_followups():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    followups = list(db.follow_ups.values())
    if case_id is not None:
        followups = [f for f in followups if f["case_id"] == case_id]
    if status is not None:
        followups = [f for f in followups if derived.followup_status(f) == status]
    followups = sorted_by_creation(followups)
    page, total = paginate(followups, limit, offset)
    return success_list([serialize_followup(f) for f in page], limit, offset, total)


@bp.route("/api/follow-ups/<followup_id>", methods=["GET"])
def get_followup(followup_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    followup = db.follow_ups.get(followup_id)
    if followup is None:
        raise errors.not_found(
            errors.ERR_FOLLOWUP_NOT_FOUND, "SatisfactionFollowUp not found"
        )
    return success_object(serialize_followup(followup))


@bp.route("/api/follow-ups/<followup_id>/respond", methods=["POST"])
def respond_followup(followup_id):
    middleware.authenticate()
    middleware.require_roles("PatientAdvocate")
    body = get_body()
    require_present(body, "score")
    followup = db.follow_ups.get(followup_id)
    if followup is None:
        raise errors.not_found(
            errors.ERR_FOLLOWUP_NOT_FOUND, "SatisfactionFollowUp not found"
        )
    now = CLOCK.now()
    # Child state (rung 7): still PENDING and the clock not past expires_at.
    if followup["status"] != "PENDING" or now > derived.followup_expires_at(followup):
        raise errors.api_error(
            errors.ERR_FOLLOWUP_INVALID_STATE,
            409,
            "Follow-up is not PENDING or has expired",
        )
    score = body.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or score < 1 or score > 5:
        raise errors.api_error(
            errors.ERR_FOLLOWUP_SCORE_INVALID, 422, "score must be an integer in 1..5"
        )
    followup["score"] = score
    followup["responded_at"] = iso_ms(now)
    followup["status"] = "RESPONDED"
    touch(followup)
    # A score of two or lower is a failed resolution and fires the reopen
    # cascade on the case.
    if score <= 2:
        case = db.patient_cases.get(followup["case_id"])
        if case is not None and case["lifecycle_status"] == "CLOSED":
            cascades.reopen_case(case, now)
    return success_object(serialize_followup(followup))


# ---------------------------------------------------------------------------
# ClockSuspension
# ---------------------------------------------------------------------------


@bp.route("/api/patient-cases/<case_id>/clock-suspensions", methods=["POST"])
def create_suspension(case_id):
    middleware.authenticate()
    middleware.require_roles("IntakeCoordinator")
    body = get_body()
    require_present(body, "reason")
    case = get_case_or_404(case_id)
    if case["lifecycle_status"] in ("CLOSED", "WITHDRAWN"):
        raise errors.api_error(
            errors.ERR_CASE_INVALID_STATE,
            409,
            "Cannot suspend the clock of a CLOSED or WITHDRAWN case",
        )
    if derived.has_open_suspension(case["id"]):
        raise errors.api_error(
            errors.ERR_DUPLICATE_OPEN_SUSPENSION,
            409,
            "Case already has an OPEN ClockSuspension",
        )
    reason = check_enum(body, "reason", SUSPENSION_REASONS, required=True)
    suspension = stamp_new()
    suspension.update(
        {
            "case_id": case["id"],
            "reason": reason,
            "status": "OPEN",
            "started_at": CLOCK.now_iso(),
            "closed_at": None,
            "credited_seconds": 0,
        }
    )
    db.clock_suspensions[suspension["id"]] = suspension
    return success_object(serialize_suspension(suspension), 201)


@bp.route("/api/clock-suspensions", methods=["GET"])
def list_suspensions():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    suspensions = list(db.clock_suspensions.values())
    if case_id is not None:
        suspensions = [s for s in suspensions if s["case_id"] == case_id]
    if status is not None:
        suspensions = [s for s in suspensions if s["status"] == status]
    suspensions = sorted_by_creation(suspensions)
    page, total = paginate(suspensions, limit, offset)
    return success_list([serialize_suspension(s) for s in page], limit, offset, total)


@bp.route("/api/clock-suspensions/<suspension_id>", methods=["GET"])
def get_suspension(suspension_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    suspension = db.clock_suspensions.get(suspension_id)
    if suspension is None:
        raise errors.not_found(
            errors.ERR_SUSPENSION_NOT_FOUND, "ClockSuspension not found"
        )
    return success_object(serialize_suspension(suspension))


@bp.route("/api/clock-suspensions/<suspension_id>/close", methods=["POST"])
def close_suspension(suspension_id):
    middleware.authenticate()
    middleware.require_roles("IntakeCoordinator")
    get_body()
    suspension = db.clock_suspensions.get(suspension_id)
    if suspension is None:
        raise errors.not_found(
            errors.ERR_SUSPENSION_NOT_FOUND, "ClockSuspension not found"
        )
    if suspension["status"] != "OPEN":
        raise errors.api_error(
            errors.ERR_SUSPENSION_INVALID_STATE, 409, "Suspension is not OPEN"
        )
    now = CLOCK.now()
    suspension["status"] = "CLOSED"
    suspension["closed_at"] = iso_ms(now)
    suspension["credited_seconds"] = int(
        (now - parse_iso(suspension["started_at"])).total_seconds()
    )
    touch(suspension)
    return success_object(serialize_suspension(suspension))


# ---------------------------------------------------------------------------
# TrendSnapshot
# ---------------------------------------------------------------------------


def _month_bounds(period):
    year, month = int(period[:4]), int(period[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _round_half_up_bp(numerator, denominator):
    if denominator == 0:
        return 0
    return int(
        (Decimal(numerator) * Decimal(10000) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


@bp.route("/api/trend-snapshots/compute", methods=["POST"])
def compute_snapshots():
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector", "ComplianceAuditor")
    body = get_body()
    require_present(body, "period")
    period = body.get("period")
    now = CLOCK.now()
    current_month = f"{now.year:04d}-{now.month:02d}"
    if (
        not isinstance(period, str)
        or not _PERIOD_RE.match(period)
        or period > current_month
    ):
        raise errors.invalid_request(
            "period must be YYYY-MM and not beyond the current month"
        )
    force = check_bool(body, "force_recompute", default=False)
    period_start, period_end = _month_bounds(period)
    # Cells: cases CLOSED at snapshot time whose closed_at falls in the month.
    closures = {}
    for case in db.patient_cases.values():
        if case["lifecycle_status"] != "CLOSED" or case["closed_at"] is None:
            continue
        closed_dt = parse_iso(case["closed_at"])
        if period_start <= closed_dt < period_end:
            key = (case["unit_id"], case["grievance_category"])
            closures.setdefault(key, []).append(case)
    # Snapshot-cell uniqueness without force_recompute (atomic: no writes when
    # any cell already exists).
    existing = {}
    for snap in db.trend_snapshots.values():
        if snap["period"] == period:
            existing[(snap["unit_id"], snap["case_category"])] = snap
    if not force:
        for key in closures:
            if key in existing:
                raise errors.api_error(
                    errors.ERR_SNAPSHOT_EXISTS,
                    409,
                    "TrendSnapshot cell for (unit, category, period) exists; pass force_recompute=true",
                )
    cells_written = 0
    cell_rates = []
    for (unit_id, category), cases in sorted(closures.items()):
        grievances = sum(1 for c in cases if c["classification"] == "GRIEVANCE")
        complaints = sum(1 for c in cases if c["classification"] == "COMPLAINT")
        total = len(cases)
        breaches = sum(1 for c in cases if c["resolution_timeliness"] == "LATE")
        headcount = _round_half_up_bp(breaches, total)
        # Exposure-weighted: summed days-late over LATE cases against summed
        # window-days over all closures, both measured against the binding
        # calendar due at closure time.
        days_late_seconds = Decimal(0)
        window_seconds = Decimal(0)
        for c in cases:
            due_raw = c.get("_closure_due_calendar_at")
            if due_raw is None:
                continue
            due_dt = parse_iso(due_raw)
            closed_dt = parse_iso(c["closed_at"])
            received_dt = parse_iso(c["received_at"])
            if c["resolution_timeliness"] == "LATE":
                days_late_seconds += Decimal(
                    str((closed_dt - due_dt).total_seconds())
                )
            window_seconds += Decimal(str((due_dt - received_dt).total_seconds()))
        exposure = 0
        if window_seconds != 0:
            exposure = int(
                (
                    days_late_seconds * Decimal(10000) / window_seconds
                ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
        # SYSTEMIC escalations auto-created for this unit+category whose
        # triggering case closed in the period.
        case_ids = {c["id"] for c in cases}
        systemic_new = sum(
            1
            for e in db.escalations.values()
            if e["case_id"] in case_ids
            and e["escalation_type"] == "SYSTEMIC"
            and e["source"] == "AUTO_SYSTEMIC_THRESHOLD"
        )
        snap = existing.get((unit_id, category))
        if snap is None:
            snap = stamp_new()
            snap.update({"unit_id": unit_id, "case_category": category, "period": period})
            db.trend_snapshots[snap["id"]] = snap
        snap.update(
            {
                "grievances_closed": grievances,
                "complaints_closed": complaints,
                "breaches": breaches,
                "headcount_rate_bp": headcount,
                "exposure_weighted_rate_bp": exposure,
                "systemic_new_count": systemic_new,
            }
        )
        touch(snap)
        cells_written += 1
        if total > 0:
            cell_rates.append(headcount)
    # Pinned rounding order: per-cell rates round first, then the mean rounds.
    if cell_rates:
        system_rate = int(
            (
                Decimal(sum(cell_rates)) / Decimal(len(cell_rates))
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    else:
        system_rate = 0
    return success_object(
        {
            "period": period,
            "cells_created": cells_written,
            "system_rate_bp": system_rate,
        },
        201,
    )


@bp.route("/api/trend-snapshots", methods=["GET"])
def list_snapshots():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    unit_id = request.args.get("unit_id")
    period = request.args.get("period")
    snapshots = list(db.trend_snapshots.values())
    if unit_id is not None:
        snapshots = [s for s in snapshots if s["unit_id"] == unit_id]
    if period is not None:
        snapshots = [s for s in snapshots if s["period"] == period]
    snapshots = sorted_by_creation(snapshots)
    page, total = paginate(snapshots, limit, offset)
    return success_list([serialize_snapshot(s) for s in page], limit, offset, total)


@bp.route("/api/trend-snapshots/<snapshot_id>", methods=["GET"])
def get_snapshot(snapshot_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    snapshot = db.trend_snapshots.get(snapshot_id)
    if snapshot is None:
        raise errors.not_found(errors.ERR_SNAPSHOT_NOT_FOUND, "TrendSnapshot not found")
    return success_object(serialize_snapshot(snapshot))
