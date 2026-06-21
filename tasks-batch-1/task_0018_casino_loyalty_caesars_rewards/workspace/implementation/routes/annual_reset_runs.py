"""AnnualResetRun endpoints."""
from flask import Blueprint, request

import clock
import db
from auth import require_role
from common import (
    get_json_or_400, require_int, require_iso_datetime,
    parse_pagination, paginate, stamp_create, stamp_update, get_or_404,
)
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_RESET_YEAR_TAKEN,
    ERR_RESET_NOT_DUE, ERR_RESET_ALREADY_DUE,
)
from response import success_object, success_array
from services.serializers import annual_reset_run_view


bp = Blueprint("annual_reset_runs", __name__)


@bp.route("/annual-reset-runs", methods=["POST"])
def create_run():
    require_role({"ComplianceOfficer"})
    body = get_json_or_400()
    reset_year = require_int(body, "reset_year", minimum=2020)
    scheduled_for_dt = require_iso_datetime(body, "scheduled_for")

    with db.lock:
        # priority 17: reset_year unique across SCHEDULED rows.
        for r in db.annual_reset_runs.values():
            if r["reset_year"] == reset_year and r["status"] == "SCHEDULED":
                raise ApiError(ERR_RESET_YEAR_TAKEN, 409,
                               "another SCHEDULED reset already exists for reset_year")

        row = {
            "reset_year": reset_year,
            "scheduled_for": clock.iso(scheduled_for_dt),
            "status": "SCHEDULED",
            "members_reset_count": 0,
            "tier_credits_lifetime_invariant_before_cents": 0,
            "tier_credits_lifetime_invariant_after_cents": 0,
        }
        stamp_create(row)
        db.annual_reset_runs[row["id"]] = row
        return success_object(annual_reset_run_view(row), 201)


@bp.route("/annual-reset-runs/<rid>/execute", methods=["POST"])
def execute_run(rid):
    require_role({"ComplianceOfficer"})
    with db.lock:
        r = get_or_404(db.annual_reset_runs, rid, "annual reset run")
        if r["status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "reset run is not SCHEDULED")

        # also reject if another SCHEDULED run exists for the same year (Rule per PRD §3.8).
        for other in db.annual_reset_runs.values():
            if other["id"] == r["id"]:
                continue
            if other["reset_year"] == r["reset_year"] and other["status"] == "SCHEDULED":
                raise ApiError(ERR_INVALID_STATE, 409,
                               "another SCHEDULED reset exists for the same reset_year")

        scheduled_for_dt = clock.parse_iso(r["scheduled_for"])
        now = clock.now()
        if not (now >= scheduled_for_dt):
            raise ApiError(ERR_RESET_NOT_DUE, 422,
                           "current_utc is before scheduled_for")

        # Capture invariant before.
        before_sum_cents = _sum_lifetime_cents()
        r["tier_credits_lifetime_invariant_before_cents"] = before_sum_cents

        count = 0
        for m in db.members.values():
            if m["exclusion_status"] == "EXCLUDED":
                continue
            m["tier_credits_ytd"] = 0
            m["tier_status"] = "GOLD"
            stamp_update(m)
            count += 1
        r["members_reset_count"] = count

        after_sum_cents = _sum_lifetime_cents()
        r["tier_credits_lifetime_invariant_after_cents"] = after_sum_cents
        # The invariant is guaranteed by construction (we never touch
        # tier_credits_lifetime here) — but we still expose both values.

        r["status"] = "EXECUTED"
        stamp_update(r)
        return success_object(annual_reset_run_view(r), 200)


@bp.route("/annual-reset-runs/<rid>/cancel", methods=["POST"])
def cancel_run(rid):
    require_role({"ComplianceOfficer"})
    with db.lock:
        r = get_or_404(db.annual_reset_runs, rid, "annual reset run")
        if r["status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "reset run is not SCHEDULED")
        scheduled_for_dt = clock.parse_iso(r["scheduled_for"])
        now = clock.now()
        if not (now < scheduled_for_dt):
            raise ApiError(ERR_RESET_ALREADY_DUE, 422,
                           "scheduled_for has already arrived; cannot cancel")
        r["status"] = "CANCELLED"
        stamp_update(r)
        return success_object(annual_reset_run_view(r), 200)


@bp.route("/annual-reset-runs/<rid>", methods=["GET"])
def get_run(rid):
    require_role({"ComplianceOfficer"})
    with db.lock:
        r = get_or_404(db.annual_reset_runs, rid, "annual reset run")
        return success_object(annual_reset_run_view(r), 200)


@bp.route("/annual-reset-runs", methods=["GET"])
def list_runs():
    require_role({"ComplianceOfficer"})
    status = request.args.get("status")
    reset_year_raw = request.args.get("reset_year")
    limit, offset = parse_pagination()
    with db.lock:
        rows = list(db.annual_reset_runs.values())
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if reset_year_raw is not None:
            try:
                ry = int(reset_year_raw)
            except (TypeError, ValueError):
                from errors import ERR_INVALID_REQUEST
                raise ApiError(ERR_INVALID_REQUEST, 400, "reset_year must be integer")
            rows = [r for r in rows if r["reset_year"] == ry]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([annual_reset_run_view(r) for r in page], limit, offset, total, 200)


def _sum_lifetime_cents() -> int:
    """Lifetime values are floats with 2dp precision (per accrual); convert
    to integer cents by multiplying by 100 with round-half-up."""
    from decimal import Decimal, ROUND_HALF_UP
    total = Decimal("0")
    for m in db.members.values():
        total += Decimal(str(m["tier_credits_lifetime"]))
    cents = (total * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)
