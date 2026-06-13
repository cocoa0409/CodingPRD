"""League series endpoints (PRD §3.8): create (fan-out child permits) + cancel
cascade."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import serializers
from clock import now as clock_now
from db import db, stamp_create, touch
from helpers import parse_body, require_fields, require_int, parse_dt, paginate, sort_by_created
from middleware import get_identity, require_roles
from response import success
from services import domain

bp = Blueprint("leagues", __name__)


def get_league_or_404(league_id):
    lg = db.league_series.get(league_id)
    if lg is None:
        raise errors.err(errors.ERR_NOT_FOUND, "League series not found")
    return lg


@bp.post("/leagues")
def create_league():
    user_id, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    body = parse_body()
    require_fields(body, ["facility_id", "patron_id", "weekday", "start_hour",
                          "duration_minutes", "first_date", "occurrences"])

    facility = db.facilities.get(body["facility_id"])
    if facility is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Facility not found")
    patron = db.patrons.get(body["patron_id"])
    if patron is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Patron not found")
    coi_id = body.get("coi_id")
    if coi_id is not None and db.insurance_certificates.get(coi_id) is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Insurance certificate not found")

    if role == "Patron" and body["patron_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Patron may only create their own league")

    weekday = require_int(body, "weekday", minimum=0, maximum=6)
    start_hour = require_int(body, "start_hour", minimum=0, maximum=23)
    duration = require_int(body, "duration_minutes", minimum=1)
    occurrences = require_int(body, "occurrences", minimum=1, maximum=26)
    first_date = parse_dt(body["first_date"], "first_date")

    # Build child permit windows at weekly cadence. The first occurrence anchors
    # to first_date's calendar date at start_hour (UTC).
    base = first_date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    now = clock_now()
    windows = []
    for i in range(occurrences):
        start_at = base + timedelta(weeks=i)
        end_at = start_at + timedelta(minutes=duration)
        # Well-formedness check applies to league create (PRD §3.3).
        if not (start_at < end_at) or start_at <= now or end_at <= now:
            raise errors.err(errors.ERR_INVALID_WINDOW,
                             "League occurrence window malformed or in the past")
        windows.append((start_at, end_at))

    league = {
        "facility_id": body["facility_id"],
        "patron_id": body["patron_id"],
        "coi_id": coi_id,
        "weekday": weekday,
        "start_hour": start_hour,
        "duration_minutes": duration,
        "first_date": first_date,
        "occurrences": occurrences,
        "status": "PENDING",
        "granted_occurrence_count": 0,
        "conflicted_occurrence_count": 0,
    }
    stamp_create(league)
    db.league_series[league["id"]] = league

    for (start_at, end_at) in windows:
        is_prime, tier, quoted = domain.compute_apply_pricing(facility, patron, start_at, end_at)
        child = {
            "facility_id": body["facility_id"],
            "patron_id": body["patron_id"],
            "coi_id": coi_id,
            "league_id": league["id"],
            "lottery_round_id": None,
            "start_at": start_at,
            "end_at": end_at,
            "is_prime_requested": is_prime,
            "status": "APPLIED",
            "pricing_residency": tier,
            "quoted_fee_cents": quoted,
            "final_fee_cents": None,
            "deposit_held_cents": 0,
            "refunded_cents": 0,
            "cancelled_lead_hours": None,
        }
        stamp_create(child)
        db.permits[child["id"]] = child

    return success(serializers.league_series(league), status=201)


@bp.get("/leagues/<league_id>")
def get_league(league_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron", "FinanceClerk"})
    lg = get_league_or_404(league_id)
    return success(serializers.league_series(lg))


@bp.get("/leagues/<league_id>/permits")
def list_league_permits(league_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron", "FinanceClerk"})
    get_league_or_404(league_id)
    items = [p for p in db.permits.values() if p.get("league_id") == league_id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.permit(p) for p in page], pagination=meta)


@bp.post("/leagues/<league_id>/cancel")
def cancel_league(league_id):
    user_id, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    lg = get_league_or_404(league_id)

    if role == "Patron" and lg["patron_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Patron may only cancel their own league")

    if lg["status"] == "CANCELLED":
        raise errors.err(errors.ERR_INVALID_STATE, "League series already CANCELLED")

    body = parse_body()
    refund_destination = body.get("refund_destination")
    if refund_destination is not None and refund_destination not in ("ORIGINAL", "CREDIT"):
        raise errors.err(errors.ERR_VALIDATION, "refund_destination must be ORIGINAL or CREDIT")

    # Mark league cancelled first so child roll-ups don't fight the terminal state.
    lg["status"] = "CANCELLED"
    touch(lg)

    # Cascade: cancel every non-terminal child permit through the permit cancel path.
    terminal = {"DENIED", "CANCELLED", "COMPLETED", "NO_SHOW"}
    children = [p for p in db.permits.values() if p.get("league_id") == league_id]
    for child in sort_by_created(children):
        if child["status"] in terminal:
            continue
        if child["status"] in ("APPLIED", "GRANTED"):
            domain.cancel_permit(child, refund_destination)
        else:
            # WAITLISTED children: move to CANCELLED with no refund (nothing held).
            child["status"] = "CANCELLED"
            touch(child)

    return success(serializers.league_series(lg))


@bp.get("/leagues")
def list_leagues():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron", "FinanceClerk"})
    items = list(db.league_series.values())
    for key in ("facility_id", "patron_id", "coi_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [lg for lg in items if lg.get(key) == val]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.league_series(lg) for lg in page], pagination=meta)
