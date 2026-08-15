"""Photographer endpoints."""

import re
from flask import Blueprint, request
from db import (
    photographers, payment_runs, new_id, now_iso,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_PHOTOGRAPHER_NOT_FOUND,
    ERR_INVALID_STATE, ERR_STALE_VERSION,
)
from response import success_object, success_list
from middleware import get_auth, require_role, check_photographer_ownership
from serializers import serialize_photographer, serialize_payment_run
from services.calculations import compute_payout
from db import parse_iso

bp = Blueprint("photographers", __name__)


@bp.route("/photographers", methods=["POST"])
def create_photographer():
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor"})

    body = request.get_json(force=True, silent=True) or {}

    # Priority 3: request shape
    full_name = body.get("full_name")
    email = body.get("email")
    photographer_type = body.get("photographer_type")
    day_rate_cents = body.get("day_rate_cents")
    per_image_fee_cents = body.get("per_image_fee_cents")
    royalty_rate_per_use_cents = body.get("royalty_rate_per_use_cents")
    rights_reversion_months = body.get("rights_reversion_months", 24)

    if not full_name or not isinstance(full_name, str):
        raise ApiError(ERR_INVALID_REQUEST, "full_name is required and must be a string", 400)
    if not email or not isinstance(email, str):
        raise ApiError(ERR_INVALID_REQUEST, "email is required and must be a string", 400)
    if photographer_type not in ("STAFF", "FREELANCE"):
        raise ApiError(ERR_INVALID_REQUEST, "photographer_type must be STAFF or FREELANCE", 400)
    for field_name, val in [("day_rate_cents", day_rate_cents),
                             ("per_image_fee_cents", per_image_fee_cents),
                             ("royalty_rate_per_use_cents", royalty_rate_per_use_cents)]:
        if val is None or not isinstance(val, int) or isinstance(val, bool):
            raise ApiError(ERR_INVALID_REQUEST, f"{field_name} is required and must be an integer", 400)
    if rights_reversion_months is not None and (not isinstance(rights_reversion_months, int) or isinstance(rights_reversion_months, bool)):
        raise ApiError(ERR_INVALID_REQUEST, "rights_reversion_months must be an integer", 400)
    if rights_reversion_months is None:
        rights_reversion_months = 24

    pid = new_id()
    now = now_iso()
    photog = {
        "id": pid,
        "full_name": full_name,
        "email": email,
        "photographer_type": photographer_type,
        "day_rate_cents": day_rate_cents,
        "per_image_fee_cents": per_image_fee_cents,
        "royalty_rate_per_use_cents": royalty_rate_per_use_cents,
        "rights_reversion_months": rights_reversion_months,
        "status": "ACTIVE",
        "accrued_earnings_cents": 0,
        "paid_out_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    photographers[pid] = photog
    return success_object(serialize_photographer(photog), 201)


@bp.route("/photographers/<pid>", methods=["GET"])
def get_photographer(pid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "FinanceAdmin", "Archivist", "Photographer"})
    check_photographer_ownership(user_id, role, pid)

    photog = photographers.get(pid)
    if photog is None:
        raise ApiError(ERR_PHOTOGRAPHER_NOT_FOUND, f"Photographer {pid} not found", 404)
    return success_object(serialize_photographer(photog))


@bp.route("/photographers/<pid>/suspend", methods=["POST"])
def suspend_photographer(pid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor"})

    photog = photographers.get(pid)
    if photog is None:
        raise ApiError(ERR_PHOTOGRAPHER_NOT_FOUND, f"Photographer {pid} not found", 404)

    if photog["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, f"Cannot suspend photographer in status {photog['status']}", 409)

    photog["status"] = "SUSPENDED"
    photog["updated_at"] = now_iso()
    photog["version"] += 1
    return success_object(serialize_photographer(photog))


@bp.route("/photographers/<pid>/reactivate", methods=["POST"])
def reactivate_photographer(pid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor"})

    photog = photographers.get(pid)
    if photog is None:
        raise ApiError(ERR_PHOTOGRAPHER_NOT_FOUND, f"Photographer {pid} not found", 404)

    if photog["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot reactivate photographer in status {photog['status']}", 409)

    photog["status"] = "ACTIVE"
    photog["updated_at"] = now_iso()
    photog["version"] += 1
    return success_object(serialize_photographer(photog))


@bp.route("/photographers/<pid>/payment-runs", methods=["GET"])
def list_payment_runs(pid):
    user_id, role = get_auth()
    require_role(role, {"FinanceAdmin", "Photographer"})
    check_photographer_ownership(user_id, role, pid)

    photog = photographers.get(pid)
    if photog is None:
        raise ApiError(ERR_PHOTOGRAPHER_NOT_FOUND, f"Photographer {pid} not found", 404)

    # Pagination
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    # Filter
    status_filter = request.args.get("status")

    runs = [pr for pr in payment_runs.values() if pr["photographer_id"] == pid]
    if status_filter:
        runs = [pr for pr in runs if pr["status"] == status_filter]

    # Sort by created_at ascending
    runs.sort(key=lambda r: r["created_at"])

    total = len(runs)
    page = runs[offset:offset + limit]
    return success_list([serialize_payment_run(pr) for pr in page], limit, offset, total)


@bp.route("/photographers/<pid>/payment-runs", methods=["POST"])
def create_payment_run(pid):
    user_id, role = get_auth()
    require_role(role, {"FinanceAdmin"})

    body = request.get_json(force=True, silent=True) or {}

    # Priority 3: request shape
    period_start = body.get("period_start")
    period_end = body.get("period_end")
    expected_version = body.get("expected_photographer_version")

    if not period_start or not isinstance(period_start, str):
        raise ApiError(ERR_INVALID_REQUEST, "period_start is required", 400)
    if not period_end or not isinstance(period_end, str):
        raise ApiError(ERR_INVALID_REQUEST, "period_end is required", 400)

    ps = parse_iso(period_start)
    pe = parse_iso(period_end)
    if ps is None or pe is None:
        raise ApiError(ERR_INVALID_REQUEST, "period_start and period_end must be valid ISO 8601 datetimes", 400)
    if pe <= ps:
        raise ApiError(ERR_INVALID_REQUEST, "period_end must be strictly after period_start", 400)

    # Priority 4: existence
    photog = photographers.get(pid)
    if photog is None:
        raise ApiError(ERR_PHOTOGRAPHER_NOT_FOUND, f"Photographer {pid} not found", 404)

    # Priority 23: payment period lock — check overlapping APPROVED/PAID runs
    for existing in payment_runs.values():
        if existing["photographer_id"] != pid:
            continue
        if existing["status"] not in ("APPROVED", "PAID"):
            continue
        eps = parse_iso(existing["period_start"])
        epe = parse_iso(existing["period_end"])
        if eps is None or epe is None:
            continue
        # Half-open overlap: [ps, pe) intersects [eps, epe)
        if ps < epe and eps < pe:
            raise ApiError("ERR_PAYMENT_PERIOD_LOCKED",
                           "Period overlaps an APPROVED or PAID payment run", 409)

    # Priority 25: OCC — must fire BEFORE the auto-void side effect so a stale
    # writer never voids state it never observed (§2.7, §2.9 atomicity).
    if expected_version is not None and expected_version != photog["version"]:
        raise ApiError(ERR_STALE_VERSION, "Photographer version mismatch", 412)

    # Auto-void overlapping DRAFT runs
    for existing in payment_runs.values():
        if existing["photographer_id"] != pid:
            continue
        if existing["status"] != "DRAFT":
            continue
        eps = parse_iso(existing["period_start"])
        epe = parse_iso(existing["period_end"])
        if eps is None or epe is None:
            continue
        if ps < epe and eps < pe:
            existing["status"] = "VOIDED"
            existing["updated_at"] = now_iso()
            existing["version"] += 1

    # Compute payout
    payout = compute_payout(photog, period_start, period_end)

    # Increment photographer version
    photog["version"] += 1
    photog["updated_at"] = now_iso()

    prid = new_id()
    now = now_iso()
    run = {
        "id": prid,
        "photographer_id": pid,
        "period_start": period_start,
        "period_end": period_end,
        "method": payout["method"],
        "guarantee_amount_cents": payout["guarantee_amount_cents"],
        "royalty_amount_cents": payout["royalty_amount_cents"],
        "clawback_cents": payout["clawback_cents"],
        "total_cents": payout["total_cents"],
        "paid_at": None,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    payment_runs[prid] = run
    return success_object(serialize_payment_run(run), 201)
